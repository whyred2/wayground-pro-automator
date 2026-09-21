"""
Wayground Answer Retrieval Engine:
Fetches answer keys via:
1. Quizit Online Bot API (Game PIN / Code / Room Hash) — instant, 100% accurate for live games
2. Wayground Direct API (_quizserver) — for public / solo quizzes with 24-hex Quiz IDs
3. Network interception & DOM inspection — auto-detects PINs, room hashes, and quiz IDs
"""

import asyncio
import urllib.request
import json
import re
import html
import time

from ui import log_info, log_step, log_error

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

HEX_24_REGEX = re.compile(r"^[a-fA-F0-9]{24}$")
PIN_REGEX = re.compile(r"^\d{4,9}$")


def set_allow_quizit_bot(allowed: bool):
    """Toggle whether Quizit Bot API is permitted to connect to live game PINs."""
    global _allow_quizit_bot
    _allow_quizit_bot = allowed


def is_quizit_bot_allowed() -> bool:
    """Return whether Quizit Bot is currently allowed."""
    return _allow_quizit_bot


def get_discovered_pin() -> str | None:
    """Return the Game PIN captured by the network listener, if any."""
    global _discovered_pin
    return _discovered_pin


def is_valid_quiz_id(val: any) -> bool:
    """Check if a value is a valid 24-character hexadecimal MongoDB ObjectId."""
    return isinstance(val, str) and len(val.strip()) == 24 and bool(HEX_24_REGEX.match(val.strip()))


def is_valid_game_pin(val: any) -> bool:
    """Check if a value is a valid 4-9 digit game PIN."""
    return isinstance(val, str) and bool(PIN_REGEX.match(val.strip()))


def _set_answers(answers: dict[str, list[str]], source: str):
    """Event-safe setter for globally retrieved answers."""
    global _cached_answers_db, _cached_source
    if not _answers_ready_event.is_set() and answers:
        _cached_answers_db = answers
        _cached_source = source
        _answers_ready_event.set()


# ─── API 1: Quizit Online Bot API (Game PIN) ────────────────────

def fetch_quizit_answers(pin: str) -> dict[str, list[str]]:
    """
    Fetch answers from Quizit Online Bot API using a game PIN.
    Strictly deduplicated: only one HTTP request is ever made per PIN.
    Returns { question_text: [correct_answer1, ...], qid: [...], img_url: [...] }
    """
    global _in_progress_pins, _completed_pins

    clean_pin = re.sub(r"\D", "", str(pin).strip())
    if not clean_pin:
        raise ValueError("Invalid game PIN")

    if clean_pin in _completed_pins:
        return _completed_pins[clean_pin]

    if clean_pin in _in_progress_pins:
        # Another coroutine is already fetching this PIN, wait for it
        for _ in range(40):
            time.sleep(0.3)
            if clean_pin in _completed_pins:
                return _completed_pins[clean_pin]

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

        with urllib.request.urlopen(req, timeout=12) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}")
            data = json.loads(response.read().decode("utf-8"))

        questions = data.get("questions", []) or data.get("answers", [])
        if not questions:
            raise Exception("Quizit returned no questions")

        answers_db: dict[str, list[str]] = {}
        for item in questions:
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
                # 1. Map by question text (if present)
                if q_text:
                    if q_text not in answers_db:
                        answers_db[q_text] = []
                    for t in correct_texts:
                        if t not in answers_db[q_text]:
                            answers_db[q_text].append(t)
                elif q_image:
                    img_file = q_image.split("/")[-1].split("?")[0].strip()
                    answers_db[f"[Image: {img_file}]"] = list(correct_texts)
                elif q_id:
                    answers_db[f"[Question ID: {q_id}]"] = list(correct_texts)

                # 2. Map directly by question ID (100% reliable for image questions!)
                if q_id:
                    answers_db[q_id] = list(correct_texts)
                    answers_db[f"id:{q_id}"] = list(correct_texts)

                # 3. Map by question image URL / filename
                if q_image:
                    img_file = q_image.split("/")[-1].split("?")[0].strip()
                    if img_file:
                        answers_db[f"img:{img_file}"] = list(correct_texts)

        if not answers_db:
            raise Exception("Failed to parse question-answer pairs from Quizit")

        _completed_pins[clean_pin] = answers_db
        return answers_db
    except Exception as e:
        raise Exception(f"Quizit API error: {e}")
    finally:
        _in_progress_pins.discard(clean_pin)


# ─── API 2: Wayground Direct API (_quizserver) ──────────────────

