"""
Wayground Pro Automator
=======================
Automates tests on wayground.com using answer keys from cheatnetwork.eu/services/quizizz.
Uses two browser windows side-by-side with visual highlighting.

Usage:
    python main.py
    python main.py --test-url "https://wayground.com/some-test-page"
"""

import asyncio
import sys
import argparse
import random
import subprocess
import os
import time
from datetime import datetime

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    try:
        # playwright-stealth v2.x
        from playwright_stealth import Stealth
        async def apply_stealth(page):
            await Stealth().apply_stealth_async(page)
    except ImportError:
        # playwright-stealth v1.x fallback
        from playwright_stealth import stealth_async
        async def apply_stealth(page):
            await stealth_async(page)
except ImportError:
    print("\n[ERROR] Missing dependencies. Install them with:")
    print("  pip install -r requirements.txt")
    print("  python -m playwright install chromium\n")
    sys.exit(1)


# ─── Configuration ─────────────────────────────────────────────

ANSWERS_URL = "https://cheatnetwork.eu/services/quizizz"
TEST_URL = "https://wayground.com"

# Selectors — Answer Source (CheatNetwork)
SEL_QUESTION_BOX = ".question-box"
SEL_QUESTION_TEXT = "p.font-semibold.text-gray-200"
SEL_ANSWER_TEXT = "ul li span"

# Selectors — Test Page (Wayground)
SEL_CURRENT_QUESTION = "#questionText"
SEL_CURRENT_QUESTION_INNER = ".content-slot p"
SEL_OPTION_BUTTON = "button.option"
SEL_OPTION_TEXT = "#optionText .content-slot p"
SEL_SUBMIT_BUTTON = 'button[data-cy="submit-button"]'

# Selectors — Question Counter (Wayground)
SEL_CURRENT_Q_NUM = 'span[data-cy="current-question-number"]'
SEL_TOTAL_Q_NUM = 'span[data-cy="total-question-number"]'

# Selectors — Results Page (Wayground)
SEL_STAT_CORRECT = 'div[data-cy="stat-correct-container"] span'
SEL_STAT_INCORRECT = 'div[data-cy="stat-incorrect-container"] span'
SEL_STAT_AVG_TIME = 'div[data-cy="stat-avg-time-container"] span'
SEL_STAT_STREAK = 'div[data-cy="stat-streak-container"] span'
SEL_ACCURACY_TOOLTIP = '.accuracy-chart-wrapper .show-tooltip .content span'

# Timing
MIN_THINK_SECONDS = 8.0     # Minimum "thinking" time before answering
THINK_PER_CHAR = 0.05       # Extra seconds per character of question text
THINK_JITTER = 0.30         # ±30% random variation
CLICK_DELAY_MS = 300

# Colors for console output
C_RESET = "\033[0m"
C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_CYAN = "\033[96m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"


# ─── Logging ───────────────────────────────────────────────────

def log_info(msg: str):
    print(f"{C_CYAN}[INFO]{C_RESET} {msg}")


def log_found(msg: str):
    print(f"{C_GREEN}{C_BOLD}[FOUND]{C_RESET} {C_GREEN}{msg}{C_RESET}")


def log_progress(current: int, total: int, msg: str = ""):
    bar_len = 30
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = int(100 * current / total) if total > 0 else 0
    extra = f" — {msg}" if msg else ""
    print(f"{C_YELLOW}[PROGRESS]{C_RESET} [{bar}] {current}/{total} ({pct}%){extra}")


def log_error(msg: str):
    print(f"{C_RED}{C_BOLD}[CRITICAL ERROR]{C_RESET} {C_RED}{msg}{C_RESET}")


def log_step(msg: str):
    print(f"{C_DIM}  → {msg}{C_RESET}")

def log_wrong(msg: str):
    print(f"{C_RED}[WRONG]{C_RESET} {C_YELLOW}{msg}{C_RESET}")


# ─── Human-like Thinking Delay ─────────────────────────────────

def calc_think_time(question_text: str) -> float:
    """
    Calculate a realistic "thinking" delay based on question length.
    Longer questions → more time to read and think.
    Returns seconds with random jitter.
    """
    base = MIN_THINK_SECONDS + len(question_text) * THINK_PER_CHAR
    jitter = base * random.uniform(-THINK_JITTER, THINK_JITTER)
    result = base + jitter
    return max(MIN_THINK_SECONDS, round(result, 1))


# ─── Browser Auto-Detection (Edge / Chrome) ───────────────────

