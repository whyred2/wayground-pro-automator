"""Quizit Standard fallback using the site's normal signed-in browser flow."""

import asyncio
import re
from urllib.parse import parse_qs, urlparse

from api import (
    _classify_identifier, extract_identifiers_from_page, get_discovered_pin,
    is_valid_game_pin, parse_quizit_answers, resolve_hash_to_pin,
)
from ui import log_error, log_info


QUIZIT_URL = "https://quizit.online/services/wayground"


async def resolve_quizit_pin(page, *identifiers) -> str | None:
    """Use the selected test's PIN, preserving leading zeroes."""
    hashes = []
    for identifier in (*identifiers, page.url, get_discovered_pin()):
        kind, value = _classify_identifier(identifier)
        if kind == "pin":
            return value
        if kind in ("hash", "id"):
            hashes.append(value)
    info = await extract_identifiers_from_page(page)
    if is_valid_game_pin(info.get("pin")):
        return info["pin"]
    if info.get("hash"):
        hashes.append(info["hash"])
    for room_hash in dict.fromkeys(hashes):
        pin = await asyncio.to_thread(resolve_hash_to_pin, room_hash)
        if is_valid_game_pin(str(pin or "")):
            return str(pin)
    return None


def _matches_bot_response(response, pin: str) -> bool:
    parsed = urlparse(response.url)
    return (parsed.hostname == "api.quizit.online"
            and parsed.path.rstrip("/") == "/quizizz/bot"
            and parse_qs(parsed.query).get("pin") == [pin])


async def fetch_quizit_browser_answers(context, pin: str) -> dict[str, list[str]] | None:
    """Let Quizit handle authentication; never extract or store login tokens."""
    if not is_valid_game_pin(pin):
        return None
    page = next((candidate for candidate in context.pages
                 if not candidate.is_closed()
                 and urlparse(candidate.url).hostname == "quizit.online"
                 and urlparse(candidate.url).path.rstrip("/") == "/services/wayground"), None)
    created = page is None
    if created:
        page = await context.new_page()
    received_answers = False
    try:
        log_info("Opening Quizit Standard in the browser...")
        if page.url.rstrip("/") != QUIZIT_URL:
            await page.goto(QUIZIT_URL, wait_until="domcontentloaded")
        sign_in = page.get_by_role("link", name="Sign in", exact=True)
        if await sign_in.is_visible():
            # Use the same redirect as the website's normal Get answers flow.
            await page.get_by_role("textbox").fill(pin)
            await page.get_by_role("button", name="Get answers", exact=True).click()
            await page.wait_for_url("**/auth/login**", timeout=10000)
            log_info("Quizit requires its own free account. Sign in in the Quizit tab.")
            log_info("Your Wayground account does not sign you in to Quizit.")
            choice = await asyncio.get_running_loop().run_in_executor(
                None, input, "  After signing in to Quizit, press ENTER to retry (or type s to skip): "
            )
            if choice.strip().lower() in ("s", "skip", "n", "no"):
                return None
            await page.goto(QUIZIT_URL, wait_until="domcontentloaded")
            if await sign_in.is_visible():
                log_error("Quizit sign-in is not complete. Continuing with other answer sources.")
                return None

        method = page.get_by_role("combobox", name="Answer method", exact=True)
        method_text = await method.inner_text()
        if not re.match(r"^(Standard|Bot)\b", method_text.strip(), re.I):
            await method.click()
            await page.get_by_role("option", name=re.compile(r"^(Standard|Bot)\b", re.I)).click()
        await page.get_by_role("textbox").fill(pin)
        log_info(f"Requesting Quizit Standard answer keys for PIN {pin}...")
        async with page.expect_response(lambda response: _matches_bot_response(response, pin),
                                        timeout=35000) as response_info:
            await page.get_by_role("button", name="Get answers", exact=True).click()
        response = await response_info.value
        if response.status == 401:
            log_error("Quizit session has expired. Sign in to Quizit again.")
            return None
        if response.status != 200:
            log_error(f"Quizit returned HTTP {response.status}; no answer keys were loaded.")
            return None
        answers = parse_quizit_answers(await response.json())
        received_answers = bool(answers)
        return answers or None
    except Exception as exc:
        log_error(f"Quizit browser fallback failed: {exc}")
        return None
    finally:
        # Preserve existing tabs and incomplete login pages for the user.
        if created and received_answers:
            await page.close()
