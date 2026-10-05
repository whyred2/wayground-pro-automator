"""
Wayground Answer Retrieval Engine:
Fetches answer keys via:
1. Wayground Game API (PIN -> checkRoom -> getQuestions)
2. Wayground public library search + Quiz API — verified against game questions
3. Quizit Online Bot API — optional fallback when direct answers are unavailable
4. Network interception & DOM inspection — captures answer keys when supplied by the server
"""

import asyncio
import urllib.request
import urllib.error
import json
import re
import html
import time
import uuid
from urllib.parse import urlparse, parse_qs

from ui import log_step
from answer_db import AnswerDatabase

# ─── Shared state for discovery ─────────────────────────────────
_answers_ready_event = asyncio.Event()
_cached_answers_db: dict[str, list[str]] | None = None
_cached_source: str = "Unknown"

_discovered_pin: str | None = None
_discovered_hash: str | None = None
_discovered_quiz_id: str | None = None

# Single-flight deduplication & bot control
_in_progress_pins: set[str] = set()
_completed_pins: dict[str, dict[str, list[str]]] = {}
_allow_quizit_bot: bool = True
_quizit_sign_in_required: bool = False

HEX_24_REGEX = re.compile(r"^[a-fA-F0-9]{24}$")
PIN_REGEX = re.compile(r"^\d{4,9}$")
ROOM_HASH_REGEX = re.compile(r"^[a-zA-Z0-9_-]{10,128}$")
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def _request_json(url: str, payload: dict | None = None, extra_headers: dict | None = None) -> dict:
    headers = dict(API_HEADERS)
    headers.update(extra_headers or {})
    raw = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        raw = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=raw, headers=headers)
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("API returned an invalid JSON object")
    if data.get("success") is False or data.get("error"):
        raise ValueError(str(data.get("message") or data.get("error") or "API request failed"))
    return data


def set_allow_quizit_bot(allowed: bool):
    """Toggle whether Quizit Bot API is permitted to connect to live game PINs."""
    global _allow_quizit_bot
    _allow_quizit_bot = allowed


def is_quizit_bot_allowed() -> bool:
    """Return whether Quizit Bot is currently allowed."""
    return _allow_quizit_bot


def is_quizit_sign_in_required() -> bool:
    """Report when the anonymous Quizit API requires a browser login."""
    return _quizit_sign_in_required


def get_discovered_pin() -> str | None:
    """Return the Game PIN captured by the network listener, if any."""
    global _discovered_pin
    return _discovered_pin


def reset_answer_state():
    """Start discovery for the selected test page, without reusing another quiz."""
    global _answers_ready_event, _cached_answers_db, _cached_source
    global _discovered_pin, _discovered_hash, _discovered_quiz_id
    global _quizit_sign_in_required
    _answers_ready_event = asyncio.Event()
    _cached_answers_db = None
    _cached_source = "Unknown"
    _discovered_pin = _discovered_hash = _discovered_quiz_id = None
    _quizit_sign_in_required = False


def is_valid_quiz_id(val: any) -> bool:
    """Check if a value is a valid 24-character hexadecimal MongoDB ObjectId."""
    return isinstance(val, str) and len(val.strip()) == 24 and bool(HEX_24_REGEX.match(val.strip()))


def is_valid_game_pin(val: any) -> bool:
    """Check if a value is a valid 4-9 digit game PIN."""
    return isinstance(val, str) and bool(PIN_REGEX.match(val.strip()))


def _set_answers(answers: dict[str, list[str]], source: str):
    """Event-safe setter for globally retrieved answers."""
    global _cached_answers_db, _cached_source
    if answers:
        if _cached_answers_db is None:
            _cached_answers_db = answers
            _cached_source = source
        else:
            _cached_answers_db.update(answers)
        _answers_ready_event.set()


# ─── API 1: Quizit Online Bot API (Game PIN) ────────────────────