def find_browser_exe() -> tuple[str, str]:
    """
    Auto-detect Edge or Chrome executable on Windows.
    Returns (path, name) or exits if not found.
    """
    candidates = [
        # Edge (most common on Windows)
        (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
        (os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
        (os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
        # Chrome
        (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"), "Chrome"),
        (os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), "Chrome"),
        (os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"), "Chrome"),
    ]

    for path, name in candidates:
        if os.path.isfile(path):
            return path, name

    log_error("Could not find Edge or Chrome!")
    print(f"  {C_DIM}Looked in:{C_RESET}")
    for path, name in candidates:
        print(f"    {C_DIM}{path}{C_RESET}")
    sys.exit(1)


def get_user_data_dir(browser_name: str) -> str:
    """Get the default user data directory for the browser."""
    if browser_name == "Edge":
        return os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\User Data")
    else:
        return os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")


def is_port_open(port: int) -> bool:
    """Check if a CDP port is already open."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def launch_browser_with_debug(port: int) -> subprocess.Popen:
    """
    Find Edge/Chrome, launch with --remote-debugging-port.
    Uses the user's existing profile so all logins are preserved.
    """
    exe_path, browser_name = find_browser_exe()
    user_data = get_user_data_dir(browser_name)

    log_info(f"Found {browser_name}: {exe_path}")
    log_info(f"Profile: {user_data}")

    cmd = [
        exe_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    log_info(f"Launching {browser_name} with debug port {port}...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
    )

    # Wait for browser to start and open the debug port
    for i in range(15):
        if is_port_open(port):
            log_info(f"{browser_name} is ready! (port {port})")
            return proc
        time.sleep(1)
        if i % 3 == 2:
            log_step(f"Waiting for {browser_name} to start... ({i+1}s)")

    log_error(f"{browser_name} started but port {port} is not responding.")
    log_step("Try closing ALL browser windows first, then run the script again.")
    sys.exit(1)



# ─── Scraping: CheatNetwork Answer Keys ───────────────────────

async def scrape_answers(page) -> dict[str, list[str]]:
    """
    Scrape question-answer pairs from the CheatNetwork answer key page.
    Returns a dict: { question_text: [answer1, answer2, ...] }
    For single-answer questions the list has one item.
    For MSQ (multi-select) questions the list has multiple items.
    """
    log_info("Waiting for answer key page to load...")

    # Wait for at least one question box to appear
    try:
        await page.wait_for_selector(SEL_QUESTION_BOX, timeout=30000)
    except PlaywrightTimeout:
        log_error("No .question-box elements found on the answer key page. Is the URL correct?")
        await page.screenshot(path="error_debug_scrape.png")
        sys.exit(1)

    # Give extra time for JS to render
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(2)

    # Scroll down gradually to trigger lazy-loading of all questions
    log_step("Scrolling to load all questions...")
    prev_count = 0
    for _ in range(20):
        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await asyncio.sleep(0.6)
        boxes = await page.query_selector_all(SEL_QUESTION_BOX)
        if len(boxes) == prev_count and len(boxes) > 0:
            break  # No new items loaded — we're done
        prev_count = len(boxes)

    # Scroll back to top
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(0.5)

    # Scrape all question boxes
    answers: dict[str, list[str]] = {}
    boxes = await page.query_selector_all(SEL_QUESTION_BOX)

    log_info(f"Found {len(boxes)} question boxes. Parsing...")

    for i, box in enumerate(boxes):
        # Extract question text (handle nested <span> tags)
        q_el = await box.query_selector(SEL_QUESTION_TEXT)
        if not q_el:
            log_step(f"Q{i+1}: Skipped — no question text element found")
            continue

        q_text = (await q_el.inner_text()).strip()
        if not q_text:
            log_step(f"Q{i+1}: Skipped — empty question text")
            continue

        # Extract ALL answer options (some questions have multiple correct answers)
        a_els = await box.query_selector_all(SEL_ANSWER_TEXT)
        a_texts = []
        for a_el in a_els:
            t = (await a_el.inner_text()).strip()
            if t:
                a_texts.append(t)

        if not a_texts:
            log_step(f"Q{i+1}: ⚠ No answer found for: \"{q_text[:60]}...\"")
            continue

        # Store ALL answers for the question
        answers[q_text] = a_texts
        if len(a_texts) > 1:
            log_step(f"Q{i+1} [MSQ {len(a_texts)} answers]: \"{q_text[:45]}...\" → {a_texts}")
        else:
            log_step(f"Q{i+1}: \"{q_text[:55]}...\" → \"{a_texts[0]}\"")

    log_info(f"Successfully parsed {len(answers)} question-answer pairs.")

    msq_count = sum(1 for v in answers.values() if len(v) > 1)
    if msq_count > 0:
        log_info(f"  ↳ {msq_count} multi-select questions detected.")

    if len(answers) == 0:
        log_error("No answers were scraped. Cannot continue.")
        await page.screenshot(path="error_debug_scrape.png")
        sys.exit(1)

    return answers


# ─── Matching Logic ────────────────────────────────────────────

def find_answers(question: str, answers_db: dict[str, list[str]]) -> list[str] | None:
    """
    Find the answer(s) for a given question using multiple matching strategies:
    1. Exact match (case-insensitive, stripped)
    2. Substring / contains match
    3. Fuzzy similarity (Levenshtein-based, threshold 80%)

    Returns a list of correct answer strings, or None if not found.
    """
    q_norm = question.strip().lower()

    # Strategy 1: Exact match
    for key, val in answers_db.items():
        if key.strip().lower() == q_norm:
            return val

    # Strategy 2: Substring match
    for key, val in answers_db.items():
        k = key.strip().lower()
        if k in q_norm or q_norm in k:
            return val

    # Strategy 3: Fuzzy match
    for key, val in answers_db.items():
        if _similarity(key.strip().lower(), q_norm) > 0.80:
            return val

    return None


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


# ─── Highlighting via page.evaluate() ─────────────────────────

async def highlight_question(page, selector: str):
    """Add a dashed yellow border to the question container."""
    await page.evaluate(f"""
        (() => {{
            const el = document.querySelector('{selector}');
            if (el) {{
                el.style.border = '5px dashed #FFD600';
                el.style.borderRadius = '8px';
                el.style.transition = 'border 0.3s ease';
            }}
        }})()
    """)


async def highlight_answer(page, button_handle):
    """Add a solid green border to the answer button."""
    await button_handle.evaluate("""
        (el) => {
            el.style.border = '5px solid #00E676';
            el.style.borderRadius = '8px';
            el.style.transition = 'border 0.3s ease';
            el.style.boxShadow = '0 0 15px rgba(0, 230, 118, 0.5)';
        }
    """)


async def clear_highlights(page):
    """Remove all injected highlights."""
    await page.evaluate("""
        () => {
            document.querySelectorAll('[style*="border"]').forEach(el => {
                el.style.border = '';
                el.style.borderRadius = '';
                el.style.boxShadow = '';
            });
        }
    """)


# ─── Main Automation Loop ─────────────────────────────────────

def _text_matches(btn_text: str, answer_text: str) -> bool:
    """Check if button text matches an answer (case-insensitive, partial)."""
    a = btn_text.strip().lower()
    b = answer_text.strip().lower()
    return a == b or b in a or a in b


async def _get_btn_text(btn, sel: str) -> str:
    """Extract text from a button's inner option text element."""
    text_el = await btn.query_selector(sel)
    if text_el:
        return (await text_el.inner_text()).strip()
    return (await btn.inner_text()).strip()


async def _read_question_counter(page) -> tuple[int, int]:
    """
    Read the current/total question numbers from the Wayground test page.
    Returns (current, total). Returns (0, 0) if not found.
    """
    current = 0
    total = 0
    try:
        cur_el = await page.query_selector(SEL_CURRENT_Q_NUM)
        tot_el = await page.query_selector(SEL_TOTAL_Q_NUM)
        if cur_el:
            current = int((await cur_el.inner_text()).strip())
        if tot_el:
            total = int((await tot_el.inner_text()).strip())
    except Exception:
        pass
    return current, total


async def automate_test(test_page, answers_db: dict[str, list[str]], wrong_count: int = 0):
    """
    Main loop: detect question on test page, match with DB, click answer.
    Supports both single-answer and multi-select (MSQ) questions.
    wrong_count: how many questions to answer INCORRECTLY on purpose.
    """
    answered = 0
    correct = 0
    wrong = 0

    # Try to read the real total from the test page
    _, page_total = await _read_question_counter(test_page)
    total = page_total if page_total > 0 else len(answers_db)

    if wrong_count >= total and total > 0:
        log_error(f"You requested {wrong_count} wrong answers, but the test only has {total} questions!")
        sys.exit(1)

    # Pre-select which question numbers will be answered wrong
    if wrong_count > 0:
        wrong_indices = set(random.sample(range(1, total + 1), wrong_count))
        log_info(f"🎲 Will deliberately answer {wrong_count} questions wrong (not 100%)")
    else:
        wrong_indices = set()

    log_info(f"Starting automation: {total} questions (from test page), {len(answers_db)} answers loaded.")
    if wrong_count > 0:
        expected_correct = total - wrong_count
        expected_pct = int(100 * expected_correct / total) if total > 0 else 0
        log_info(f"Target score: ~{expected_correct}/{total} ({expected_pct}%)")
    log_info("Waiting for the first question to appear...")

    # Track the last question to avoid re-processing
    last_question = ""

    while True:
        # Wait for the question element to appear
        try:
            await test_page.wait_for_selector(SEL_CURRENT_QUESTION, timeout=15000)
        except PlaywrightTimeout:
            log_info("No more questions detected. Test may be complete!")
            break

        # Extract the current question text
        question_text = ""
        try:
            inner_el = await test_page.query_selector(f"{SEL_CURRENT_QUESTION} {SEL_CURRENT_QUESTION_INNER}")
            if inner_el:
                question_text = (await inner_el.inner_text()).strip()

            if not question_text:
                container = await test_page.query_selector(SEL_CURRENT_QUESTION)
                if container:
                    question_text = (await container.inner_text()).strip()
        except Exception:
            pass

        if not question_text:
            await asyncio.sleep(0.5)
            continue

        # Skip if same question as before (debounce)
        if question_text == last_question:
            await asyncio.sleep(0.5)
            continue

        last_question = question_text
        answered += 1

        # ── Read live counter from the page ──
        page_current, page_total = await _read_question_counter(test_page)
        if page_total > 0:
            total = page_total
        display_num = page_current if page_current > 0 else answered

        # ── "Thinking" delay — human-like, based on question length ──
        think_time = calc_think_time(question_text)
        log_progress(display_num, total, f"Q: \"{question_text[:40]}...\"")
        log_step(f"⏱ Thinking for {think_time}s...")
        await asyncio.sleep(think_time)

        # ── Decide: answer correctly or deliberately wrong? ──
        deliberate_wrong = answered in wrong_indices

        # ── Find correct answer(s) from DB ──
        correct_answers = find_answers(question_text, answers_db)

        if correct_answers is None:
            log_error(f"Match not found for Q: \"{question_text}\"")
            await test_page.screenshot(path="error_debug.png")
            log_info("Screenshot saved as error_debug.png")
            sys.exit(1)

        # ── Detect MSQ mode ──
        is_msq = await test_page.query_selector("button.option.is-msq") is not None

        # ── Highlight question ──
        await highlight_question(test_page, SEL_CURRENT_QUESTION)

        # ── Get all option buttons with their text ──
        buttons = await test_page.query_selector_all(SEL_OPTION_BUTTON)

        # Categorize buttons: correct vs wrong
        correct_buttons = []
        wrong_buttons = []

        for btn in buttons:
            btn_text = await _get_btn_text(btn, SEL_OPTION_TEXT)
            is_correct = any(_text_matches(btn_text, ans) for ans in correct_answers)
            if is_correct:
                correct_buttons.append((btn, btn_text))
            else:
                wrong_buttons.append((btn, btn_text))

        if not correct_buttons:
            log_error(f"No matching button found for answers: {correct_answers}")
            log_error(f"Question was: \"{question_text}\"")
            # Log available options for debugging
            for btn in buttons:
                t = await _get_btn_text(btn, SEL_OPTION_TEXT)
                log_step(f"  Available option: \"{t}\"")
            await test_page.screenshot(path="error_debug.png")
            log_info("Screenshot saved as error_debug.png")
            sys.exit(1)

        # ─────────────────────────────────────────────────
        # MSQ: Multi-Select Question
        # ─────────────────────────────────────────────────
        if is_msq:
            log_info(f"📋 MSQ detected — {len(correct_answers)} correct answer(s)")

            if deliberate_wrong:
                # Deliberately wrong: pick some wrong ones, skip some correct
                wrong += 1
                log_wrong(f"Q{answered}: Deliberately picking WRONG for MSQ! ({wrong}/{wrong_count})")
                # Click one random wrong + skip one correct
                targets = []
                if wrong_buttons:
                    targets.append(random.choice(wrong_buttons))
                # Add some (but not all) correct answers to make it partially wrong
                if len(correct_buttons) > 1:
                    targets.extend(correct_buttons[:len(correct_buttons) - 1])
                elif correct_buttons:
                    # Only one correct — just click the wrong one
                    pass
            else:
                correct += 1
                targets = correct_buttons
                ans_str = ", ".join(f'\"{a}\"' for a in correct_answers)
                log_found(f"Q: \"{question_text[:40]}...\" -> A: [{ans_str}]")

            # Click each target with a small delay between
            for i, (btn, btn_text) in enumerate(targets):
                await highlight_answer(test_page, btn)
                await asyncio.sleep(random.uniform(0.4, 0.8))
                log_step(f"  Selecting [{i+1}/{len(targets)}]: \"{btn_text}\"")
                await btn.click()
                await asyncio.sleep(random.uniform(0.3, 0.6))

            # Click the Submit button
            await asyncio.sleep(random.uniform(0.5, 1.0))
            submit_btn = await test_page.query_selector(SEL_SUBMIT_BUTTON)
            if submit_btn:
                log_step("Clicking Submit (Отправить)...")
                await submit_btn.click()
            else:
                log_error("Submit button not found!")
                await test_page.screenshot(path="error_debug.png")
                sys.exit(1)

        # ─────────────────────────────────────────────────
        # Single-answer question
        # ─────────────────────────────────────────────────
        else:
            if deliberate_wrong and wrong_buttons:
                target_btn, target_text = random.choice(wrong_buttons)
                wrong += 1
                log_wrong(f"Q{answered}: Deliberately picking WRONG answer! ({wrong}/{wrong_count})")
            else:
                target_btn, target_text = correct_buttons[0]
                correct += 1
                log_found(f"Q: \"{question_text[:50]}...\" -> A: \"{correct_answers[0]}\"")

            await highlight_answer(test_page, target_btn)
            await asyncio.sleep(0.8)

            log_step(f"Clicking: \"{target_text}\"")
            await target_btn.click()

        # Post-click delay
        await asyncio.sleep(CLICK_DELAY_MS / 1000)

        # Clear highlights
        await clear_highlights(test_page)

        # Wait for page transition
        await asyncio.sleep(1)

    # ── Summary ──
    print()
    log_info(f"✅ Automation complete!")
    log_info(f"   Total: {answered}  |  ✅ Correct: {correct}  |  ❌ Wrong: {wrong}")
    if answered > 0:
        pct = int(100 * correct / answered)
        log_info(f"   Estimated score: ~{pct}%")


# ─── Results Scraping ──────────────────────────────────────────

async def scrape_results(test_page, timeout: int = 30):
    """
    Wait for the results page to appear and scrape stats from Wayground.
    Prints accuracy, points, correct/incorrect, avg time, and streak.
    """
    log_info("Waiting for results page to load...")

    # Wait for any stat container to appear
    try:
        await test_page.wait_for_selector(
            'div[data-cy="stat-correct-container"]',
            timeout=timeout * 1000
        )
    except PlaywrightTimeout:
        log_step("Results page did not appear within timeout. Skipping.")
        return

    await asyncio.sleep(2)  # Let all elements render

    results = {}

    # ── Stats badges ──
    for sel, label in [
        (SEL_STAT_CORRECT, "Correct"),
        (SEL_STAT_INCORRECT, "Incorrect"),
        (SEL_STAT_AVG_TIME, "Avg Time"),
        (SEL_STAT_STREAK, "Streak"),
    ]:
        try:
            el = await test_page.query_selector(sel)
            if el:
                results[label] = (await el.inner_text()).strip()
        except Exception:
            pass

    # ── Accuracy / Points tooltip ──
    accuracy_text = ""
    try:
        el = await test_page.query_selector(SEL_ACCURACY_TOOLTIP)
        if el:
            accuracy_text = (await el.inner_text()).strip()
    except Exception:
        pass

    # ── Print results ──
    print()
    print(f"{C_CYAN}{'═'*60}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}  📊  RESULTS FROM WAYGROUND{C_RESET}")
    print(f"{C_CYAN}{'═'*60}{C_RESET}")

    if results:
        for label, value in results.items():
            if "Correct" in label:
                color = C_GREEN
            elif "Incorrect" in label:
                color = C_RED
            elif "Time" in label:
                color = C_CYAN
            else:
                color = C_YELLOW
            print(f"  {color}{label:<12}{C_RESET}  {value}")

    if accuracy_text:
        print(f"\n  {C_BOLD}Points:{C_RESET}  {accuracy_text}")

    print(f"{C_CYAN}{'═'*60}{C_RESET}")
    print()


# ─── Tab Picker (for --attach mode) ───────────────────────────

async def _get_live_pages(browser) -> list:
    """Gather all open (non-closed) pages from all browser contexts."""
    pages = []
    for ctx in browser.contexts:
        for page in ctx.pages:
            if not page.is_closed():
                pages.append(page)
    return pages


async def _page_label(page) -> tuple[str, str]:
    """Get a safe title and url for a page (handles closed pages)."""
    try:
        title = await page.title() or "(no title)"
    except Exception:
        title = "(closed)"
    url = page.url or ""
    return title, url


async def pick_tab(pages: list, role_name: str, keyword_hint: str) -> object:
    """
    Show the user a numbered list of open tabs and let them pick one.
    Returns the selected page object.
    """
    print(f"\n{C_CYAN}{'─'*60}{C_RESET}")
    print(f"  Select the {C_BOLD}{role_name}{C_RESET} tab:")
    print(f"{C_CYAN}{'─'*60}{C_RESET}")

    best_guess = 0
    for i, page in enumerate(pages):
        title, url = await _page_label(page)
        marker = ""
        if keyword_hint and keyword_hint.lower() in url.lower():
            marker = f" {C_GREEN}← suggested{C_RESET}"
            best_guess = i
        title_short = title[:50] + "..." if len(title) > 50 else title
        url_short = url[:60] + "..." if len(url) > 60 else url
        print(f"  {C_BOLD}{i+1}{C_RESET}) {title_short}")
        print(f"     {C_DIM}{url_short}{C_RESET}{marker}")

    print()
    while True:
        choice = await asyncio.get_event_loop().run_in_executor(
            None, input, f"  Enter number [default: {best_guess+1}]: "
        )
        choice = choice.strip()
        if not choice:
            return pages[best_guess]
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(pages):
                return pages[idx]
        except ValueError:
            pass
        print(f"  {C_RED}Invalid. Enter 1-{len(pages)}.{C_RESET}")


async def pick_both_tabs(browser, answers_hint: str, test_hint: str):
    """
    Let user pick answer and test tabs, with confirmation and retry option.
    Returns (page_answers, page_test).
    """
    while True:
        all_pages = await _get_live_pages(browser)

        if not all_pages:
            return None, None

        log_info(f"Found {len(all_pages)} open tab(s).")

        page_answers = await pick_tab(all_pages, "📖 ANSWERS (CheatNetwork)", answers_hint)
        page_test = await pick_tab(all_pages, "🎯 TEST (Wayground)", test_hint)

        # ── Show confirmation ──
        ans_title, ans_url = await _page_label(page_answers)
        test_title, test_url = await _page_label(page_test)

        print()
        print(f"{C_CYAN}{'─'*60}{C_RESET}")
        print(f"  {C_BOLD}Your selection:{C_RESET}")
        print(f"  📖 Answers: {ans_title[:40]}")
        print(f"     {C_DIM}{ans_url[:55]}{C_RESET}")
        print(f"  🎯 Test:    {test_title[:40]}")
        print(f"     {C_DIM}{test_url[:55]}{C_RESET}")
        print(f"{C_CYAN}{'─'*60}{C_RESET}")
        print()

        confirm = await asyncio.get_event_loop().run_in_executor(
            None, input, f"  Correct? ({C_GREEN}Enter{C_RESET} = yes, {C_YELLOW}r{C_RESET} = re-pick): "
        )

        if confirm.strip().lower() not in ("r", "re", "retry", "n", "no"):
            return page_answers, page_test

        print(f"\n  {C_YELLOW}Re-picking tabs...{C_RESET}")


# ─── Entry Point ───────────────────────────────────────────────

CDP_PORT = 9222

async def main():
    parser = argparse.ArgumentParser(
        description="Wayground Pro Automator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Modes:
  Normal (default):  Opens a new Playwright browser. You log in, then automation starts.
  Attach (--attach): Auto-launches your Edge/Chrome with debug mode, connects to
                     existing tabs. Keeps your logins! Pick tabs from a list.
        """
    )
    parser.add_argument(
        "--test-url",
        default=TEST_URL,
        help=f"URL of the test page (default: {TEST_URL})"
    )
    parser.add_argument(
        "--answers-url",
        default=ANSWERS_URL,
        help=f"URL of the answer key page (default: {ANSWERS_URL})"
    )
    parser.add_argument(
        "--wrong",
        type=int,
        default=0,
        help="Number of questions to answer WRONG on purpose (for a non-100%% score). Default: 0"
    )
    parser.add_argument(
        "--attach",
        action="store_true",
        default=False,
        help="Attach to Edge/Chrome (auto-launches with debug port if needed)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=CDP_PORT,
        help=f"CDP port for --attach mode (default: {CDP_PORT})"
    )
    args = parser.parse_args()

    print(f"""
{C_CYAN}╔══════════════════════════════════════════════╗
║        Wayground Pro Automator   v1.0        ║
╚══════════════════════════════════════════════╝{C_RESET}
    """)

    # Interactive setup if no arguments were provided
    if len(sys.argv) == 1:
        print(f"{C_CYAN}Interactive Setup (no arguments provided){C_RESET}")
        print(f"{C_DIM}{'─'*60}{C_RESET}")
        
        print(f"  {C_BOLD}Select Mode:{C_RESET}")
        print(f"  {C_CYAN}1{C_RESET}) Attach to your Edge/Chrome (Recommended! Keeps logins)")
        print(f"  {C_CYAN}2{C_RESET}) Open new standalone browser")
        
        mode = await asyncio.get_event_loop().run_in_executor(
            None, input, "  Enter choice [default: 1]: "
        )
        args.attach = (mode.strip() != '2')
        
        print()
        print(f"  {C_BOLD}Mistakes settings:{C_RESET}")
        wrong = await asyncio.get_event_loop().run_in_executor(
            None, input, "  How many questions to answer WRONG? (0 for 100%) [default: 0]: "
        )
        if wrong.strip().isdigit():
            args.wrong = int(wrong.strip())
            
        print(f"{C_DIM}{'─'*60}{C_RESET}\n")

    async with async_playwright() as p:

        # ═══════════════════════════════════════════════════
        #  MODE: --attach (auto-find & connect to Edge/Chrome)
        # ═══════════════════════════════════════════════════
        if args.attach:
            port = args.port
            browser_proc = None

            if is_port_open(port):
                log_info(f"Browser already running on port {port} — connecting...")
            else:
                log_info("No debug port detected. Launching browser automatically...")
                browser_proc = launch_browser_with_debug(port)

            cdp_url = f"http://localhost:{port}"

            try:
                browser = await p.chromium.connect_over_cdp(cdp_url)
            except Exception as e:
                log_error(f"Could not connect on port {port}!")
                print(f"  {C_DIM}Error: {e}{C_RESET}")
                print(f"\n  {C_YELLOW}Tip: Close ALL Edge/Chrome windows first, then try again.{C_RESET}\n")
                sys.exit(1)

            # Check for open tabs
            all_pages = await _get_live_pages(browser)

            if not all_pages:
                # Fresh browser — open pages for the user
                log_info("No tabs open yet. Opening answer key and test pages...")
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                page_answers = await ctx.new_page()
                await page_answers.goto(args.answers_url, wait_until="domcontentloaded")
                page_test = await ctx.new_page()
                await page_test.goto("https://wayground.com", wait_until="domcontentloaded")

                print()
                print(f"{C_YELLOW}{'─'*60}{C_RESET}")
                print(f"{C_BOLD}{C_YELLOW}⏸  LOG IN & NAVIGATE{C_RESET}")
                print(f"{C_YELLOW}{'─'*60}{C_RESET}")
                print(f"  1️⃣   Log in to Wayground in the browser")
                print(f"  2️⃣   Navigate to: {C_CYAN}{args.test_url}{C_RESET}")
                print(f"  3️⃣   Come back here and press Enter")
                print(f"{C_YELLOW}{'─'*60}{C_RESET}")
                print()

                await asyncio.get_event_loop().run_in_executor(
                    None, input, "  ▶  Press ENTER when ready..."
                )
                print()
            else:
                # Tabs exist — let user pick with confirmation
                page_answers, page_test = await pick_both_tabs(browser, "cheatnetwork", "wayground")

                if page_answers is None:
                    log_error("No open tabs available!")
                    sys.exit(1)

                print()

            # Scrape & automate
            await _run_phases(page_answers, page_test, args)

            print()
            log_info("Done! 🎉 (Browser left open — use --attach again for the next test)")

        # ═══════════════════════════════════════════════════
        #  MODE: Normal (launch new Playwright browser)
        # ═══════════════════════════════════════════════════
        else:
            try:
                browser = await p.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"]
                )
            except Exception as e:
                err_msg = str(e).lower()
                if "executable doesn't exist" in err_msg or "playwright install" in err_msg:
                    log_info("Playwright browsers not found!")
                    log_step("Starting automatic installation (this may take a few minutes)...")
                    
                    import subprocess
                    from playwright._impl._driver import compute_driver_executable, get_driver_env
                    
                    driver_exec = compute_driver_executable()
                    env = get_driver_env()
                    if isinstance(driver_exec, tuple):
                        cmd = list(driver_exec)
                    else:
                        cmd = [str(driver_exec)]
                    cmd.extend(["install", "chromium"])
                    
                    try:
                        # Output goes directly to console so user can see progress (download percentage)
                        subprocess.run(cmd, env=env, check=True)
                        print()
                        log_info("Chromium installed successfully! Relaunching...")
                        browser = await p.chromium.launch(
                            headless=False,
                            args=["--disable-blink-features=AutomationControlled"]
                        )
                    except Exception as inst_e:
                        log_error(f"Failed to auto-install Chromium: {inst_e}")
                        print(f"  {C_DIM}Please manually run: python -m playwright install chromium{C_RESET}")
                        sys.exit(1)
                else:
                    raise e

            UA = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )

            ctx_answers = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=UA,
            )
            page_answers = await ctx_answers.new_page()
            await apply_stealth(page_answers)

            ctx_test = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=UA,
            )
            page_test = await ctx_test.new_page()
            await apply_stealth(page_test)

            log_info(f"Opening answer key page: {args.answers_url}")
            await page_answers.goto(args.answers_url, wait_until="domcontentloaded")

            log_info("Opening Wayground login page...")
            await page_test.goto("https://wayground.com", wait_until="domcontentloaded")

            print()
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print(f"{C_BOLD}{C_YELLOW}⏸  MANUAL LOGIN REQUIRED{C_RESET}")
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print(f"  1️⃣   In the {C_CYAN}Wayground{C_RESET} browser window — log in to your account.")
            print(f"  2️⃣   Navigate to your test URL:")
            print(f"       {C_CYAN}{args.test_url}{C_RESET}")
            print(f"  3️⃣   Once you see the test/waiting screen — come back here.")
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print()

            await asyncio.get_event_loop().run_in_executor(
                None, input, "  ▶  Press ENTER when you are on the test page and ready to start..."
            )
            print()

            await _run_phases(page_answers, page_test, args)

            print()
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            await asyncio.get_event_loop().run_in_executor(
                None, input, "  ✅  Done! Press ENTER to close the browser..."
            )
            await browser.close()

            log_info("Done! 🎉")


async def _run_phases(page_answers, page_test, args):
    """Shared logic: scrape answers, print table, run automation."""

    log_info("=" * 50)
    log_info("PHASE 1: Scraping answer keys...")
    log_info("=" * 50)
    answers_db = await scrape_answers(page_answers)

    print(f"\n{C_CYAN}{'#':<4} {'Question':<55} {'Answer(s)':<35}{C_RESET}")
    print(f"{C_DIM}{'─'*4} {'─'*55} {'─'*35}{C_RESET}")
    for i, (q, answers_list) in enumerate(answers_db.items()):
        q_short = q[:52] + "..." if len(q) > 52 else q
        if len(answers_list) == 1:
            a_short = answers_list[0][:32] + "..." if len(answers_list[0]) > 32 else answers_list[0]
        else:
            a_short = f"[{len(answers_list)}] " + ", ".join(a[:15] for a in answers_list)
            if len(a_short) > 32:
                a_short = a_short[:29] + "..."
        print(f"{C_DIM}{i+1:<4}{C_RESET} {q_short:<55} {C_GREEN}{a_short:<35}{C_RESET}")
    print()

    log_info("=" * 50)
    log_info("PHASE 2: Automating test...")
    log_info("=" * 50)
    await automate_test(page_test, answers_db, wrong_count=args.wrong)

    # ── Phase 3: Scrape results ──
    log_info("=" * 50)
    log_info("PHASE 3: Reading results from Wayground...")
    log_info("=" * 50)
    await scrape_results(page_test, timeout=30)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        pass  # sys.exit() calls shouldn't print an extra traceback
    except KeyboardInterrupt:
        print(f"\n{C_RED}[INFO] Automation stopped by user.{C_RESET}")
    except Exception as e:
        pass # Unhandled exceptions will print their own traceback
    finally:
        # Prevents the console window from instantly closing on fatal errors or when finished
        print()
        input(f"{C_DIM}Press ENTER to exit...{C_RESET}")
