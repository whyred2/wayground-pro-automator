"""
Wayground Pro Automator
=======================
Automates tests on wayground.com using answer keys from the direct API
or cheatnetwork.eu/services/quizizz as a fallback.

Usage:
    python src/main.py
    python src/main.py --attach --wrong 5
"""

import asyncio
import sys
import argparse
import os

# Suppress Node.js deprecation warnings (DEP0169 from Playwright internals)
os.environ["NODE_OPTIONS"] = "--no-deprecation"

# force Playwright (in the compiled .exe) to search for browsers in the global folder
if getattr(sys, 'frozen', False) and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    _local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(_local_appdata, "ms-playwright")

try:
    from playwright.async_api import async_playwright
    try:
        # playwright-stealth v2.x
        from playwright_stealth import Stealth
        async def apply_stealth(page):
            await Stealth().apply_stealth_async(page)
    except Exception:
        try:
            # playwright-stealth v1.x fallback
            from playwright_stealth import stealth_async
            async def apply_stealth(page):
                await stealth_async(page)
        except Exception:
            # Safe fallback if stealth data files are missing or incompatible
            async def apply_stealth(page):
                pass
except ImportError:
    print("\n[ERROR] Missing dependencies. Install them with:")
    print("  pip install -r requirements.txt")
    print("  python -m playwright install chromium\n")
    sys.exit(1)