def parse_quizit_answers(data: dict) -> dict[str, list[str]]:
    """Parse supplied Quizit keys, rejecting an explicitly unsolved result."""
    if not isinstance(data, dict):
        raise ValueError("Quizit returned an invalid JSON object")
    if data.get("solved") is False:
        raise ValueError("Quizit could not retrieve the answer keys for this game")
    questions = data.get("questions", []) or data.get("answers", [])
    if not isinstance(questions, list) or not questions:
        raise Exception("Quizit returned no questions")

    answers_db = AnswerDatabase()
    for item in questions:
        if not isinstance(item, dict):
            continue
        q_id = str(item.get("id") or item.get("_id") or "").strip()
        q_info = item.get("question") if isinstance(item.get("question"), dict) else {}
        q_raw = q_info.get("text", "") if q_info else (item.get("question") if isinstance(item.get("question"), str) else "")
        q_text = html.unescape(re.sub(r"<[^<]+?>", "", q_raw)).strip() if q_raw else ""
        q_image = str(q_info.get("image", "") or "").strip()

        # Extract correct answers (texts, option images)
        answers_list = item.get("answers", [])
        correct_texts = []
        if isinstance(answers_list, list):
            for a in answers_list:
                if isinstance(a, dict):
                    a_raw = a.get("text", "")
                    a_img = a.get("image", "")
                elif isinstance(a, str):
                    a_raw = a
                    a_img = ""
                else:
                    continue
                if a_raw:
                    a_text = html.unescape(re.sub(r"<[^<]+?>", "", a_raw)).strip()
                    if a_text and a_text not in correct_texts:
                        correct_texts.append(a_text)
                if a_img:
                    img_file = a_img.split("/")[-1].split("?")[0].strip()
                    if img_file and img_file not in correct_texts:
                        correct_texts.append(img_file)

        if correct_texts:
            answers_db.add_question(q_text, correct_texts, qid=q_id,
                                    images=[q_image] if q_image else [])

    if not answers_db:
        raise Exception("Failed to parse question-answer pairs from Quizit")

    return answers_db


def fetch_quizit_answers(pin: str) -> dict[str, list[str]]:
    """
    Fetch answers from Quizit Online Bot API using a game PIN.
    Strictly deduplicated: only one HTTP request is ever made per PIN.
    Returns { question_text: [correct_answer1, ...], qid: [...], img_url: [...] }
    """
    global _in_progress_pins, _completed_pins, _quizit_sign_in_required

    clean_pin = re.sub(r"\D", "", str(pin).strip())
    if not clean_pin:
        raise ValueError("Invalid game PIN")

    if clean_pin in _completed_pins:
        return _completed_pins[clean_pin]

    if clean_pin in _in_progress_pins:
        # Another coroutine is already fetching this PIN, wait for it
        for _ in range(110):
            time.sleep(0.3)
            if clean_pin in _completed_pins:
                return _completed_pins[clean_pin]
            if clean_pin not in _in_progress_pins:
                break
        else:
            raise ValueError("A Quizit request for this PIN is already in progress")

    _in_progress_pins.add(clean_pin)
    try:
        url = f"https://api.quizit.online/quizizz/bot?pin={clean_pin}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}")
            data = json.loads(response.read().decode("utf-8"))

        answers_db = parse_quizit_answers(data)

        _completed_pins[clean_pin] = answers_db
        return answers_db
    except urllib.error.HTTPError as e:
        if e.code == 401:
            _quizit_sign_in_required = True
            raise ValueError("Quizit requires sign-in to a Quizit account. Use the signed-in browser fallback.") from e
        raise ValueError(f"Quizit API error: HTTP {e.code}") from e
    except Exception as e:
        raise Exception(f"Quizit API error: {e}")
    finally:
        _in_progress_pins.discard(clean_pin)


# ─── API 2: Wayground Direct API (_quizserver) ──────────────────

def _clean_text(value) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<br\s*/?>|</p>|</div>", " ", value, flags=re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", text)).split())


def _get_questions(payload: dict) -> list[dict]:
    """Accept quizserver lists and game API question maps, excluding placeholders."""
    containers = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        containers.append(data)
    for container in list(containers):
        for key in ("room", "quiz"):
            value = container.get(key)
            if isinstance(value, dict):
                containers.append(value)
                if isinstance(value.get("info"), dict):
                    containers.append(value["info"])
    for container in containers:
        questions = container.get("questions")
        if isinstance(questions, dict):
            real_questions = [dict(q, _id=q.get("_id") or q.get("id") or qid)
                              for qid, q in questions.items() if isinstance(q, dict)]
            if real_questions:
                return real_questions
        if isinstance(questions, list):
            real_questions = [q for q in questions if isinstance(q, dict)]
            if real_questions:
                return real_questions
    return []


