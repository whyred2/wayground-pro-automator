"""
CheatNetwork scraper: extract question-answer pairs from cheatnetwork.eu.
Supports automatic form submission (game pin / link) and graceful fallback.
"""

import asyncio
from time import monotonic
from urllib.parse import urlparse

from config import (
    SEL_QUESTION_BOX,
    SEL_CN_INPUT, SEL_CN_SUBMIT,
)
from ui import log_info, log_step, log_error
from answer_db import AnswerDatabase

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
    Preserve each visible question box, including repeated question wording.
    """
    answers = AnswerDatabase()
    try:
        raw_data = await page.evaluate("""
            () => {
                const list = [];
                const boxes = document.querySelectorAll('.question-box, [class*="question-box"]');
                for (const box of boxes) {
                    if (!box.getClientRects().length) continue;
                    // 1. Extract question text
                    let qEl = box.querySelector('p.font-semibold, p[class*="font-semibold"], p.break-words, p[class*="text-"]');
                    if (!qEl) {
                        const ps = box.querySelectorAll('p');
                        for (const p of ps) {
                            if (!p.closest('button')) {
                                qEl = p;
                                break;
                            }
                        }
                    }
                    if (!qEl) continue;
                    const qText = (qEl.innerText || qEl.textContent || '').trim();
                    if (!qText) continue;

                    // 2. Extract answer text(s)
                    const aTexts = [];
                    const lis = box.querySelectorAll('ul li');
                    if (lis.length > 0) {
                        for (const li of lis) {
                            const clone = li.cloneNode(true);
                            clone.querySelectorAll('svg, button, [aria-hidden="true"]').forEach(el => el.remove());
                            const aText = (clone.innerText || clone.textContent || '').trim();
                            if (aText && !aTexts.includes(aText)) {
                                aTexts.push(aText);
                            }
                        }
                    } else {
                        const spans = box.querySelectorAll('ul span, li span');
                        for (const s of spans) {
                            const t = (s.innerText || s.textContent || '').trim();
                            if (t && !aTexts.includes(t)) aTexts.push(t);
                        }
                    }
                    if (aTexts.length > 0) {
                        list.push({ question: qText, answers: aTexts,
                            qid: box.getAttribute('data-quesid') || box.getAttribute('data-question-id') || '' });
                    }
                }
                return list;
            }
        """)

        log_info(f"Found {len(raw_data)} parsed question boxes.")
        for i, item in enumerate(raw_data):
            q_text = item["question"]
            a_texts = item["answers"]
            answers.add_question(q_text, a_texts, qid=item.get("qid", ""))

            if len(a_texts) > 1:
                log_step(f"Q{i+1} [MSQ {len(a_texts)} answers]: \"{q_text[:45]}...\" → {a_texts}")
            else:
                log_step(f"Q{i+1}: \"{q_text[:55]}...\" → \"{a_texts[0]}\"")

    except Exception as e:
        log_error(f"Error while parsing question boxes: {e}")

    return answers


def _page_closed(page, error=None) -> bool:
    if page.is_closed():
        return True
    message = str(error or "").lower()
    return "has been closed" in message or "browser has disconnected" in message


async def read_cheatnetwork_state(page) -> dict:
    """Inspect visible dialogs, ignoring stale hidden login-modal content."""
    if _page_closed(page):
        return {"status": "closed", "questions": 0}
    try:
        return await page.evaluate("""() => {
            const visible = el => el && el.getClientRects().length > 0
                && getComputedStyle(el).visibility !== 'hidden';
            const dialogs = [...document.querySelectorAll(
                '[role="dialog"], [role="alertdialog"], [aria-modal="true"], [role="alert"]'
            )].filter(visible);
            const notice = dialogs.map(el => el.innerText || '').join(' ').toLowerCase();
            const boxes = [...document.querySelectorAll('.question-box, [class*="question-box"]')]
                .filter(visible);
            const ready = boxes.filter(box => [...box.querySelectorAll('ul li, li span')]
                .some(el => (el.innerText || '').trim()));
            // A download dialog takes precedence over a transient login notice
            // or partially rendered question boxes. Do not interrupt that request.
            if (/downloading\\s+answers|loading\\s+answers|fetching\\s+answers/.test(notice))
                return {status: 'downloading', questions: ready.length};
            if (/not\\s+logged\\s+in|access\\s+denied/.test(notice)
                || /(?:^|\\/)login(?:\\/|$)/i.test(location.pathname))
                return {status: 'login', questions: ready.length};
            if (ready.length) return {status: 'ready', questions: ready.length};
            const form = [...document.querySelectorAll('input[placeholder="Enter game pin or link"], input[type="text"]')]
                .some(visible);
            return {status: form ? 'form' : 'waiting', questions: 0};
        }""")
    except Exception as exc:
        if _page_closed(page, exc):
            return {"status": "closed", "questions": 0}
        if "execution context was destroyed" in str(exc).lower():
            return {"status": "waiting", "questions": 0}
        return {"status": "error", "questions": 0, "message": str(exc)}


async def _wait_for_answers(page, quiz_input, *, wait_timeout, download_timeout, initial_state=None) -> bool:
    deadline = monotonic() + wait_timeout
    submitted = False
    login_requested = False
    download_started = False
    login_seen_at = None
    last_progress = monotonic()
    while monotonic() < deadline:
        state = initial_state if initial_state is not None else await read_cheatnetwork_state(page)
        initial_state = None
        status = state["status"]
        if status != "login":
            login_seen_at = None
        if status == "ready":
            return True
        if status == "closed":
            log_error("The CheatNetwork tab or browser was closed. Select an open answer tab to continue.")
            return False
        if status == "error":
            log_error(f"Could not read CheatNetwork: {state.get('message', 'unknown error')}")
            return False
        if status == "downloading":
            if not download_started:
                download_started = True
                deadline = max(deadline, monotonic() + download_timeout)
                log_info("Downloading answers... Waiting for the dialog to close.")
            if monotonic() - last_progress >= 30:
                log_info("CheatNetwork is still downloading answers. Keeping the page open.")
                last_progress = monotonic()
        elif status == "login":
            if login_seen_at is None:
                login_seen_at = monotonic()
            # Some requests briefly show the login notice before the download
            # dialog. Give that transition time to complete without submitting again.
            if monotonic() - login_seen_at < 3:
                await asyncio.sleep(0.5)
                continue
            if login_requested:
                log_error("CheatNetwork still reports 'Not logged in'. No further requests were sent.")
                return False
            login_requested = True
            log_info("CheatNetwork reports 'Not logged in'. Sign in in that tab; the page will stay open.")
            choice = await asyncio.get_running_loop().run_in_executor(
                None, input, "  Sign in, then press ENTER to continue (or type s to skip): "
            )
            if choice.strip().lower() in ("s", "skip", "n", "no"):
                return False
            # Login time is user-controlled and must not consume the download wait.
            deadline = monotonic() + wait_timeout
            download_started = False
            submitted = False
            login_seen_at = None
            continue
        elif status == "form" and quiz_input and not submitted and not download_started:
            submitted = True
            if not await _fill_and_submit(page, quiz_input):
                return False
            log_info("Waiting for answers to load...")
        await asyncio.sleep(0.5)
    log_error("CheatNetwork did not finish loading answers. The page was kept open without reloading.")
    return False


async def scrape_answers(page, quiz_input: str | None = None, *,
                         wait_timeout: float = 120.0, download_timeout: float = 300.0
                         ) -> dict[str, list[str]] | None:
    """Read an existing answer tab or submit once and wait through its dialogs."""
    try:
        if _page_closed(page):
            log_error("The selected CheatNetwork tab was closed.")
            return None
        log_info("Checking CheatNetwork page state (answers / download / login / form)...")
        await page.wait_for_load_state("domcontentloaded")
        state = await read_cheatnetwork_state(page)
        if state["status"] == "ready":
            log_info("Answers are already loaded. Reading the selected tab without submitting the form.")
            quiz_input = None
        elif quiz_input:
            parsed = urlparse(quiz_input)
            if parsed.hostname == "cheatnetwork.eu" and parsed.path.startswith("/services/quizizz/answers"):
                if page.url != quiz_input:
                    await page.goto(quiz_input, wait_until="domcontentloaded")
                    state = await read_cheatnetwork_state(page)
                quiz_input = None
        if state["status"] != "ready" and not await _wait_for_answers(
            page, quiz_input, wait_timeout=wait_timeout, download_timeout=download_timeout, initial_state=state
        ):
            return None

        log_step("Scrolling to load all questions...")
        previous_count = 0
        stable_rounds = 0
        for _ in range(25):
            if _page_closed(page):
                return None
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await asyncio.sleep(0.5)
            boxes = await page.query_selector_all(SEL_QUESTION_BOX)
            count = len(boxes)
            stable_rounds = stable_rounds + 1 if count == previous_count and count > 0 else 0
            if stable_rounds >= 2:
                break
            previous_count = count
        await page.evaluate("window.scrollTo(0, 0)")
        answers = await _parse_question_boxes(page)
        if not answers:
            log_error("No answer keys were found in the selected CheatNetwork tab.")
            return None
        log_info(f"Successfully parsed {len(answers)} question-answer pairs.")
        return answers
    except Exception as exc:
        if _page_closed(page, exc):
            log_error("The CheatNetwork tab or browser was closed. Answer retrieval stopped safely.")
        else:
            log_error(f"Could not read CheatNetwork answers: {exc}")
        return None
