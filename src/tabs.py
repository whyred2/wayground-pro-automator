"""
Tab picker helpers for --attach mode: list, select, and confirm browser tabs.
"""

import asyncio

from config import C_RESET, C_GREEN, C_YELLOW, C_CYAN, C_BOLD, C_DIM, C_RED
from ui import log_info


async def get_live_pages(browser) -> list:
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
