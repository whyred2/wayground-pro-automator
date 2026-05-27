"""
CheatNetwork scraper: extract question-answer pairs from cheatnetwork.eu.
Supports automatic form submission (game pin / link) and graceful fallback.
"""

import asyncio
import sys

from config import (
    SEL_QUESTION_BOX, SEL_QUESTION_TEXT, SEL_ANSWER_TEXT,
    SEL_CN_INPUT, SEL_CN_SUBMIT,
)
from ui import log_info, log_step, log_error

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
except ImportError:
    PlaywrightTimeout = Exception


async def _fill_and_submit(page, quiz_input: str) -> bool:
    """
    Try to fill the CheatNetwork form with the quiz link/pin and submit.
    Returns True if the form was filled and submitted, False otherwise.
    """
    try:
        # Wait for the input field to appear (SPA may take a moment)
        await page.wait_for_selector(SEL_CN_INPUT, timeout=15000)
    except PlaywrightTimeout:
        # Fallback: try any visible text input
        log_step("Primary input selector not found, trying generic input...")
        try:
            await page.wait_for_selector('input[type="text"]', timeout=5000)
        except PlaywrightTimeout:
            log_error("Could not find the input field on CheatNetwork.")
            return False

    # Fill the input
    try:
        input_el = await page.query_selector(SEL_CN_INPUT)
        if not input_el:
            input_el = await page.query_selector('input[type="text"]')
        if not input_el:
            log_error("Input element not found.")
            return False

        await input_el.click()
        await input_el.fill(quiz_input)
        log_step(f"Entered: \"{quiz_input}\"")
    except Exception as e:
        log_error(f"Failed to fill input: {e}")
        return False

    # Click the submit button
    await asyncio.sleep(0.3)
    try:
        submit_btn = await page.query_selector(SEL_CN_SUBMIT)
        if not submit_btn:
            # Fallback: try button with "Get Answers" text
            submit_btn = await page.query_selector('button.button-style')
        if not submit_btn:
            log_error("Submit button not found.")
            return False

        await submit_btn.click()
        log_step("Clicked 'Get Answers'")
    except Exception as e:
        log_error(f"Failed to click submit: {e}")
        return False

    return True


async def _parse_question_boxes(page) -> dict[str, list[str]]:
    """
    Parse all .question-box elements on the page into a dict.
    Returns { question_text: [answer1, answer2, ...] }
    """
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

    return answers


async def scrape_answers(page, quiz_input: str | None = None) -> dict[str, list[str]] | None:
    """
    Scrape question-answer pairs from the CheatNetwork answer key page.
    
    If quiz_input is provided, tries to auto-fill the form with it.
    Returns a dict: { question_text: [answer1, answer2, ...] }
    Returns None if scraping failed (instead of exiting).
    """
    log_info("Waiting for CheatNetwork page to load...")

    # Wait for the page to be interactive
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(1)

    # Wait for either the form input or the question boxes to appear (handles automatic redirection)
    log_info("Checking page state (form vs answers)...")
    try:
        # Wait for either selector concurrently to handle SPA redirection race conditions
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(page.wait_for_selector(SEL_CN_INPUT, timeout=8000)),
                asyncio.create_task(page.wait_for_selector(SEL_QUESTION_BOX, timeout=8000))
            ],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        
        if await page.query_selector(SEL_QUESTION_BOX):
            log_info("✅ Answers are already loaded on the page. Skipping form submission.")
            quiz_input = None
    except Exception:
        pass

    # If the tab is already on the answers page, skip form filling
    current_url = page.url
    if "/answers#" in current_url:
        log_info("Already on the CheatNetwork answers page. Skipping form submission.")
        quiz_input = None

    # Base URL to return to in case of login redirects
    home_url = current_url.split("/answers#")[0] if "/answers#" in current_url else current_url
    if "/login" in home_url:
        home_url = "https://cheatnetwork.eu/services/quizizz"

    attempts = 3
    for attempt in range(attempts):
        attempt_quiz_input = quiz_input
        # ── Auto-fill form if we have quiz input ──
        if attempt_quiz_input:
            if "cheatnetwork.eu/services/quizizz/answers" in attempt_quiz_input:
                log_info(f"Navigating directly to answers URL: {attempt_quiz_input}")
                await page.goto(attempt_quiz_input, wait_until="domcontentloaded")
            else:
                log_info(f"Auto-filling CheatNetwork form (Attempt {attempt+1}/{attempts}) with: \"{attempt_quiz_input}\"")
                filled = await _fill_and_submit(page, attempt_quiz_input)
                if not filled:
                    if attempt < attempts - 1:
                        log_step("Auto-fill failed. Going back to form and retrying...")
                        await page.goto(home_url, wait_until="domcontentloaded")
                        await asyncio.sleep(2)
                        continue
                    else:
                        log_error("Auto-fill failed repeatedly.")
                        return None

        # ── Wait for answers or login modal/redirect ──
        log_info("Waiting for answers to load...")
        is_logged_out = False
        answers_appeared = False
        try:
            # Poll for up to 10 seconds to detect modal/redirect early
            for _ in range(20):
                await asyncio.sleep(0.5)
                if await page.query_selector(SEL_QUESTION_BOX):
                    answers_appeared = True
                    break
                
                # Check for login redirection
                if "/login" in page.url:
                    is_logged_out = True
                    break
                    
                # Check for headlessui dialog with "Not logged in" / "Access denied"
                dialog = await page.query_selector('[role="dialog"]')
                if dialog:
                    d_text = await dialog.inner_text()
                    if "Not logged in" in d_text or "Access denied" in d_text:
                        is_logged_out = True
                        break
                        
                # Check generic body text
                body_t = await page.inner_text("body")
                if "Not logged in" in body_t or "Access denied" in body_t:
                    is_logged_out = True
                    break
        except Exception:
            pass

        if is_logged_out:
            if attempt < attempts - 1:
                log_step(f"⚠ Got 'Not logged in' on CheatNetwork (Attempt {attempt+1}/{attempts}). Navigating back to form and retrying...")
                await page.goto(home_url, wait_until="domcontentloaded")
                await asyncio.sleep(2)
                continue
            else:
                log_error("Got 'Not logged in' modal or redirect repeatedly. Cannot proceed.")
                return None

        # Final wait for question box if not already appeared
        if not answers_appeared:
            try:
                await page.wait_for_selector(SEL_QUESTION_BOX, timeout=20000)
                break # Success!
            except PlaywrightTimeout:
                if attempt < attempts - 1:
                    log_step(f"Timeout waiting for answers (Attempt {attempt+1}/{attempts}). Retrying form submission...")
                    await page.goto(home_url, wait_until="domcontentloaded")
                    await asyncio.sleep(2)
                    continue
                else:
                    log_error("No .question-box elements appeared after 30 seconds.")
                    await page.screenshot(path="error_debug_scrape.png")
                    return None
        else:
            break # Success!

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

    # ── Parse all question boxes ──
    answers = await _parse_question_boxes(page)

    log_info(f"Successfully parsed {len(answers)} question-answer pairs.")

    msq_count = sum(1 for v in answers.values() if len(v) > 1)
    if msq_count > 0:
        log_info(f"  ↳ {msq_count} multi-select questions detected.")

    if len(answers) == 0:
        log_error("No answers were scraped from CheatNetwork.")
        await page.screenshot(path="error_debug_scrape.png")
        return None

    return answers