def fetch_api_answers(quiz_id: str) -> dict[str, list[str]]:
    """
    Fetch raw quiz data from Wayground API and compile answers_db.
    Requires a valid 24-char MongoDB ObjectId quiz_id.
    """
    clean_id = quiz_id.strip()
    url = f"https://wayground.com/_quizserver/main/v2/quiz/{clean_id}?convertQuestions=false&includeFsFeatures=true&sanitize=read&questionMetadata=true&includeUserHydratedVariants=true"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}")
            data = json.loads(response.read().decode())
    except Exception as e:
        raise Exception(f"API fetch failed: {e}")

    quiz_data = data.get("data", {}).get("quiz", {})
    info_data = quiz_data.get("info", {})
    if not info_data:
        raise Exception("Invalid API response format (missing 'info')")

    answers_db: dict[str, list[str]] = {}
    questions = info_data.get("questions", [])
    for q in questions:
        q_id = str(q.get("_id") or q.get("id") or "").strip()
        q_struct = q.get("structure", {})
        q_query = q_struct.get("query", {})
        q_text_raw = q_query.get("text", "")
        q_text = html.unescape(re.sub(r"<[^<]+?>", "", q_text_raw)).strip() if q_text_raw else ""

        # Extract image if present
        q_media = q_query.get("media", [])
        q_image = ""
        if isinstance(q_media, list) and len(q_media) > 0 and isinstance(q_media[0], dict):
            q_image = q_media[0].get("url", "")

        options_raw = q_struct.get("options", [])
        ans_raw = q_struct.get("answer")
        ans_indices = []
        if isinstance(ans_raw, int):
            ans_indices = [ans_raw]
        elif isinstance(ans_raw, list):
            ans_indices = ans_raw

        correct_texts = []
        for idx in ans_indices:
            try:
                idx = int(idx)
            except ValueError:
                continue

            if 0 <= idx < len(options_raw):
                opt = options_raw[idx]
                opt_text_raw = opt.get("text", "")
                if opt_text_raw:
                    opt_text = html.unescape(re.sub(r"<[^<]+?>", "", opt_text_raw)).strip()
                    if opt_text and opt_text not in correct_texts:
                        correct_texts.append(opt_text)

                # Option image
                opt_media = opt.get("media", [])
                if isinstance(opt_media, list) and len(opt_media) > 0 and isinstance(opt_media[0], dict):
                    opt_img = opt_media[0].get("url", "")
                    if opt_img:
                        img_file = opt_img.split("/")[-1].split("?")[0].strip()
                        if img_file and img_file not in correct_texts:
                            correct_texts.append(img_file)

                # Store index directly as fallback only if no text or image exists
                if not correct_texts:
                    correct_texts.append(f"option-{idx}")
                    correct_texts.append(f"index:{idx}")

        if correct_texts:
            if q_text:
                if q_text not in answers_db:
                    answers_db[q_text] = []
                for t in correct_texts:
                    if t not in answers_db[q_text]:
                        answers_db[q_text].append(t)
            elif q_image:
                img_file = q_image.split("/")[-1].split("?")[0].strip()
                answers_db[f"[Image: {img_file}]"] = list(correct_texts)
            elif q_id:
                answers_db[f"[Question ID: {q_id}]"] = list(correct_texts)

            if q_id:
                answers_db[q_id] = list(correct_texts)
                answers_db[f"id:{q_id}"] = list(correct_texts)

            if q_image:
                img_file = q_image.split("/")[-1].split("?")[0].strip()
                if img_file:
                    answers_db[f"img:{img_file}"] = list(correct_texts)

    return answers_db


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