from config import ANSWERS_URL, TEST_URL, C_RESET, C_GREEN, C_YELLOW, C_CYAN, C_BOLD, C_DIM
from ui import clear_screen, print_banner, Spinner, log_info, log_error, log_step, print_phase_header
from browser import is_port_open, launch_browser_with_debug
from api import (
    intercept_response,
    fetch_api_answers,
    find_quiz_id,
    is_valid_quiz_id,
    extract_quiz_id_from_url,
    resolve_pin_to_quiz_id,
    retrieve_answers,
    fetch_answers_by_any_identifier,
    set_allow_quizit_bot,
)
from scraper import scrape_answers
from automation import automate_test, scrape_results, _read_question_counter
from tabs import get_live_pages, pick_tab
from matching import get_display_questions


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
    parser.add_argument(
        "-q", "--quiz-input",
        type=str,
        default=None,
        help="Quiz URL or game PIN code to use for answer extraction."
    )
    parser.add_argument(
        "--no-bot",
        action="store_true",
        default=False,
        help="Do not use Quizit solver bot (prevents bot player from entering lobby)."
    )
    args = parser.parse_args()

    if args.no_bot:
        set_allow_quizit_bot(False)

    print_banner()

    # Interactive setup if no arguments were provided
    if len(sys.argv) == 1:
        print(f"{C_CYAN}Interactive Setup{C_RESET}")
        print(f"{C_DIM}{'─'*60}{C_RESET}")
        
        print(f"  {C_BOLD}Select Mode:{C_RESET}")
        print(f"  {C_CYAN}1{C_RESET}) Attach to your Edge/Chrome ({C_GREEN}Recommended! Keeps browser open if console closes, preserves logins{C_RESET})")
        print(f"  {C_CYAN}2{C_RESET}) Open new standalone browser")
        
        mode = await asyncio.get_event_loop().run_in_executor(
            None, input, "  Enter choice [default: 1]: "
        )
        # Default to Mode 1 (Attach) for maximum persistence and login retention
        args.attach = (mode.strip() != '2')
        
        print()
        print(f"  {C_BOLD}Quiz URL or game code:{C_RESET}")
        print(f"  {C_DIM}Example: https://wayground.com/join?gc=XXXXXX or XXXXXX{C_RESET}")
        quiz_input_raw = await asyncio.get_event_loop().run_in_executor(
            None, input, f"  Enter URL or code (or press Enter to skip): "
        )
        args.quiz_input = quiz_input_raw.strip() if quiz_input_raw.strip() else None

        print()
        print(f"  {C_BOLD}Use Quizit Solver Bot for live PINs?{C_RESET}")
        print(f"  {C_DIM}Note: Quizit Bot connects as a guest ('Reconnecting...') to fetch answers.{C_RESET}")
        print(f"  {C_DIM}Select 'n' if teacher is actively watching the lobby.{C_RESET}")
        bot_choice = await asyncio.get_event_loop().run_in_executor(
            None, input, "  Allow Quizit Bot? [Y/n, default: Y]: "
        )
        if bot_choice.strip().lower() == 'n':
            set_allow_quizit_bot(False)
            log_step("Quizit Bot disabled. Will use Direct API / CheatNetwork.")

        print(f"{C_DIM}{'─'*60}{C_RESET}\n")

    # Clear screen before the main work begins
    clear_screen()
    print_banner("Connecting..." if args.attach else "Launching browser...")

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
                # ── Attach network listener for API Data ──
                for ctx in browser.contexts:
                    ctx.on("response", intercept_response)
            except Exception as e:
                log_error(f"Could not connect on port {port}!")
                print(f"  {C_DIM}Error: {e}{C_RESET}")
                print(f"\n  {C_YELLOW}Tip: Close ALL Edge/Chrome windows first, then try again.{C_RESET}\n")
                sys.exit(1)

            # Check for Wayground tab
            all_pages = await get_live_pages(browser)
            has_wayground = any("wayground" in (pg.url.lower() if pg.url else "") for pg in all_pages)

            if not has_wayground:
                log_info("Wayground tab not found. Opening it for you...")
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                
                # Make sure the listener is attached to this context
                try:
                    ctx.on("response", intercept_response)
                except Exception:
                    pass
                
                # Reuse empty/newtab page if available instead of opening a duplicate tab
                page_test = None
                for pg in ctx.pages:
                    u = (pg.url or "").lower().rstrip("/")
                    if u in ("about:blank", "edge://newtab", "chrome://newtab") or not u:
                        page_test = pg
                        break
                if not page_test:
                    page_test = await ctx.new_page()

                await page_test.goto("https://wayground.com", wait_until="domcontentloaded")

                print()
                print(f"{C_YELLOW}{'─'*60}{C_RESET}")
                print(f"{C_BOLD}{C_YELLOW}⏸  LOG IN & NAVIGATE{C_RESET}")
                print(f"{C_YELLOW}{'─'*60}{C_RESET}")
                print(f"  1.   Log in to Wayground in the browser")
                print(f"  2.   Navigate to your test URL")
                print(f"  3.   Come back here and press Enter")
                print(f"{C_YELLOW}{'─'*60}{C_RESET}")
                print()

                await asyncio.get_event_loop().run_in_executor(
                    None, input, "  ▶  Press ENTER when ready..."
                )
                print()

            # Re-fetch pages and let user pick the test tab
            all_pages = await get_live_pages(browser)
            log_info(f"Found {len(all_pages)} open tab(s).")
            page_test = await pick_tab(all_pages, "🎯 TEST (Wayground)", "wayground")
            try:
                page_test.on("response", intercept_response)
            except Exception:
                pass

            print()

            # Run phases
            await _run_phases(page_test, browser, args)

            print()
            log_info("Done! 🎉  (Browser left open — use --attach again for the next test)")

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

            ctx_test = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=UA,
            )
            ctx_test.on("response", intercept_response)
            page_test = await ctx_test.new_page()
            await apply_stealth(page_test)

            # Determine initial test URL based on user input
            target_test_url = args.test_url
            if args.quiz_input:
                inp = args.quiz_input.strip()
                if inp.isdigit():
                    target_test_url = f"https://wayground.com/join?gc={inp}"
                elif "wayground.com" in inp:
                    target_test_url = inp

            log_info(f"Opening: {target_test_url}...")
            await page_test.goto(target_test_url, wait_until="domcontentloaded")

            print()
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print(f"{C_BOLD}{C_YELLOW}⏸  MANUAL LOGIN REQUIRED{C_RESET}")
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print(f"  1.   In the {C_CYAN}Wayground{C_RESET} browser window — log in to your account.")
            print(f"  2.   Navigate to your test URL (if not redirected):")
            print(f"       {C_CYAN}{target_test_url}{C_RESET}")
            print(f"  3.   Once you see the test/waiting screen — come back here.")
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print()

            await asyncio.get_event_loop().run_in_executor(
                None, input, "  ▶  Press ENTER when you are on the test page and ready to start..."
            )
            print()

            await _run_phases(page_test, browser, args)

            print()
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            await asyncio.get_event_loop().run_in_executor(
                None, input, "  ✅  Done! Press ENTER to close the browser..."
            )
            await browser.close()

            log_info("Done! 🎉")


