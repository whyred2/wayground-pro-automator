"""
CheatNetwork scraper: extract question-answer pairs from cheatnetwork.eu.
"""

import asyncio
import sys

from config import SEL_QUESTION_BOX, SEL_QUESTION_TEXT, SEL_ANSWER_TEXT
from ui import log_info, log_step, log_error

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
except ImportError:
    PlaywrightTimeout = Exception


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

        # Store ALL answers for the question (accumulate to handle duplicate text across variations)
        if q_text not in answers:
            answers[q_text] = []
        for text in a_texts:
            if text not in answers[q_text]:
                answers[q_text].append(text)
                
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