def fetch_answers_by_any_identifier(identifier: str) -> tuple[dict[str, list[str]] | None, str]:
    """
    Given ANY user input (URL, Game PIN, Room Hash, or Quiz ID), attempt
    all possible resolution paths and return (answers_db, source_description).
    """
    clean = str(identifier).strip()
    if not clean:
        return None, ""

    # Case 1: URL input (e.g. https://wayground.com/join?gc=665058)
    if "wayground.com" in clean or "quizizz.com" in clean or clean.startswith("http"):
        # Check game code (?gc=XXXXXX)
        m_gc = re.search(r"[?&]gc=(\d+)", clean)
        if m_gc and _allow_quizit_bot:
            pin = m_gc.group(1)
            try:
                db = fetch_quizit_answers(pin)
                if db:
                    return db, f"Quizit API (Game PIN: {pin} from URL)"
            except Exception:
                pass

        # Check path ObjectId (/(quiz|admin/quiz|pre-game)/<24-hex>)
        m_path = re.search(r"/(?:quiz|admin/quiz|pre-game)/([a-fA-F0-9]{24})", clean)
        if m_path:
            qid = m_path.group(1)
            try:
                db = fetch_api_answers(qid)
                if db:
                    return db, f"Wayground Direct API (Quiz ID: {qid})"
            except Exception:
                pass

        # Check join path room hash (/join/<hash>)
        m_join_hash = re.search(r"/join/([a-zA-Z0-9_-]{10,})", clean)
        if m_join_hash:
            clean = m_join_hash.group(1)

    # Case 2: Pure digits PIN (e.g. 665058)
    digits = re.sub(r"\D", "", clean)
    if 4 <= len(digits) <= 9:
        if _allow_quizit_bot:
            try:
                db = fetch_quizit_answers(digits)
                if db:
                    return db, f"Quizit API (Game PIN: {digits})"
            except Exception as e:
                log_step(f"Quizit PIN fetch failed: {e}")
        else:
            log_step("⚠ Live game PIN detected, but Quizit Bot is disabled. (Live game answers require the bot).")

    # Case 3: 24-character hexadecimal (Room Hash or MongoDB Quiz ID)
    if is_valid_quiz_id(clean):
        # 3a. Try treating as Room Hash (common in live games)
        pin = resolve_hash_to_pin(clean)
        if pin and _allow_quizit_bot:
            try:
                db = fetch_quizit_answers(pin)
                if db:
                    return db, f"Quizit API (Game PIN: {pin} via Room Hash)"
            except Exception:
                pass

        # 3b. Try treating directly as Quiz ID on _quizserver
        try:
            db = fetch_api_answers(clean)
            if db:
                return db, f"Wayground Direct API (Quiz ID: {clean})"
        except Exception:
            pass

    # Case 4: Other room hash format (length >= 10)
    if len(clean) >= 10 and not clean.isdigit() and _allow_quizit_bot:
        pin = resolve_hash_to_pin(clean)
        if pin:
            try:
                db = fetch_quizit_answers(pin)
                if db:
                    return db, f"Quizit API (Game PIN: {pin} via Room Hash)"
            except Exception:
                pass

    return None, ""


# ─── Network Interception ───────────────────────────────────────

async def intercept_response(response):
    """
    Universal network listener to catch Wayground / Quizizz traffic:
    Extracts Game PIN, Room Hash, or Quiz ID and pre-fetches answers.
    Strictly debounced: will never trigger duplicate Quizit bot requests.
    """
    global _discovered_pin, _discovered_hash, _discovered_quiz_id

    if _answers_ready_event.is_set():
        return

    url = (response.url or "").lower()
    if not ("wayground.com" in url or "quizizz.com" in url):
        return
    if any(url.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".css", ".woff", ".woff2", ".mp3"]):
        return

    # 1. Check request body for game code / roomCode
    try:
        req = response.request
        if req and req.method in ["POST", "PUT"]:
            post_data = req.post_data
            if post_data and len(post_data) < 20000:
                try:
                    p_json = json.loads(post_data)
                    p_code = p_json.get("roomCode") or p_json.get("gameCode") or p_json.get("code")
                    if p_code and str(p_code).isdigit():
                        _discovered_pin = str(p_code)
                        asyncio.create_task(_async_try_pin(_discovered_pin, source=f"Request payload ({url})"))
                except Exception:
                    pass
    except Exception:
        pass

    # 2. Check response body (only if pin wasn't already triggered)
    if response.status == 200 and not _discovered_pin:
        try:
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type or "text/json" in content_type:
                body = await response.json()
                if isinstance(body, dict):
                    room = body.get("room") or body.get("data", {}).get("room") or {}
                    if isinstance(room, dict):
                        # Extract PIN
                        r_code = room.get("code") or room.get("roomCode")
                        if r_code and str(r_code).isdigit():
                            _discovered_pin = str(r_code)
                            asyncio.create_task(_async_try_pin(_discovered_pin, source="Room response code"))

                        # Extract Hash
                        r_hash = room.get("hash")
                        if r_hash and len(str(r_hash)) >= 10 and not _discovered_pin:
                            _discovered_hash = str(r_hash)
                            asyncio.create_task(_async_try_hash(_discovered_hash, source="Room response hash"))

                    # Check items array (students/games/{hash})
                    items = body.get("data", {}).get("items", []) or body.get("items", [])
                    if isinstance(items, list) and len(items) > 0 and isinstance(items[0], dict):
                        g_code = items[0].get("gameCode")
                        if g_code and str(g_code).isdigit():
                            _discovered_pin = str(g_code)
                            asyncio.create_task(_async_try_pin(_discovered_pin, source="_gameapi items gameCode"))
        except Exception:
            pass


