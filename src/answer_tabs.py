"""Select and preserve existing CheatNetwork tabs during answer retrieval."""

import asyncio
from urllib.parse import urlparse

from scraper import read_cheatnetwork_state, scrape_answers
from tabs import get_live_pages, pick_tab
from ui import log_error, log_info


def is_cheatnetwork_page(page) -> bool:
    host = (urlparse(page.url).hostname or "").lower()
    return host == "cheatnetwork.eu" or host.endswith(".cheatnetwork.eu")


async def select_existing_answer_tab(browser, *, ready_only=False):
    candidates = [page for page in await get_live_pages(browser) if is_cheatnetwork_page(page)]
    if not candidates:
        return None
    states = await asyncio.gather(*(read_cheatnetwork_state(page) for page in candidates))
    pages = [page for page, state in zip(candidates, states)
             if state["status"] not in ("closed", "error")
             and (not ready_only or state["status"] == "ready")]
    if not pages:
        return None
    log_info(f"Found {len(pages)} open CheatNetwork answer tab(s).")
    return await pick_tab(
        pages, "ANSWERS (CheatNetwork)", "/answers", allow_skip=True,
        skip_label="Continue automatic lookup" if ready_only else "Open a new CheatNetwork tab",
    )


async def retrieve_cheatnetwork_answers(browser, context, quiz_input, answers_url, *,
                                      preferred_page=None):
    page = preferred_page if preferred_page and not preferred_page.is_closed() else None
    owned_page = None
    answers = None
    try:
        if page is None:
            page = await select_existing_answer_tab(browser)
        if page is None:
            log_info("Opening CheatNetwork in a new tab...")
            page = owned_page = await context.new_page()
            await page.goto(answers_url, wait_until="domcontentloaded")
        else:
            log_info("Using the selected CheatNetwork tab without reloading it.")
        answers = await scrape_answers(page, quiz_input=quiz_input)
        if answers:
            return answers, "CheatNetwork"

        if not browser.is_connected():
            log_error("The browser was closed. Reopen it and run the program again.")
            return None, ""
        if page.is_closed():
            log_info("The answer tab was closed. Select another CheatNetwork tab.")
            page = await select_existing_answer_tab(browser)
            if page is None:
                return None, ""

        log_info("Automatic retrieval did not produce answers. The selected CheatNetwork tab is open.")
        log_info("Sign in if needed, request answers, and wait for 'Downloading answers...' to finish.")
        choice = await asyncio.get_running_loop().run_in_executor(
            None, input, "  Press ENTER to read the answers (or type s to skip CheatNetwork): "
        )
        if choice.strip().lower() in ("s", "skip", "n", "no"):
            return None, ""
        if not browser.is_connected():
            log_error("The browser was closed. Reopen it and run the program again.")
            return None, ""
        if page.is_closed():
            log_info("The answer tab was closed. Select another open answer tab.")
            page = await select_existing_answer_tab(browser)
            if page is None:
                return None, ""
        answers = await scrape_answers(page, quiz_input=None)
        return answers, "CheatNetwork (manual)" if answers else ""
    except Exception as exc:
        if not browser.is_connected():
            log_error("The browser was closed. Answer retrieval stopped safely.")
        else:
            log_error(f"CheatNetwork retrieval failed: {exc}")
        return None, ""
    finally:
        # Only a temporary tab created here may be closed after successful use.
        if owned_page and answers and not owned_page.is_closed():
            try:
                await owned_page.close()
            except Exception:
                pass
