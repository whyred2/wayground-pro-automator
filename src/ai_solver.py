"""
AI Solver Engine:
Analyzes quiz/test questions and multiple-choice options in real time using the OpenAI SDK
connected to Groq (qwen/qwen3.8-27b by default) or any OpenAI-compatible API.
Supports text, math, multi-language, Fill-in-the-Blank, and vision/image questions.
"""

import json
import re
import time
import random
import urllib.request
from openai import OpenAI

from config import AI_API_BASE, AI_API_KEY, AI_MODEL, AI_GATEWAY_URL
from ui import log_info, log_step, log_error


def get_ai_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    """Instantiate OpenAI client configured with the specified or default base_url and api_key."""
    key = api_key or AI_API_KEY
    url = base_url or AI_API_BASE
    return OpenAI(
        api_key=key,
        base_url=url,
    )


def test_ai_connection(
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    gateway_url: str | None = None
) -> tuple[bool, str]:
    """Verify connectivity and authentication with the AI API or Cloudflare Gateway."""
    key = api_key or AI_API_KEY
    mdl = model or AI_MODEL
    url = base_url or AI_API_BASE
    gw = gateway_url or AI_GATEWAY_URL

    if not key and gw:
        try:
            req = urllib.request.Request(
                f"{gw.rstrip('/')}/health",
                headers={"User-Agent": "WaygroundProAutomator/3.0"}
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return True, f"Cloudflare Gateway online ({data.get('service', 'ok')})"
        except Exception as exc:
            return False, f"Cloudflare Gateway unreachable: {exc}"

    if not key:
        return False, "API key is empty and no Gateway URL configured"

    try:
        client = get_ai_client(api_key=key, base_url=url)
        resp = client.chat.completions.create(
            model=mdl,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        if resp and resp.choices:
            return True, "Connection successful"
        return False, "No choices returned"
    except Exception as exc:
        return False, str(exc)


def _solve_via_gateway_mcq(
    gateway_url: str,
    question_text: str,
    options_info: list[dict],
    is_msq: bool = False,
    image_base64: str | None = None,
) -> tuple[list[int], str]:
    """Call Cloudflare Worker AI Gateway endpoint /api/solve for multiple-choice questions."""
    endpoint = f"{gateway_url.rstrip('/')}/api/solve"
    payload = {
        "question": question_text,
        "options": options_info,
        "is_msq": is_msq,
        "image_base64": image_base64,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WaygroundProAutomator/3.0"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        reasoning = res_data.get("reasoning", "")
        indices = _parse_candidate_indices(
            res_data.get("selected_indices", [1]),
            len(options_info),
            options_info
        )
        if not indices and options_info:
            indices = [0]
        return indices, reasoning


def _solve_via_gateway_fib(
    gateway_url: str,
    question_text: str,
    num_blanks: int = 1,
    image_base64: str | None = None,
) -> tuple[list[str], list[str], str]:
    """Call Cloudflare Worker AI Gateway endpoint /api/solve-fib for fill-in-the-blank questions."""
    endpoint = f"{gateway_url.rstrip('/')}/api/solve-fib"
    payload = {
        "question": question_text,
        "num_blanks": num_blanks,
        "image_base64": image_base64,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WaygroundProAutomator/3.0"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        ans = res_data.get("answers") or [res_data.get("answer", "answer")]
        wrongs = res_data.get("plausible_wrongs") or [res_data.get("plausible_wrong", "answers")]
        reasoning = res_data.get("reasoning", "")
        return ans, wrongs, reasoning


def _format_options_text(options_info: list[dict]) -> str:
    """Format extracted options into a clean numbered list for AI analysis."""
    lines = []
    for idx, opt in enumerate(options_info, 1):
        txt = (opt.get("text") or "").strip()
        alt = (opt.get("alt") or "").strip()
        img_src = (opt.get("img_src") or "").strip()

        if txt:
            label = txt
        elif alt:
            label = f"[Image: {alt}]"
        elif img_src:
            fname = img_src.split("/")[-1].split("?")[0]
            label = f"[Image: {fname}]"
        else:
            label = f"Option {idx}"
        lines.append(f"{idx}. {label}")
    return "\n".join(lines)


def _parse_candidate_indices(val, total_options: int, options_info: list[dict] | None = None) -> list[int]:
    """Robustly parse any AI value (int, string number, letter, text) into 0-based indices."""
    indices = []
    items = val if isinstance(val, list) else [val]

    letter_map = {
        'a': 0, 'b': 1, 'c': 2, 'd': 3, 'e': 4, 'f': 5, 'g': 6, 'h': 7,
        'а': 0, 'б': 1, 'в': 2, 'г': 3, 'д': 4, 'е': 5  # Russian / Cyrillic letters
    }

    for item in items:
        if isinstance(item, int):
            if 1 <= item <= total_options:
                indices.append(item - 1)
            elif item == 0 and total_options > 0:
                indices.append(0)
        elif isinstance(item, str):
            clean = item.strip()
            # 1. Pure digits
            if clean.isdigit():
                num = int(clean)
                if 1 <= num <= total_options:
                    indices.append(num - 1)
                elif num == 0 and total_options > 0:
                    indices.append(0)
            # 2. Letter option (A, B, C, D...)
            elif clean.lower() in letter_map:
                l_idx = letter_map[clean.lower()]
                if l_idx < total_options:
                    indices.append(l_idx)
            # 3. Match against option text
            elif options_info:
                clean_low = clean.lower()
                for o_idx, opt in enumerate(options_info):
                    opt_text = (opt.get("text") or opt.get("alt") or "").strip().lower()
                    if clean_low and (clean_low == opt_text or clean_low in opt_text or opt_text in clean_low):
                        indices.append(o_idx)
                        break

    return indices


def _parse_ai_response(raw_text: str, total_options: int, is_msq: bool, options_info: list[dict] | None = None) -> tuple[list[int], str]:
    """
    Parse AI JSON output into 0-based option indices and reasoning text.
    Handles varied JSON keys, letter choices (A/B/C/D), option text, and markdown code fences.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    reasoning = ""
    selected_indices: list[int] = []

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            reasoning = data.get("reasoning") or data.get("explanation") or data.get("rationale") or ""
            # Check potential keys for selected indices
            for candidate_key in [
                "selected_indices", "correct_indices", "selected_options",
                "correct_options", "indices", "answers", "correct_index",
                "selected_index", "answer", "option", "choice", "selected"
            ]:
                val = data.get(candidate_key)
                if val is not None:
                    parsed = _parse_candidate_indices(val, total_options, options_info)
                    if parsed:
                        selected_indices.extend(parsed)
                        break
        elif isinstance(data, list):
            selected_indices.extend(_parse_candidate_indices(data, total_options, options_info))
    except Exception:
        pass

    # Regex fallback if JSON was malformed or missing expected keys
    if not selected_indices:
        # Check for letter matches e.g. "Option A" or "Answer: B" or "Choice C"
        letter_match = re.findall(r"(?:option|choice|answer|вариант|відповідь)?\s*[:#]?\s*\b([A-Ha-hА-Еа-е])\b", raw_text)
        if letter_match:
            selected_indices.extend(_parse_candidate_indices(letter_match, total_options, options_info))

        if not selected_indices:
            matches = re.findall(r"\b(\d+)\b", raw_text)
            for m in matches:
                val = int(m)
                if 1 <= val <= total_options:
                    selected_indices.append(val - 1)
                    if not is_msq:
                        break

    # Filter bounds
    valid = [idx for idx in selected_indices if 0 <= idx < total_options]

    # Deduplicate while preserving order
    seen = set()
    final_indices = []
    for idx in valid:
        if idx not in seen:
            seen.add(idx)
            final_indices.append(idx)

    # Fallback to option 0 if nothing matched
    if not final_indices and total_options > 0:
        final_indices = [0]
        if not reasoning:
            reasoning = "Fallback selection"

    return final_indices, reasoning.strip()


def solve_question_with_ai(
    question_text: str,
    options_info: list[dict],
    is_msq: bool = False,
    image_base64: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    max_retries: int = 2,
) -> tuple[list[int], str]:
    """
    Submit a question and its options to the AI model (qwen/qwen3.8-27b on Groq by default).
    Returns (selected_0_based_indices, reasoning_string).
    """
    key = api_key or AI_API_KEY
    mdl = model or AI_MODEL
    url = base_url or AI_API_BASE

    total_options = len(options_info)
    if total_options == 0:
        return [], "No options available"

    if not key and AI_GATEWAY_URL:
        try:
            return _solve_via_gateway_mcq(AI_GATEWAY_URL, question_text, options_info, is_msq, image_base64)
        except Exception as exc:
            log_error(f"Cloudflare Gateway error: {exc}")
            return [0], f"Gateway error: {exc}"
    elif not key:
        raise ValueError("AI API key is not configured and AI_GATEWAY_URL is not set")

    formatted_options = _format_options_text(options_info)

    q_stem = question_text.strip() if question_text else "[Question presented in image/media]"
    q_type_hint = (
        "This is a MULTIPLE-CHOICE question where ONE OR MORE options can be correct. "
        "Select ALL options that are correct."
        if is_msq
        else "This is a SINGLE-CHOICE question where exactly ONE option is correct."
    )

    prompt = (
        f"Question:\n{q_stem}\n\n"
        f"Options:\n{formatted_options}\n\n"
        f"Instructions:\n{q_type_hint}\n"
        "Carefully analyze each option step-by-step to eliminate distractors and verify accuracy. "
        "Output strictly valid JSON with 'reasoning' (1-2 concise sentences analyzing the options) "
        "and 'selected_indices' (list of 1-based option numbers):\n"
        '{"reasoning": "Option X is factually correct because...", "selected_indices": [1]}\n'
        'Example: {"reasoning": "Option 2 correctly satisfies the rule...", "selected_indices": [2]}'
    )

    system_prompt = (
        "You are an expert, highly accurate test and quiz solver with deep knowledge across "
        "academic subjects, English grammar, science, and history. "
        "Carefully analyze the question and select the exact correct multiple-choice option(s). "
        "Always output valid JSON."
    )

    # Prepare user content (text-only or multimodal with base64 image)
    if image_base64:
        data_uri = image_base64 if image_base64.startswith("data:") else f"data:image/png;base64,{image_base64}"
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]
    else:
        user_content = prompt

    client = get_ai_client(api_key=key, base_url=url)
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=mdl,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                max_tokens=768,
                temperature=0.0,
            )
            choices = resp.choices or []
            if not choices:
                return [0], "No choices returned by AI API"
            raw_content = choices[0].message.content or ""
            return _parse_ai_response(raw_content, total_options, is_msq, options_info)

        except Exception as exc:
            last_exc = exc
            err_msg = str(exc)

            # If Groq returns 400 json_validate_failed with failed_generation, salvage partial generation
            if "failed_generation" in err_msg:
                m_gen = re.search(r"'failed_generation':\s*'([^']+)'", err_msg) or re.search(r'"failed_generation":\s*"([^"]+)"', err_msg)
                if m_gen:
                    try:
                        salvaged_text = m_gen.group(1).encode().decode('unicode-escape', errors='replace')
                        salvaged_idx, salvaged_r = _parse_ai_response(salvaged_text, total_options, is_msq, options_info)
                        if salvaged_idx and salvaged_idx != [0]:
                            return salvaged_idx, f"Salvaged: {salvaged_r}"
                    except Exception:
                        pass

            if "image" in err_msg.lower() and isinstance(user_content, list):
                user_content = prompt
                continue
            if "rate_limit" in err_msg.lower() or "429" in err_msg:
                time.sleep(1.5 * (attempt + 1))
                continue
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            break

    log_error(f"AI solver failed after {max_retries + 1} attempt(s): {last_exc}")
    return [0], f"Error: {last_exc}"


def generate_plausible_wrong(correct_word: str) -> str:
    """Generate a believable human student mistake for a word or phrase instead of typing 'incorrect'."""
    word = (correct_word or "").strip()
    if not word:
        return "no"

    # 1. Number handling
    if re.match(r'^-?\d+(\.\d+)?$', word):
        try:
            val = float(word)
            if val.is_integer():
                wrong_num = int(val) + random.choice([-1, 1, 2, -2])
                return str(wrong_num)
            else:
                wrong_num = round(val + random.choice([-0.5, 0.5, 1.0]), 2)
                return str(wrong_num)
        except Exception:
            return "0"

    low = word.lower()
    # 2. English grammatical mutations (verb tenses, singular/plural)
    if low.endswith("s") and len(low) > 3 and not low.endswith("ss"):
        return word[:-1]
    elif low.endswith("ed") and len(low) > 4:
        return word[:-2] + "ing"
    elif low.endswith("ing") and len(low) > 5:
        return word[:-3] + "s"
    elif low.endswith(("sh", "ch", "x", "z")):
        return word + "es"
    elif low.endswith("y") and len(low) > 2 and low[-2] not in "aeiou":
        return word[:-1] + "ies"
    elif len(word) >= 4 and word.isalpha():
        # Common slight typo: swap 2nd and 3rd letters
        if len(word) >= 5:
            chars = list(word)
            chars[1], chars[2] = chars[2], chars[1]
            return "".join(chars)
        else:
            return word + "s"
    else:
        if len(word) > 3:
            return word[:-1]
        return word + "s"


def _parse_fib_response(raw_text: str, num_blanks: int = 1) -> tuple[list[str], list[str], str]:
    """Parse AI output for fill-in-the-blank questions into list of answers, plausible wrongs, and reasoning."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    reasoning = ""
    answers: list[str] = []
    plausible_wrongs: list[str] = []

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            reasoning = data.get("reasoning") or data.get("explanation") or data.get("rationale") or ""
            for candidate in ["answers", "answer", "words", "word", "blanks", "blank", "text", "term"]:
                val = data.get(candidate)
                if val is not None:
                    if isinstance(val, list):
                        answers = [str(x).strip() for x in val if str(x).strip()]
                    elif isinstance(val, str) and val.strip():
                        answers = [val.strip()]
                    elif isinstance(val, (int, float)):
                        answers = [str(val)]
                    if answers:
                        break

            for candidate_w in ["plausible_wrongs", "plausible_wrong", "wrong_answers", "wrong_answer", "distractors", "distractor"]:
                val_w = data.get(candidate_w)
                if val_w is not None:
                    if isinstance(val_w, list):
                        plausible_wrongs = [str(x).strip() for x in val_w if str(x).strip()]
                    elif isinstance(val_w, str) and val_w.strip():
                        plausible_wrongs = [val_w.strip()]
                    if plausible_wrongs:
                        break

        elif isinstance(data, list):
            answers = [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass

    if not answers:
        m = re.search(r'"(?:answer|word|term)"\s*:\s*"([^"]+)"', raw_text, re.IGNORECASE)
        if m:
            answers = [m.group(1).strip()]
        else:
            first_line = cleaned.split("\n")[0].strip().strip('"\'')
            if first_line and len(first_line) < 80:
                answers = [first_line]
            else:
                answers = ["answer"]

    while len(answers) < num_blanks:
        answers.append(answers[0] if answers else "answer")

    while len(plausible_wrongs) < len(answers):
        target_ans = answers[len(plausible_wrongs)]
        plausible_wrongs.append(generate_plausible_wrong(target_ans))

    return answers[:num_blanks], plausible_wrongs[:num_blanks], reasoning.strip()


def solve_fib_with_ai(
    question_text: str,
    num_blanks: int = 1,
    image_base64: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    max_retries: int = 2,
) -> tuple[list[str], list[str], str]:
    """
    Submit a Fill-in-the-Blank (FIB) question to the AI model.
    Returns (list_of_answers_per_blank, list_of_plausible_wrong_per_blank, reasoning_string).
    """
    key = api_key or AI_API_KEY
    mdl = model or AI_MODEL
    url = base_url or AI_API_BASE

    if not key and AI_GATEWAY_URL:
        try:
            return _solve_via_gateway_fib(AI_GATEWAY_URL, question_text, num_blanks, image_base64)
        except Exception as exc:
            log_error(f"Cloudflare Gateway FIB error: {exc}")
            fallback_wrongs = [generate_plausible_wrong("answer")] * num_blanks
            return ["answer"] * num_blanks, fallback_wrongs, f"Gateway error: {exc}"
    elif not key:
        raise ValueError("AI API key is not configured and AI_GATEWAY_URL is not set")

    q_stem = question_text.strip() if question_text else "[Question presented in image/media]"

    if num_blanks <= 1:
        instructions = (
            "Provide the exact single word, number, or short phrase that belongs in the blank.\n"
            "Also provide 'plausible_wrong': a realistic human student mistake for this blank (e.g. wrong verb form/tense, singular vs plural, or natural typo). DO NOT write 'incorrect'.\n"
            "Respond strictly in JSON format matching this schema:\n"
            '{"answer": "the missing word or phrase", "plausible_wrong": "realistic student mistake", "reasoning": "brief explanation"}\n'
            'Example: {"answer": "speak", "plausible_wrong": "speaks", "reasoning": "Plural subject requires base form."}'
        )
    else:
        instructions = (
            f"Provide the missing word, number, or short phrase for EACH of the {num_blanks} blanks in order.\n"
            f"Also provide 'plausible_wrongs': list of realistic student mistakes for each blank. DO NOT write 'incorrect'.\n"
            "Respond strictly in JSON format matching this schema:\n"
            '{"answers": ["word1", "word2"], "plausible_wrongs": ["mistake1", "mistake2"], "reasoning": "brief explanation"}'
        )

    prompt = (
        f"Fill-in-the-blank Question:\n{q_stem}\n\n"
        f"Instructions:\n{instructions}"
    )

    system_prompt = (
        "You are an expert test and quiz solver. "
        "Complete fill-in-the-blank questions with the most accurate, standard concise answer. "
        "Also generate realistic human student mistakes ('plausible_wrong') for educational modeling. "
        "Never output the word 'incorrect' or 'wrong'. Always respond in JSON."
    )

    if image_base64:
        data_uri = image_base64 if image_base64.startswith("data:") else f"data:image/png;base64,{image_base64}"
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]
    else:
        user_content = prompt

    client = get_ai_client(api_key=key, base_url=url)
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=mdl,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                max_tokens=512,
                temperature=0.0,
            )
            choices = resp.choices or []
            if not choices:
                return ["answer"] * num_blanks, ["answers"] * num_blanks, "No choices returned by AI API"
            raw_content = choices[0].message.content or ""
            return _parse_fib_response(raw_content, num_blanks)

        except Exception as exc:
            last_exc = exc
            err_msg = str(exc)
            if "image" in err_msg.lower() and isinstance(user_content, list):
                user_content = prompt
                continue
            if "rate_limit" in err_msg.lower() or "429" in err_msg:
                time.sleep(1.5 * (attempt + 1))
                continue
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            break

    log_error(f"AI FIB solver failed after {max_retries + 1} attempt(s): {last_exc}")
    fallback_wrongs = [generate_plausible_wrong("answer")] * num_blanks
    return ["answer"] * num_blanks, fallback_wrongs, f"Error: {last_exc}"