def _media_urls(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(media["url"]) for media in value
            if isinstance(media, dict) and media.get("url")]


def _blank_answer_texts(structure: dict) -> list[str]:
    """Resolve explicit BLANK target/option IDs; choose one accepted text per blank."""
    answer = structure.get("answer")
    targets = structure.get("targets")
    options = structure.get("options")
    if not all(isinstance(value, list) and value for value in (answer, targets, options)):
        return []
    target_ids = [target.get("id") for target in targets if isinstance(target, dict)]
    if len(target_ids) != len(targets) or not all(isinstance(target, str) and target for target in target_ids):
        return []
    if len(set(target_ids)) != len(target_ids):
        return []
    query = structure.get("query") or {}
    query_text = query.get("text", "") if isinstance(query, dict) else ""
    query_targets = re.findall(r"<blank\b[^>]*\bid\s*=\s*[\"']([^\"']+)[\"']", query_text, re.I)
    if query_targets:
        if len(query_targets) != len(target_ids) or set(query_targets) != set(target_ids):
            return []
        target_ids = query_targets
    by_target = {}
    for item in answer:
        if not isinstance(item, dict) or item.get("targetId") not in target_ids:
            return []
        target_id = item["targetId"]
        if target_id in by_target:
            return []
        ids = item.get("optionId")
        if isinstance(ids, str):
            ids = [ids]
        if not isinstance(ids, list) or not ids or not all(isinstance(option_id, str) for option_id in ids):
            return []
        target = next(target for target in targets if target["id"] == target_id)
        references = target.get("optionId")
        if references is not None:
            if not isinstance(references, list) or not all(isinstance(reference, str) for reference in references):
                return []
            if not set(ids).issubset(references):
                return []
        by_target[target_id] = ids
    options_by_id = {}
    for option in options:
        if not isinstance(option, dict):
            continue
        for option_id in (option.get("id"), option.get("_id")):
            if not isinstance(option_id, str) or not option_id:
                continue
            if option_id in options_by_id and options_by_id[option_id] != option:
                return []
            options_by_id[option_id] = option
    texts = []
    for target_id in target_ids:
        ids = by_target.get(target_id, [])
        if not ids or any(option_id not in options_by_id for option_id in ids):
            return []
        accepted = [_clean_text(options_by_id[option_id].get("text")) for option_id in ids]
        accepted = [text for text in accepted if text]
        if not accepted:
            return []
        # Multiple IDs for one target are alternative accepted spellings,
        # whereas multiple targets are separate inputs in question order.
        texts.append(accepted[0])
    return texts


def parse_wayground_answers(payload: dict) -> dict[str, list[str]]:
    """Only use explicit server answer keys; options alone are never answers."""
    answers_db = AnswerDatabase()
    for q in _get_questions(payload):
        structure = q.get("structure")
        if not isinstance(structure, dict) or "answer" not in structure:
            continue
        answer = structure["answer"]
        if answer is None or isinstance(answer, bool):
            continue
        query = structure.get("query") or {}
        if not isinstance(query, dict):
            query = {}
        q_text = _clean_text(query.get("text"))
        q_id = str(q.get("_id") or q.get("id") or "").strip()
        options = structure.get("options") or []
        if not isinstance(options, list):
            options = []
        values = answer if isinstance(answer, list) else [answer]
        kind = str(q.get("type") or structure.get("kind") or "").upper()
        correct_texts = _blank_answer_texts(structure) if kind == "BLANK" else []
        for value in values if kind != "BLANK" else []:
            option_values = []
            if isinstance(value, bool):
                continue
            if kind in ("FIB", "FITB") and isinstance(value, str):
                option_values = [_clean_text(value)]
            elif isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                index = int(value)
                if not 0 <= index < len(options) or not isinstance(options[index], dict):
                    continue
                option = options[index]
                text = _clean_text(option.get("text"))
                if text:
                    option_values.append(text)
                for image in _media_urls(option.get("media")):
                    filename = urlparse(image).path.rsplit("/", 1)[-1]
                    if filename:
                        option_values.append(filename)
                if not option_values:
                    option_values = [f"option-{index}", f"index:{index}"]
            for text in option_values:
                if text and text not in correct_texts:
                    correct_texts.append(text)
        if not correct_texts:
            continue
        images = _media_urls(query.get("media"))
        option_info = []
        for option in options:
            if not isinstance(option, dict):
                continue
            option_images = _media_urls(option.get("media"))
            option_info.append({"text": _clean_text(option.get("text")),
                                "img_src": option_images[0] if option_images else ""})
        answers_db.add_question(q_text, correct_texts, qid=q_id, images=images, options=option_info)
    return answers_db


