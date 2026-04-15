"""
Test automation: highlighting, question answering loop, and results scraping.
"""

import asyncio
import random

from config import (
    SEL_CURRENT_QUESTION, SEL_CURRENT_QUESTION_INNER,
    SEL_OPTION_BUTTON, SEL_OPTION_TEXT, SEL_SUBMIT_BUTTON,
    SEL_CURRENT_Q_NUM, SEL_TOTAL_Q_NUM,
    SEL_STAT_CORRECT, SEL_STAT_INCORRECT, SEL_STAT_AVG_TIME, SEL_STAT_STREAK,
    SEL_ACCURACY_TOOLTIP,
    MIN_THINK_SECONDS, THINK_PER_CHAR, THINK_JITTER, CLICK_DELAY_MS,
    C_RESET, C_GREEN, C_RED, C_YELLOW, C_CYAN, C_BOLD, C_DIM,
)
from ui import log_info, log_found, log_progress, log_error, log_step, log_wrong
from matching import find_answers

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
except ImportError:
    PlaywrightTimeout = Exception


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


# ─── Helper Functions ──────────────────────────────────────────

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


# ─── Main Automation Loop ─────────────────────────────────────

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
        wrong_count = total - 1
        log_info(f"Adjusted to {wrong_count} wrong answers.")

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
            log_step(f"{C_YELLOW}[SKIP] No match for: \"{question_text[:50]}...\" — guessing randomly{C_RESET}")
            # Pick a random option instead of crashing
            buttons = await test_page.query_selector_all(SEL_OPTION_BUTTON)
            if buttons:
                random_btn = random.choice(buttons)
                random_text = await _get_btn_text(random_btn, SEL_OPTION_TEXT)
                log_step(f"Guessing: \"{random_text}\"")
                await asyncio.sleep(calc_think_time(question_text))
                await highlight_answer(test_page, random_btn)
                await asyncio.sleep(0.4)
                await random_btn.click()
                await asyncio.sleep(CLICK_DELAY_MS / 1000)
                await clear_highlights(test_page)
                await asyncio.sleep(1)
            continue

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
            log_step(f"{C_YELLOW}[SKIP] Answer options changed or not found — guessing randomly{C_RESET}")
            if buttons:
                random_btn = random.choice(buttons)
                random_text = await _get_btn_text(random_btn, SEL_OPTION_TEXT)
                log_step(f"Guessing: \"{random_text}\"")
                await highlight_answer(test_page, random_btn)
                await asyncio.sleep(0.4)
                await random_btn.click()
                await asyncio.sleep(CLICK_DELAY_MS / 1000)
                await clear_highlights(test_page)
                await asyncio.sleep(1)
            continue

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
                ans_str = ", ".join(f'"{a}"' for a in correct_answers)
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
                import sys
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