async def _run_phases(page_test, browser, args):
    """Shared logic: fetch answers (API first, CheatNetwork fallback), then automate."""

    # ── Clear screen for Phase 1 ──
    clear_screen()
    print_banner("Working...")
    print_phase_header(1, "Retrieving answer keys")
    
    answers_db = None
    answer_source = "Unknown"
    
    # ── Phase 1: Retrieve Answer Keys via multi-tiered engine ──
    async with Spinner("Retrieving answers (Quizit API / Game PIN / Direct API / Network)..."):
        answers_db, answer_source = await retrieve_answers(
            page_test, quiz_input=args.quiz_input, timeout=6.0
        )

    if answers_db:
        log_info(f"✅ Loaded {len(answers_db)} answers [{answer_source}]")

    # If automatic answer retrieval didn't succeed, offer manual PIN / URL / ID entry
    if not answers_db:
        log_step(f"{C_YELLOW}Could not automatically locate answers.{C_RESET}")
        print(f"  {C_DIM}Enter Game PIN (e.g. 665058), Room Hash, Quiz ID, or URL.{C_RESET}")
        print(f"  {C_DIM}Press ENTER to fall back to CheatNetwork.{C_RESET}")
        try:
            manual_input = await asyncio.get_event_loop().run_in_executor(
                None, input, "  ▶  PIN, Hash, ID or URL (or press ENTER to skip): "
            )
            clean_man = manual_input.strip()
            if clean_man:
                async with Spinner(f"Resolving answers for '{clean_man}'..."):
                    loop = asyncio.get_event_loop()
                    answers_db, answer_source = await loop.run_in_executor(
                        None, fetch_answers_by_any_identifier, clean_man
                    )
                    if answers_db:
                        log_info(f"✅ Loaded {len(answers_db)} answers [{answer_source}]")
                    else:
                        log_error("Could not resolve answers from manual input.")
        except Exception:
            pass

    # ── Lazy CheatNetwork fallback ──
    if not answers_db:
        log_step(f"{C_YELLOW}Falling back to CheatNetwork scraping...{C_RESET}")
        log_info("Opening CheatNetwork in a new tab...")
        
        # Open CheatNetwork page on-demand
        if browser.contexts:
            ctx = browser.contexts[0]
        else:
            ctx = await browser.new_context()
        
        page_answers = await ctx.new_page()
        try:
            await apply_stealth(page_answers)
        except Exception:
            pass  # stealth is nice-to-have, not critical
        # Build quiz input for CheatNetwork form
        # Priority: user-provided URL/code > test page URL
        quiz_input_str = args.quiz_input
        if not quiz_input_str:
            # Try to extract from the current test page URL
            test_url = page_test.url
            if "wayground" in test_url or "quizizz" in test_url:
                quiz_input_str = test_url
        
        target_cn_url = args.answers_url
        if quiz_input_str and "cheatnetwork.eu/services/quizizz/answers" in quiz_input_str:
            target_cn_url = quiz_input_str

        await page_answers.goto(target_cn_url, wait_until="domcontentloaded")
        
        # Attempt 1: Auto-fill the CheatNetwork form
        answers_db = await scrape_answers(page_answers, quiz_input=quiz_input_str)
        
        if answers_db:
            answer_source = "CheatNetwork"
            log_info("Closing CheatNetwork tab...")
            await page_answers.close()
        else:
            # Attempt 2: Let the user manually interact with CheatNetwork
            log_info(f"{C_YELLOW}Auto-scraping failed. Switching to manual mode...{C_RESET}")
            print()
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print(f"{C_BOLD}{C_YELLOW}⏸  MANUAL CHEATNETWORK MODE{C_RESET}")
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print(f"  The CheatNetwork tab is open in the browser.")
            print(f"  1.  Go to the {C_CYAN}CheatNetwork{C_RESET} tab")
            print(f"  2.  Enter your quiz link or game PIN")
            print(f"  3.  Click {C_BOLD}\"Get Answers\"{C_RESET}")
            print(f"  4.  Wait for the answers to appear")
            print(f"  5.  Come back here and press {C_BOLD}Enter{C_RESET}")
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print()
            
            await asyncio.get_event_loop().run_in_executor(
                None, input, "  ▶  Press ENTER when answers are visible on CheatNetwork..."
            )
            print()
            
            # Try scraping again (without auto-fill — user already filled the form)
            answers_db = await scrape_answers(page_answers, quiz_input=None)
            
            if answers_db:
                answer_source = "CheatNetwork (manual)"
            
            log_info("Closing CheatNetwork tab...")
            await page_answers.close()
        
        if not answers_db:
            log_error("Could not retrieve answers from any source.")
            log_error("Please check your quiz link/PIN and try again.")
            sys.exit(1)

    display_questions = get_display_questions(answers_db)
    print(f"\n{C_CYAN}{'#':<4} {'Question':<55} {'Answer(s)':<35}{C_RESET}  {C_DIM}[Source: {answer_source}]{C_RESET}")
    print(f"{C_DIM}{'─'*4} {'─'*55} {'─'*35}{C_RESET}")
    for i, (q, answers_list) in enumerate(display_questions):
        q_short = q[:52] + "..." if len(q) > 52 else q
        if len(answers_list) == 1:
            a_short = answers_list[0][:32] + "..." if len(answers_list[0]) > 32 else answers_list[0]
        else:
            a_short = f"[{len(answers_list)}] " + ", ".join(a[:15] for a in answers_list)
            if len(a_short) > 32:
                a_short = a_short[:29] + "..."
        print(f"{C_DIM}{i+1:<4}{C_RESET} {q_short:<55} {C_GREEN}{a_short:<35}{C_RESET}")
    print()

    # ── Ask how many wrong answers now that we know the real question count ──
    _, page_total = await _read_question_counter(page_test)
    total_questions = page_total if page_total > 0 else len(display_questions)

    wrong_count = args.wrong  # Use CLI value if provided
    if wrong_count == 0:
        print(f"{C_CYAN}{'─'*60}{C_RESET}")
        print(f"  {C_BOLD}Mistakes settings:{C_RESET}")
        print(f"  Total questions in test: {C_BOLD}{total_questions}{C_RESET}")
        print()
        wrong_input = await asyncio.get_event_loop().run_in_executor(
            None, input, f"  How many questions to answer WRONG? (0 for 100%) [default: 0]: "
        )
        if wrong_input.strip().isdigit():
            wrong_count = int(wrong_input.strip())
            if wrong_count >= total_questions and total_questions > 0:
                log_error(f"Cannot answer {wrong_count} wrong out of {total_questions} questions!")
                wrong_count = max(0, total_questions - 1)
                log_info(f"Adjusted to {wrong_count} wrong answers.")
        print(f"{C_CYAN}{'─'*60}{C_RESET}")
        print()

    if wrong_count > 0:
        expected_correct = total_questions - wrong_count
        expected_pct = int(100 * expected_correct / total_questions) if total_questions > 0 else 0
        log_info(f"Target score: ~{expected_correct}/{total_questions} ({expected_pct}%)")

    # ── Phase 2 ──
    print_phase_header(2, "Automating test")
    await automate_test(page_test, answers_db, wrong_count=wrong_count, expected_total=total_questions)

    # ── Phase 3: Scrape results ──
    clear_screen()
    print_banner("Finishing up...")
    print_phase_header(3, "Reading results from Wayground")
    await scrape_results(page_test, timeout=30)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        pass  # sys.exit() calls shouldn't print an extra traceback
    except KeyboardInterrupt:
        print(f"\n{C_RESET}[INFO] Automation stopped by user.")
    except Exception as e:
        log_error(f"Unexpected error: {e}")
    finally:
        # Prevents the console window from instantly closing on fatal errors or when finished
        print()
        input(f"{C_DIM}Press ENTER to exit...{C_RESET}")