def _fetch_quiz_payload(quiz_id: str) -> dict:
    clean_id = quiz_id.strip()
    if not is_valid_quiz_id(clean_id):
        raise ValueError("The Quiz API requires a 24-character quiz ID")
    url = f"https://wayground.com/_quizserver/main/v2/quiz/{clean_id}?convertQuestions=false&includeFsFeatures=true&sanitize=read&questionMetadata=true&includeUserHydratedVariants=true"
    return _request_json(url)


def fetch_api_answers(quiz_id: str) -> dict[str, list[str]]:
    """Fetch explicit answer keys from a public quiz with a MongoDB ObjectId."""
    return parse_wayground_answers(_fetch_quiz_payload(quiz_id))


def _game_resource_metadata(room_hash: str) -> dict:
    """Read the library title even when the game exposes an opaque quiz ID."""
    payload = _request_json(f"https://wayground.com/_gameapi/main/public/v1/students/games/{room_hash}")
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {}
    quizzes = data.get("quizzes") or {}
    items = data.get("items") or []
    if not isinstance(items, list) or not isinstance(quizzes, dict):
        return {}
    for item in items:
        if not isinstance(item, dict) or item.get("_id") != room_hash:
            continue
        quiz_id = item.get("quizId")
        quiz = quizzes.get(quiz_id) if isinstance(quiz_id, str) else None
        return {"quiz_id": quiz_id,
                "name": _clean_text(quiz.get("name")) if isinstance(quiz, dict) else ""}
    return {}


def _verified_quiz_answers(game_questions: list[dict], quiz_payload: dict) -> dict[str, list[str]]:
    """Accept library keys only for the same question IDs and unchanged content."""
    if not game_questions:
        return {}
    source_questions = {}
    for source_question in _get_questions(quiz_payload):
        qid = str(source_question.get("_id") or source_question.get("id") or "")
        if not qid or qid in source_questions:
            return {}
        source_questions[qid] = source_question
    selected = []
    seen_ids = set()
    for game_question in game_questions:
        qid = str(game_question.get("_id") or game_question.get("id") or "")
        if not qid or qid in seen_ids or qid not in source_questions:
            return {}
        seen_ids.add(qid)
        source_question = source_questions[qid]
        game_structure = game_question.get("structure")
        source_structure = source_question.get("structure")
        if not isinstance(game_structure, dict) or not isinstance(source_structure, dict):
            return {}
        # These fields include question/option text, media and option IDs.
        # Matching IDs alone would miss an edited question or reordered options.
        if any(game_structure.get(key) != source_structure.get(key)
               for key in ("query", "kind")):
            return {}
        if game_question.get("type") != source_question.get("type"):
            return {}
        blank = (game_question.get("type") or game_structure.get("kind")) == "BLANK"
        if blank:
            # BLANK options contain the answers themselves and are stripped from
            # the game response. The unchanged targets retain their option IDs.
            targets = game_structure.get("targets")
            if not targets or targets != source_structure.get("targets"):
                return {}
            if game_question.get("ver") != source_question.get("ver"):
                return {}
        if game_structure.get("options") != source_structure.get("options"):
            if not blank or game_structure.get("options") not in (None, []):
                return {}
        selected.append(source_question)
    answers = parse_wayground_answers({"questions": selected})
    return answers if all(f"id:{qid}" in answers for qid in seen_ids) else {}


def _search_public_quizzes(title: str) -> list[dict]:
    """Use the same public library search endpoint as the teacher panel."""
    session_id = str(uuid.uuid4())
    payload = {
        "query": title, "queryId": str(uuid.uuid4()), "sessionId": session_id,
        "page": "explore-ssr", "source": "HeroSearchBar", "from": 0, "size": 10,
        "includeQuestions": False, "includeSources": ["questionTypes"],
        "sortBy": {"key": "_score", "order": "desc"},
        "filters": {"contentTypes": ["quiz"]},
    }
    response = _request_json(
        "https://wayground.com/_sserverv2/main/v3/search/public?includeCollections=false",
        payload, {"X-Q-Sessionid": session_id},
    )
    data = response.get("data") or {}
    hits = data.get("hits") if isinstance(data, dict) else None
    return [hit for hit in hits if isinstance(hit, dict)] if isinstance(hits, list) else []


