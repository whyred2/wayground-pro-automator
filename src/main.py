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

from config import ANSWERS_URL, TEST_URL, C_RESET, C_GREEN, C_YELLOW, C_CYAN, C_BOLD, C_DIM
from ui import clear_screen, print_banner, Spinner, log_info, log_error, log_step, print_phase_header
from browser import is_port_open, launch_browser_with_debug
from api import intercept_response, fetch_api_answers, _quiz_id_event, _captured_quiz_id
from scraper import scrape_answers
from automation import automate_test, scrape_results, _read_question_counter
from tabs import get_live_pages, pick_tab


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

    print_banner()

    # Interactive setup if no arguments were provided
    if len(sys.argv) == 1:
        print(f"{C_CYAN}Interactive Setup{C_RESET}")
        print(f"{C_DIM}{'─'*60}{C_RESET}")
        
        print(f"  {C_BOLD}Select Mode:{C_RESET}")
        print(f"  {C_CYAN}1{C_RESET}) Open new standalone browser (Recommended!)")
        print(f"  {C_CYAN}2{C_RESET}) Attach to your Edge/Chrome (keeps logins)")
        
        mode = await asyncio.get_event_loop().run_in_executor(
            None, input, "  Enter choice [default: 1]: "
        )
        args.attach = (mode.strip() == '2')
            
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

            log_info("Opening Wayground login page...")
            await page_test.goto("https://wayground.com", wait_until="domcontentloaded")

            print()
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print(f"{C_BOLD}{C_YELLOW}⏸  MANUAL LOGIN REQUIRED{C_RESET}")
            print(f"{C_YELLOW}{'─'*60}{C_RESET}")
            print(f"  1.   In the {C_CYAN}Wayground{C_RESET} browser window — log in to your account.")
            print(f"  2.   Navigate to your test URL:")
            print(f"       {C_CYAN}{args.test_url}{C_RESET}")
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
    
    # Check if we intercepted the quiz ID via network or if we can extract it right now
    if not _quiz_id_event.is_set():
        # Try DOM extraction as a quick fallback
        try:
            quiz_id_eval = await page_test.evaluate("""
                () => {
                    if (window.quizId) return window.quizId;
                    const html = document.documentElement.innerHTML;
                    const idx = html.indexOf('"quizInfo"');
                    if (idx !== -1) {
                        const sub = html.substring(idx, idx + 2000);
                        const m = sub.match(/"_id"\\s*:\\s*"([a-fA-F0-9]{24})"/);
                        if (m) return m[1];
                    }
                    return null;
                }
            """)
            if quiz_id_eval:
                log_info(f"✅ Extracted quiz_id from page DOM: {quiz_id_eval}")
                import api
                api._captured_quiz_id = quiz_id_eval
                _quiz_id_event.set()
        except Exception:
            pass

    # Wait up to 5 seconds for the network interceptor
    if not _quiz_id_event.is_set():
        async with Spinner("Waiting for quiz data from network..."):
            try:
                await asyncio.wait_for(_quiz_id_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    # Re-import to get the potentially updated value
    from api import _captured_quiz_id as quiz_id

    if quiz_id:
        log_info(f"Quiz ID: {quiz_id}")
        async with Spinner("Fetching answers via Direct API..."):
            try:
                answers_db = await asyncio.get_event_loop().run_in_executor(
                    None, fetch_api_answers, quiz_id
                )
                answer_source = "Direct API"
            except Exception as e:
                log_error(f"Direct API failed: {e}")
                answers_db = None
        if answers_db:
            log_info(f"✅ Loaded {len(answers_db)} answers from API")

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
        await page_answers.goto(args.answers_url, wait_until="domcontentloaded")
        
        answers_db = await scrape_answers(page_answers)
        answer_source = "CheatNetwork"
        
        # Close the CheatNetwork tab — no longer needed
        log_info("Closing CheatNetwork tab...")
        await page_answers.close()

    print(f"\n{C_CYAN}{'#':<4} {'Question':<55} {'Answer(s)':<35}{C_RESET}  {C_DIM}[Source: {answer_source}]{C_RESET}")
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

    # ── Ask how many wrong answers now that we know the total ──
    _, page_total = await _read_question_counter(page_test)
    total_questions = page_total if page_total > 0 else len(answers_db)

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
    await automate_test(page_test, answers_db, wrong_count=wrong_count)

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