async def _async_try_pin(pin: str, source: str = "Network"):
    """Background task to fetch answers from detected PIN (single-flight)."""
    global _in_progress_pins, _completed_pins, _allow_quizit_bot

    if not _allow_quizit_bot:
        return
    if _answers_ready_event.is_set():
        return

    clean_pin = re.sub(r"\D", "", str(pin).strip())
    if clean_pin in _in_progress_pins or clean_pin in _completed_pins:
        return

    try:
        loop = asyncio.get_event_loop()
        db = await loop.run_in_executor(None, fetch_quizit_answers, clean_pin)
        if db:
            _set_answers(db, source=f"Quizit API (PIN: {clean_pin} from {source})")
            log_info(f"✅ Auto-captured answers via PIN {clean_pin} [{source}]")
    except Exception:
        pass


async def _async_try_hash(room_hash: str, source: str = "Network"):
    """Background task to resolve hash and fetch answers (single-flight)."""
    global _allow_quizit_bot

    if not _allow_quizit_bot:
        return
    if _answers_ready_event.is_set():
        return

    try:
        loop = asyncio.get_event_loop()
        pin = await loop.run_in_executor(None, resolve_hash_to_pin, room_hash)
        if pin:
            await _async_try_pin(pin, source=f"Hash {room_hash}")
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
    """
    Master coordinator to retrieve answers using all available channels:
    1. If answers were already captured by network listener -> return immediately.
    2. Try user-provided quiz_input (URL, PIN, Hash, or Quiz ID).
    3. Check active browser URL (e.g. ?gc=665058).
    4. Inspect page DOM & localStorage.
    5. Wait for network listener (up to timeout seconds).
    """
    global _cached_answers_db, _cached_source

    # 1. Already ready?
    if _answers_ready_event.is_set() and _cached_answers_db:
        return _cached_answers_db, _cached_source

    # 2. Check user input
    if quiz_input:
        loop = asyncio.get_event_loop()
        db, src = await loop.run_in_executor(None, fetch_answers_by_any_identifier, quiz_input)
        if db:
            _set_answers(db, src)
            return db, src

    # 3. Check active page URL
    try:
        current_url = page.url or ""
        if current_url:
            loop = asyncio.get_event_loop()
            db, src = await loop.run_in_executor(None, fetch_answers_by_any_identifier, current_url)
            if db:
                _set_answers(db, src)
                return db, src
    except Exception:
        pass

    # 4. In-page DOM / localStorage inspection
    page_info = await extract_identifiers_from_page(page)
    loop = asyncio.get_event_loop()

    if page_info.get("pin"):
        db, src = await loop.run_in_executor(None, fetch_answers_by_any_identifier, page_info["pin"])
        if db:
            _set_answers(db, f"Page DOM ({src})")
            return db, _cached_source

    if page_info.get("hash"):
        db, src = await loop.run_in_executor(None, fetch_answers_by_any_identifier, page_info["hash"])
        if db:
            _set_answers(db, f"Page Storage ({src})")
            return db, _cached_source

    if page_info.get("quizId"):
        db, src = await loop.run_in_executor(None, fetch_answers_by_any_identifier, page_info["quizId"])
        if db:
            _set_answers(db, f"Page Storage ({src})")
            return db, _cached_source

    # 5. Wait for network listener while periodically re-checking page
    elapsed = 0.0
    step = 0.8
    while elapsed < timeout:
        if _answers_ready_event.is_set() and _cached_answers_db:
            return _cached_answers_db, _cached_source

        await asyncio.sleep(step)
        elapsed += step

        # Periodic re-check of DOM / URL (SPA might have loaded room state)
        page_info = await extract_identifiers_from_page(page)
        if page_info.get("pin"):
            db, src = await loop.run_in_executor(None, fetch_answers_by_any_identifier, page_info["pin"])
            if db:
                _set_answers(db, f"Page DOM Delayed ({src})")
                return db, _cached_source

    return _cached_answers_db, _cached_source


# ─── Backwards Compatibility ────────────────────────────────────

async def find_quiz_id(page, quiz_input: str | None = None, timeout: float = 6.0) -> str | None:
    """Legacy helper: returns 24-char quiz ID or None."""
    global _discovered_quiz_id
    if _discovered_quiz_id and is_valid_quiz_id(_discovered_quiz_id):
        return _discovered_quiz_id
    return None