def _fetch_library_answers(title: str, game_questions: list[dict]) -> dict[str, list[str]]:
    if not title or not game_questions:
        return {}
    log_step(f"Searching the public library for the original quiz: {title}")
    candidates = _search_public_quizzes(title)
    candidates.sort(key=lambda hit: (
        _clean_text(hit.get("name")).casefold() != title.casefold(),
        hit.get("noOfQuestions") != len(game_questions),
    ))
    tried = set()
    for candidate in candidates:
        quiz_id = candidate.get("quizId")
        if not is_valid_quiz_id(quiz_id) or quiz_id in tried:
            continue
        count = candidate.get("noOfQuestions")
        if isinstance(count, int) and count < len(game_questions):
            continue
        if len(tried) >= 5:
            break
        tried.add(quiz_id)
        try:
            answers = _verified_quiz_answers(game_questions, _fetch_quiz_payload(quiz_id))
        except Exception:
            continue
        if answers:
            log_step(f"Public quiz verified against all {len(game_questions)} game questions (Quiz ID: {quiz_id})")
            return answers
    return {}


def fetch_game_answers(identifier: str) -> dict[str, list[str]]:
    """Read game questions without joining a player or submitting an answer."""
    clean = str(identifier).strip()
    quiz_id = None
    if is_valid_game_pin(clean):
        response = _request_json("https://wayground.com/play-api/v5/checkRoom", {"roomCode": clean})
        room = response.get("room") or response.get("data", {}).get("room") or {}
        if not isinstance(room, dict):
            raise ValueError("Game API returned an invalid room")
        answers = parse_wayground_answers({"room": room})
        if answers:
            return answers
        room_hash = str(room.get("hash") or "").strip()
        quiz_id = room.get("quizId")
    else:
        room_hash = clean
    if not ROOM_HASH_REGEX.fullmatch(room_hash):
        raise ValueError("Game API did not return a valid room hash")
    payload = _request_json("https://wayground.com/play-api/v4/getQuestions", {"roomHash": room_hash})
    answers = parse_wayground_answers(payload)
    if answers:
        return answers
    questions = _get_questions(payload)
    # Some games expose a public quiz ID. Opaque 64-character IDs cannot be
    # sent to quizserver (it returns HTTP 400), so do not treat them as ObjectIds.
    try:
        metadata = _game_resource_metadata(room_hash)
    except Exception:
        metadata = {}
    if not is_valid_quiz_id(quiz_id):
        quiz_id = metadata.get("quiz_id")
    if is_valid_quiz_id(quiz_id):
        try:
            quiz_payload = _fetch_quiz_payload(quiz_id)
            answers = (_verified_quiz_answers(questions, quiz_payload) if questions
                       else parse_wayground_answers(quiz_payload))
            if answers:
                return answers
        except Exception as exc:
            log_step(f"Public quiz lookup: {exc}")
    try:
        answers = _fetch_library_answers(metadata.get("name", ""), questions)
        if answers:
            return answers
    except Exception as exc:
        log_step(f"Public library lookup: {exc}")
    if questions:
        raise ValueError(f"Game API returned {len(questions)} questions, but no supported answer keys. Correct answers may be hidden by the server.")
    raise ValueError("Game API returned no questions or answer keys")


# ─── Resolution Helpers ─────────────────────────────────────────

def resolve_hash_to_pin(room_hash: str) -> str | None:
    """Resolve a game room hash to gameCode (PIN) via Wayground / Quizizz _gameapi."""
    clean_hash = room_hash.strip()
    if not clean_hash:
        return None

    urls = [
        f"https://wayground.com/_gameapi/main/public/v1/students/games/{clean_hash}",
        f"https://quizizz.com/_gameapi/main/public/v1/students/games/{clean_hash}",
    ]

    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    items = data.get("data", {}).get("items", []) or data.get("items", [])
                    if items and isinstance(items, list) and isinstance(items[0], dict):
                        game_code = items[0].get("gameCode")
                        if game_code and str(game_code).strip():
                            return str(game_code).strip()
        except Exception:
            continue

    return None


