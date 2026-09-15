import re
import html


def _norm(s: str) -> str:
    """Normalize text for robust comparison: quotes, dashes, whitespace, punctuation."""
    if not s:
        return ""
    # Unescape HTML entities
    s = html.unescape(s).strip().lower()
    # Normalize unicode quotes
    s = re.sub(r'[\u201c\u201d\u201e\u201f"«»]', '"', s)
    s = re.sub(r"[\u2018\u2019'`]", "'", s)
    # Normalize unicode dashes / hyphens
    s = re.sub(r'[\u2013\u2014\u2212-]', '-', s)
    # Collapse multiple whitespaces
    s = re.sub(r'\s+', ' ', s)
    # Strip trailing punctuation
    s = s.rstrip('.;,!?')
    return s.strip()


def get_display_questions(answers_db: dict[str, list[str]]) -> list[tuple[str, list[str]]]:
    """
    Extract clean, unique user-facing questions and their answers.
    Filters out internal lookup aliases (hex IDs, id: prefixes, img: prefixes).
    """
    display_list = []
    for k, v in answers_db.items():
        if k.startswith("__"):
            continue
        # Skip raw hexadecimal IDs (MongoDB ObjectIds, SHA hashes)
        if len(k) >= 16 and re.match(r"^[a-fA-F0-9]+$", k):
            continue
        # Skip id: and img: prefixes
        if k.startswith("id:") or k.startswith("img:"):
            continue
        display_list.append((k, v))

    # Fallback if test has purely image-based questions without human labels
    if not display_list:
        seen_ids = set()
        for k, v in answers_db.items():
            if k.startswith("id:"):
                qid = k[3:]
                if qid not in seen_ids:
                    seen_ids.add(qid)
                    display_list.append((f"[Image Question: {qid}]", v))

    return display_list


def find_answers(
    question: str,
    answers_db: dict[str, list[str]],
    qid: str | None = None,
    image_url: str | None = None
) -> list[str] | None:
    """
    Find the answer(s) for a given question using multiple matching strategies:
    1. Question ID match (data-quesid) — 100% precision even without text/image
    2. Image filename match (if question contains an image)
    3. Exact text match (case-insensitive, stripped)
    4. Substring / contains text match
    5. Fuzzy similarity (Levenshtein-based, threshold 80%)

    Returns a list of correct answer strings, or None if not found.
    """
    if not answers_db:
        return None

    # Strategy 1: Direct Question ID match
    if qid:
        clean_qid = str(qid).strip()
        if clean_qid in answers_db:
            return answers_db[clean_qid]
        if f"id:{clean_qid}" in answers_db:
            return answers_db[f"id:{clean_qid}"]

    # Strategy 2: Image filename match
    if image_url:
        img_name = image_url.split("/")[-1].split("?")[0].strip().lower()
        if img_name:
            if f"img:{img_name}" in answers_db:
                return answers_db[f"img:{img_name}"]
            for k, val in answers_db.items():
                if k.startswith("img:") and img_name in k.lower():
                    return val

    # Strategy 3-5: Text-based matching (if question text exists)
    if question and question.strip():
        q_norm = _norm(question)

        # Strategy 3: Exact match
        for key, val in answers_db.items():
            if key.startswith("id:") or key.startswith("img:"):
                continue
            if _norm(key) == q_norm:
                return val

        # Strategy 4: Substring match (ranked by highest overlap ratio)
        best_sub = None
        best_ratio = 0.0
        for key, val in answers_db.items():
            if key.startswith("id:") or key.startswith("img:"):
                continue
            k = _norm(key)
            if len(k) > 6 and len(q_norm) > 6:
                if k in q_norm:
                    ratio = len(k) / len(q_norm)
                    if ratio > best_ratio and ratio >= 0.5:
                        best_ratio = ratio
                        best_sub = val
                elif q_norm in k:
                    ratio = len(q_norm) / len(k)
                    if ratio > best_ratio and ratio >= 0.5:
                        best_ratio = ratio
                        best_sub = val
        if best_sub:
            return best_sub

        # Strategy 5: Fuzzy match (pick highest similarity above threshold)
        best_fuzzy = None
        best_sim = 0.80
        for key, val in answers_db.items():
            if key.startswith("id:") or key.startswith("img:"):
                continue
            k = _norm(key)
            sim = _similarity(k, q_norm)
            if sim > best_sim:
                best_sim = sim
                best_fuzzy = val
        if best_fuzzy:
            return best_fuzzy

        return None


def score_option(btn_info: dict, ans: str) -> float:
    """
    Score how closely a button matches a specific expected answer (0.0 to 1.0).
    1.0 = exact match on text, alt, image filename, or option index.
    """
    ans_n = _norm(ans)
    if not ans_n:
        return 0.0

    # 1. Text match
    btn_text_n = _norm(btn_info.get("text") or "")
    if btn_text_n:
        if btn_text_n == ans_n:
            return 1.0

    # 2. Image alt match
    alt_n = _norm(btn_info.get("alt") or "")
    if alt_n and alt_n == ans_n:
        return 1.0

    # 3. Image src filename match
    img_src = (btn_info.get("img_src") or "").strip().lower()
    if img_src:
        img_file = img_src.split("/")[-1].split("?")[0].strip().lower()
        if img_file and (img_file == ans_n or f"img:{img_file}" == ans_n):
            return 1.0

    # 4. Direct index match
    cy_idx = btn_info.get("cy_index")
    if cy_idx is not None and ans_n in (f"index:{cy_idx}", f"option-{cy_idx}", str(cy_idx)):
        return 1.0

    # 5. Fuzzy similarity only if button has text
    if btn_text_n:
        return _similarity(btn_text_n, ans_n)

    return 0.0


def rank_and_match_buttons(
    buttons_info: list[dict],
    correct_answers: list[str],
    is_msq: bool = False
) -> tuple[list[int], list[int]]:
    """
    Rank all available option buttons against the expected answers.
    CRITICAL RULE:
    If ANY button on the page is an EXACT match (score >= 0.999),
    all fuzzy/distractor buttons (< 0.999) are strictly ignored!
    This completely eliminates teacher distractors (e.g. 'less' vs 'more', 'July' vs 'January').

    Returns:
      (correct_indices, wrong_indices)
    """
    if not buttons_info or not correct_answers:
        return [], list(range(len(buttons_info)))

    # For each button, find its highest score against any expected answer
    scored_buttons = []
    for idx, b_info in enumerate(buttons_info):
        best_score = 0.0
        best_ans = ""
        for ans in correct_answers:
            s = score_option(b_info, ans)
            if s > best_score:
                best_score = s
                best_ans = ans
        scored_buttons.append((idx, b_info, best_score, best_ans))

    # Check if ANY button is an exact match (or option index/image match)
    has_exact_match = any(s >= 0.999 for _, _, s, _ in scored_buttons)

    correct_indices: list[int] = []

    if not is_msq:
        # Single-choice question: sort descending by match score
        scored_buttons.sort(key=lambda x: x[2], reverse=True)
        top_idx, _, top_score, _ = scored_buttons[0]

        if has_exact_match:
            # Only accept exact matches
            if top_score >= 0.999:
                correct_indices.append(top_idx)
        else:
            # No button is exact; accept highest-scoring button if >= 0.85
            if top_score >= 0.85:
                correct_indices.append(top_idx)
    else:
        # Multi-select (MSQ): for each expected answer, find the single best button
        for ans in correct_answers:
            best_idx = None
            best_s = 0.0
            for idx, b_info in enumerate(buttons_info):
                s = score_option(b_info, ans)
                if s > best_s:
                    best_s = s
                    best_idx = idx

            if best_idx is not None:
                if has_exact_match:
                    if best_s >= 0.999 and best_idx not in correct_indices:
                        correct_indices.append(best_idx)
                else:
                    if best_s >= 0.85 and best_idx not in correct_indices:
                        correct_indices.append(best_idx)

    wrong_indices = [i for i in range(len(buttons_info)) if i not in correct_indices]
    return correct_indices, wrong_indices


def match_button_option(btn_info: dict, correct_answers: list[str]) -> bool:
    """Legacy helper: checks if a button scores high enough against correct answers."""
    for ans in correct_answers:
        if score_option(btn_info, ans) >= 0.95:
            return True
    return False


def _similarity(s1: str, s2: str) -> float:
    """Levenshtein-based similarity ratio (0.0 to 1.0)."""
    longer, shorter = (s1, s2) if len(s1) >= len(s2) else (s2, s1)
    if len(longer) == 0:
        return 1.0
    return (len(longer) - _edit_distance(longer, shorter)) / len(longer)


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,      # deletion
                curr[j] + 1,           # insertion
                prev[j] + (0 if ca == cb else 1)  # substitution
            ))
        prev = curr
    return prev[-1]