def resolve_hash_to_quiz_id(room_hash: str) -> str | None:
    """Resolve a game room hash to 24-char quizId via Wayground / Quizizz _gameapi."""
    clean_hash = room_hash.strip()
    if not clean_hash:
        return None

    urls = [
        f"https://wayground.com/_gameapi/main/public/v1/students/games/{clean_hash}",
        f"https://quizizz.com/_gameapi/main/public/v1/students/games/{clean_hash}",
    ]

    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    items = data.get("data", {}).get("items", []) or data.get("items", [])
                    if items and isinstance(items, list) and isinstance(items[0], dict):
                        qid = items[0].get("quizId")
                        if is_valid_quiz_id(qid):
                            return qid
                        # The legacy domain exposes the same opaque ID. It is
                        # not a transport failure and cannot be resolved there.
                        return None
        except Exception:
            continue

    return None


def resolve_pin_to_quiz_id(pin_or_code: str) -> str | None:
    """Resolve a 6-8 digit game PIN to 24-char quizId via checkRoom."""
    clean_pin = re.sub(r"\D", "", pin_or_code.strip())
    if not clean_pin:
        return None

    for base_url in ["https://wayground.com", "https://game.quizizz.com"]:
        url = f"{base_url}/play-api/v5/checkRoom"
        try:
            payload = json.dumps({"roomCode": clean_pin}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    room = data.get("room") or data.get("data", {}).get("room") or {}
                    qid = room.get("quizId")
                    if is_valid_quiz_id(qid):
                        return qid
                    rhash = room.get("hash")
                    if rhash:
                        resolved = resolve_hash_to_quiz_id(rhash)
                        if resolved:
                            return resolved
        except Exception:
            continue

    return None


def extract_quiz_id_from_url(url: str) -> str | None:
    """Extract 24-hex quizId or game PIN from a URL string."""
    if not url:
        return None
    match_hex = re.search(r"[?&]quizId=([a-fA-F0-9]{24})", url)
    if match_hex:
        return match_hex.group(1)
    match_path = re.search(r"/(?:quiz|admin/quiz|pre-game)/([a-fA-F0-9]{24})", url)
    if match_path:
        return match_path.group(1)
    match_gc = re.search(r"[?&]gc=(\d+)", url)
    if match_gc:
        return match_gc.group(1)
    return None


# ─── Unified Identifier Resolver ────────────────────────────────

def _classify_identifier(identifier: str) -> tuple[str, str]:
    clean = str(identifier or "").strip()
    if not clean:
        return "", ""
    if clean.startswith(("http://", "https://")):
        parsed = urlparse(clean)
        host = (parsed.hostname or "").lower()
        if not any(host == domain or host.endswith("." + domain)
                   for domain in ("wayground.com", "quizizz.com")):
            return "", ""
        query = parse_qs(parsed.query)
        pin = query.get("gc", [""])[0]
        if is_valid_game_pin(pin):
            return "pin", pin
        quiz_id = query.get("quizId", [""])[0]
        if is_valid_quiz_id(quiz_id):
            return "quiz", quiz_id
        quiz_match = re.search(r"/(?:quiz|admin/quiz|pre-game)/([a-fA-F0-9]{24})(?:/|$)", parsed.path)
        if quiz_match:
            return "quiz", quiz_match.group(1)
        # /join/game/<encrypted session> is not a room hash.
        hash_match = re.fullmatch(r"/join/([a-zA-Z0-9_-]{10,128})/?", parsed.path)
        return ("hash", hash_match.group(1)) if hash_match else ("", "")
    if is_valid_game_pin(clean):
        return "pin", clean
    if is_valid_quiz_id(clean):
        return "id", clean
    if ROOM_HASH_REGEX.fullmatch(clean) and not clean.isdigit():
        return "hash", clean
    return "", ""


def fetch_answers_by_any_identifier(identifier: str) -> tuple[dict[str, list[str]] | None, str]:
    """Try Wayground's direct APIs first, then the permitted Quizit fallback."""
    kind, value = _classify_identifier(identifier)
    if not kind:
        return None, ""
    if kind in ("quiz", "id"):
        try:
            db = fetch_api_answers(value)
            if db:
                return db, f"Wayground Quiz API (Quiz ID: {value})"
        except Exception as exc:
            if kind == "quiz":
                log_step(f"Direct Quiz API: {exc}")
        if kind == "quiz":
            return None, ""
    try:
        db = fetch_game_answers(value)
        if db:
            label = "PIN" if kind == "pin" else "Room Hash"
            return db, f"Wayground Game API ({label}: {value})"
    except Exception as exc:
        log_step(f"Direct Game API: {exc}")
    if _allow_quizit_bot and not _quizit_sign_in_required:
        pin = value if kind == "pin" else resolve_hash_to_pin(value)
        if pin:
            try:
                db = fetch_quizit_answers(pin)
                if db:
                    return db, f"Quizit API (Game PIN: {pin})"
            except Exception as exc:
                log_step(f"Quizit fallback failed: {exc}")
    return None, ""


# ─── Network Interception ───────────────────────────────────────

async def intercept_response(response):
    """Capture supplied answer keys and identifiers without spawning a bot."""
    global _discovered_pin, _discovered_hash, _discovered_quiz_id
    parsed = urlparse(response.url or "")
    host = (parsed.hostname or "").lower()
    if not any(host == domain or host.endswith("." + domain)
               for domain in ("wayground.com", "quizizz.com")):
        return
    if not any(part in parsed.path for part in ("/play-api/", "/_gameapi/", "/_quizserver/")):
        return
    if response.status != 200:
        return
    try:
        request = response.request
        if request and request.method in ("POST", "PUT"):
            raw = request.post_data
            if raw and len(raw) < 20000:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    pin = str(payload.get("roomCode") or payload.get("gameCode") or "")
                    if is_valid_game_pin(pin):
                        _discovered_pin = pin
                    room_hash = payload.get("roomHash")
                    if isinstance(room_hash, str) and ROOM_HASH_REGEX.fullmatch(room_hash):
                        _discovered_hash = room_hash
    except Exception:
        pass
    try:
        if "json" not in response.headers.get("content-type", "").lower():
            return
        body = await response.json()
        if not isinstance(body, dict):
            return
        # Do not skip JSON after discovering a PIN: subsequent getQuestions
        # and quizserver responses are where the actual keys can arrive.
        answers = parse_wayground_answers(body)
        if answers:
            _set_answers(answers, "Wayground API (Browser response)")
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        room = body.get("room") or data.get("room") or {}
        if isinstance(room, dict):
            pin = str(room.get("code") or room.get("roomCode") or "")
            if is_valid_game_pin(pin):
                _discovered_pin = pin
            room_hash = room.get("hash") or body.get("roomHash")
            if isinstance(room_hash, str) and ROOM_HASH_REGEX.fullmatch(room_hash):
                _discovered_hash = room_hash
            if is_valid_quiz_id(room.get("quizId")):
                _discovered_quiz_id = room["quizId"]
        items = data.get("items") or body.get("items") or []
        if isinstance(items, list) and items and isinstance(items[0], dict):
            item = items[0]
            if is_valid_game_pin(str(item.get("gameCode") or "")):
                _discovered_pin = str(item["gameCode"])
            if is_valid_quiz_id(item.get("quizId")):
                _discovered_quiz_id = item["quizId"]
        quiz = data.get("quiz") or {}
        if isinstance(quiz, dict) and is_valid_quiz_id(quiz.get("_id")):
            _discovered_quiz_id = quiz["_id"]
    except Exception:
        pass


# ─── Page DOM & Storage Inspection ──────────────────────────────

async def extract_identifiers_from_page(page) -> dict:
    """
    Inspect browser tab DOM, URL, window globals, referrer, cookies, and localStorage
    for game PINs, room hashes, or quiz IDs.
    """
    try:
        result = await page.evaluate("""
            () => {
                const info = { pin: null, hash: null, quizId: null };

                // 1. URL search parameter (?gc=XXXXXX)
                const urlParams = new URLSearchParams(window.location.search);
                if (urlParams.has('gc')) {
                    info.pin = urlParams.get('gc');
                }

                // 2. document.referrer check (e.g. redirected from https://wayground.com/join?gc=00355925)
                if (!info.pin && document.referrer) {
                    const mRef = document.referrer.match(/[?&]gc=(\\d{4,9})/);
                    if (mRef) info.pin = mRef[1];
                }

                // 3. Performance navigation entries
                if (!info.pin && window.performance && window.performance.getEntriesByType) {
                    try {
                        const entries = window.performance.getEntriesByType('navigation');
                        for (const e of entries) {
                            const mNav = (e.name || '').match(/[?&]gc=(\\d{4,9})/);
                            if (mNav) {
                                info.pin = mNav[1];
                                break;
                            }
                        }
                    } catch (e) {}
                }

                // 4. Cookies inspection
                if (!info.pin && document.cookie) {
                    const mCookie = document.cookie.match(/(?:^|;\\s*)(?:gc|roomCode|gameCode|pin)=([^;]+)/i);
                    if (mCookie && /^\\d{4,9}$/.test(mCookie[1].trim())) {
                        info.pin = mCookie[1].trim();
                    }
                }

                // 5. Storage inspection
                for (const store of [window.localStorage, window.sessionStorage]) {
                    if (!store) continue;
                    for (let i = 0; i < store.length; i++) {
                        const k = store.key(i) || '';
                        const v = store.getItem(k) || '';
                        if (!v || v.length > 500000) continue;

                        // Check if key itself is the pin / game code
                        if (/^(?:gc|pin|room_?code|game_?code|code)$/i.test(k) && /^\\d{4,9}$/.test(v.trim())) {
                            if (!info.pin) info.pin = v.trim();
                        }

                        const mPin = v.match(/["']?(?:roomCode|gameCode|code|gc|pin)["']?\\s*[:=]\\s*["']?(\\d{4,9})["']?/i);
                        if (mPin && !info.pin) info.pin = mPin[1];

                        const mHash = v.match(/["']?(?:roomHash|hash)["']?\\s*[:=]\\s*["']([a-zA-Z0-9_-]{10,})["']/i);
                        if (mHash && !info.hash) info.hash = mHash[1];

                        const mQid = v.match(/["']?quizId["']?\\s*[:=]\\s*["']([a-fA-F0-9]{24})["']/i);
                        if (mQid && !info.quizId) info.quizId = mQid[1];
                    }
                }

                // 6. DOM text search for game pin
                const mBody = document.body ? (document.body.innerText || '').match(/(?:Game\\s*(?:Code|PIN)|Код\\s*(?:гри|игры)|PIN)\\s*[:#]?\\s*(\\d{5,8})/i) : null;
                if (mBody && !info.pin) info.pin = mBody[1];

                return info;
            }
        """)
        return result or {}
    except Exception:
        return {}


# ─── Master Answer Retrieval Function ───────────────────────────

async def retrieve_answers(page, quiz_input: str | None = None, timeout: float = 6.0) -> tuple[dict[str, list[str]] | None, str]:
    """Coordinate direct API lookup, captured responses, and optional fallbacks."""
    attempted: set[tuple[str, str]] = set()

    async def try_identifier(identifier):
        key = _classify_identifier(identifier)
        if not key[0] or key in attempted:
            return None, ""
        attempted.add(key)
        db, source = await asyncio.to_thread(fetch_answers_by_any_identifier, identifier)
        if db:
            _set_answers(db, source)
        return db, source

    if _answers_ready_event.is_set() and _cached_answers_db:
        return _cached_answers_db, _cached_source
    for identifier in (quiz_input, page.url):
        db, source = await try_identifier(identifier)
        if db:
            return db, source

    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if _answers_ready_event.is_set() and _cached_answers_db:
            return _cached_answers_db, _cached_source
        info = await extract_identifiers_from_page(page)
        # A captured PIN and room hash refer to the same game: avoid retrying
        # the failed PIN through its hash on every DOM polling iteration.
        pin = info.get("pin") or _discovered_pin
        candidates = [pin, info.get("quizId") or _discovered_quiz_id]
        if not pin:
            candidates.append(info.get("hash") or _discovered_hash)
        for identifier in candidates:
            db, source = await try_identifier(identifier)
            if db:
                return db, source
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(_answers_ready_event.wait(), timeout=min(0.8, remaining))
        except asyncio.TimeoutError:
            pass
    return _cached_answers_db, _cached_source


# ─── Backwards Compatibility ────────────────────────────────────

async def find_quiz_id(page, quiz_input: str | None = None, timeout: float = 6.0) -> str | None:
    """Legacy helper: returns 24-char quiz ID or None."""
    global _discovered_quiz_id
    if _discovered_quiz_id and is_valid_quiz_id(_discovered_quiz_id):
        return _discovered_quiz_id
    return None
