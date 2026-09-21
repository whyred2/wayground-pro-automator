"""
Test automation: highlighting, question answering loop, and results scraping.
Supports text questions, image questions, media options, and robust intermission handling.
"""

import asyncio
import random
import base64
import re

from config import (
    SEL_CURRENT_QUESTION, SEL_CURRENT_QUESTION_INNER, SEL_QUESTION_MEDIA,
    SEL_OPTION_BUTTON, SEL_OPTION_TEXT, SEL_SUBMIT_BUTTON, SEL_CONTINUE_BUTTON, SEL_REDEMPTION_BUTTON,
    SEL_FIB_INPUT,
    SEL_CURRENT_Q_NUM, SEL_TOTAL_Q_NUM,
    SEL_RESULTS_CONTAINER, SEL_STAT_CORRECT, SEL_STAT_INCORRECT, SEL_STAT_AVG_TIME, SEL_STAT_STREAK,
    SEL_ACCURACY_TOOLTIP,
    MIN_THINK_SECONDS, THINK_PER_CHAR, THINK_JITTER, CLICK_DELAY_MS,
    C_RESET, C_GREEN, C_RED, C_YELLOW, C_CYAN, C_BOLD, C_DIM,
    AI_MODEL,
)
from ui import log_info, log_found, log_progress, log_error, log_step, log_wrong
from matching import find_answers, match_button_option, rank_and_match_buttons, get_display_questions
from ai_solver import solve_question_with_ai, solve_fib_with_ai, generate_plausible_wrong

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
except ImportError:
    PlaywrightTimeout = Exception


async def _safe_click(btn, description: str = "") -> bool:
    """Try to click a button; return True on success, False if element is stale/detached."""
    try:
        await btn.click(timeout=3000)
        return True
    except Exception as exc:
        msg = str(exc)
        if "not attached" in msg or "detached" in msg or "stale" in msg:
            label = f" ({description})" if description else ""
            log_step(f"⚠ Element became stale{label} (user clicked first?). Skipping to next question...")
            return False
        # Fallback to JS click if Playwright actionability check times out or overlay intercepts
        try:
            await btn.evaluate("el => el.click()")
            return True
        except Exception:
            return False


# ─── Human-like Thinking Delay ─────────────────────────────────

def calc_think_time(question_text: str) -> float:
    """
    Calculate a realistic "thinking" delay based on question length.
    Longer questions → more time to read and think.
    Returns seconds with random jitter.
    """
    length = len(question_text) if question_text else 25
    base = MIN_THINK_SECONDS + length * THINK_PER_CHAR
    jitter = base * random.uniform(-THINK_JITTER, THINK_JITTER)
    result = base + jitter
    return max(MIN_THINK_SECONDS, round(result, 1))


# ─── Highlighting via page.evaluate() ─────────────────────────

async def highlight_question(page):
    """Add a dashed yellow border to the active question container."""
    try:
        await page.evaluate("""
            () => {
                const el = document.querySelector('[data-highlight-block="stem"]') ||
                           document.querySelector('[data-testid="question-scroll-container"]') ||
                           document.querySelector('[data-quesid]') ||
                           document.querySelector('[data-testid="quiz-container"]') ||
                           document.querySelector('#questionText') ||
                           document.querySelector('[data-cy="question-text"]');
                if (el) {
                    el.style.border = '5px dashed #FFD600';
                    el.style.borderRadius = '8px';
                    el.style.transition = 'border 0.3s ease';
                }
            }
        """)
    except Exception:
        pass


async def highlight_answer(page, button_handle):
    """Add a solid green border to the answer button."""
    try:
        await button_handle.evaluate("""
            (el) => {
                el.style.border = '5px solid #00E676';
                el.style.borderRadius = '8px';
                el.style.transition = 'border 0.3s ease';
                el.style.boxShadow = '0 0 15px rgba(0, 230, 118, 0.5)';
            }
        """)
    except Exception:
        pass


async def clear_highlights(page):
    """Remove all injected highlights."""
    try:
        await page.evaluate("""
            () => {
                document.querySelectorAll('[style*="border"]').forEach(el => {
                    el.style.border = '';
                    el.style.borderRadius = '';
                    el.style.boxShadow = '';
                });
            }
        """)
    except Exception:
        pass


# ─── Rich Button & Question Extraction ─────────────────────────

async def _get_option_buttons(page) -> list:
    """
    Find and return all visible option buttons, deduplicating nested wrapper elements
    (e.g., [data-testid="option-trigger-N"] containing button.option).
    Ensures exactly 1 interactive leaf element per option choice is returned.
    """
    try:
        handles = await page.evaluate_handle("""
            () => {
                const candidates = Array.from(document.querySelectorAll(
                    'button[data-testid^="option-trigger-"], [data-testid^="option-trigger-"], ' +
                    'button.option, .option.is-selectable, button[data-cy^="option-"], [data-cy^="option-"], ' +
                    '.option-container button, div[role="radiogroup"] button, div[role="group"] button, ' +
                    'button[role="radio"], button[role="checkbox"]'
                ));

                // 1. Filter to visible elements only
                const visible = candidates.filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
                });

                // 2. Deduplicate: if an element contains another candidate, prefer the inner interactive leaf
                const leafElements = [];
                for (const el of visible) {
                    const hasChildCandidate = visible.some(other => other !== el && el.contains(other));
                    if (!hasChildCandidate) {
                        leafElements.push(el);
                    }
                }

                return leafElements.length > 0 ? leafElements : visible;
            }
        """)
        length = await page.evaluate("arr => arr.length", handles)
        elements = []
        for i in range(length):
            el = await page.evaluate_handle(f"arr => arr[{i}]", handles)
            element = el.as_element()
            if element:
                elements.append(element)
        return elements
    except Exception:
        return await page.query_selector_all(SEL_OPTION_BUTTON)


async def _extract_button_info(btn, idx: int = -1) -> dict:
    """
    Extract text, image alt, image src, and cy index from an option button.
    Handles buttons where options are pure images with no inner text,
    as well as modern assessment options with radio markers (A/B/C/D).
    """
    try:
        info = await btn.evaluate("""
            (el) => {
                const clone = el.cloneNode(true);

                // 1. Replace KaTeX / MathML with clean LaTeX formula
                clone.querySelectorAll('.katex, [data-testid="math-renderer"], .math-renderer').forEach(k => {
                    const ann = k.querySelector('annotation[encoding*="tex"]');
                    const math = ann ? ann.textContent.trim() : (k.querySelector('.katex-html')?.textContent || k.textContent || '').trim();
                    if (math) {
                        const rep = document.createTextNode(' ' + math + ' ');
                        k.parentNode.replaceChild(rep, k);
                    }
                });

                // 2. Remove radio/checkbox markers (A/B/C/D markers) and visual decorators
                clone.querySelectorAll('[data-testid="radio"], [data-testid="checkbox"], svg, button').forEach(b => b.remove());

                // 3. Priority to option text container inside the clone
                let textEl = clone.querySelector(
                    '[data-highlight-block^="option"], .min-w-0 [data-testid="text-renderer"], [data-testid="text-renderer"], ' +
                    '.option-text-inner, .text-container, #optionText .content-slot p, .content-slot p, .content-slot'
                );
                let rawText = textEl ? (textEl.innerText || textEl.textContent || '') : (clone.innerText || clone.textContent || '');

                const img = el.querySelector('img');
                const alt = img ? (img.getAttribute('alt') || '') : '';
                const src = img ? (img.getAttribute('src') || '') : '';
                const cy = el.getAttribute('data-cy') || '';
                const testId = el.getAttribute('data-testid') || '';
                const mIdx = cy.match(/option-([0-9]+)/) || testId.match(/option-trigger-([0-9]+)/);
                const cyIdx = mIdx ? parseInt(mIdx[1], 10) : null;
                const aria = el.getAttribute('aria-label') || '';
                return { text: (rawText || '').replace(/\\s+/g, ' ').trim(), alt: alt.trim(), src: src.trim(), cyIdx: cyIdx, aria: aria.trim() };
            }
        """)
        return {
            "text": info.get("text", ""),
            "alt": info.get("alt", ""),
            "img_src": info.get("src", ""),
            "cy_index": info.get("cyIdx") if info.get("cyIdx") is not None else idx,
            "aria": info.get("aria", "")
        }
    except Exception:
        try:
            t = (await btn.inner_text()).strip()
            return {"text": t, "alt": "", "img_src": "", "cy_index": idx, "aria": ""}
        except Exception:
            return {"text": "", "alt": "", "img_src": "", "cy_index": idx, "aria": ""}


async def _extract_question_info(page) -> dict:
    """
    Extract question details (qid, text, image URL) from current page DOM.
    Supports classic quizizz, modern assessment shells, LaTeX/KaTeX math, and reading passages.
    """
    try:
        info = await page.evaluate("""
            () => {
                let qid = null;
                const qidEl = document.querySelector('[data-quesid]');
                if (qidEl && qidEl.dataset && qidEl.dataset.quesid) {
                    qid = qidEl.dataset.quesid.trim();
                }

                // Question text
                let text = '';
                const textEl = document.querySelector(
                    '[data-highlight-block="stem"], ' +
                    '[data-testid="read-aloud-container"] [data-testid="text-renderer"], ' +
                    '#questionText .content-slot p, #questionText, [data-cy="question-text"], .question-text-color'
                );
                if (textEl) {
                    const clone = textEl.cloneNode(true);

                    // 1. Replace KaTeX math with its clean LaTeX annotation
                    clone.querySelectorAll('.katex, [data-testid="math-renderer"], .math-renderer').forEach(k => {
                        const ann = k.querySelector('annotation[encoding*="tex"]');
                        const math = ann ? ann.textContent.trim() : (k.querySelector('.katex-html')?.textContent || k.textContent || '').trim();
                        if (math) {
                            const rep = document.createTextNode(' ' + math + ' ');
                            k.parentNode.replaceChild(rep, k);
                        }
                    });

                    // 2. Replace fill-in-the-blank text inputs with ______
                    const blanks = clone.querySelectorAll('input, textarea, [data-testid^="fib-text-blank"], .quizizz-ui-text-input');
                    blanks.forEach(b => {
                        const rep = document.createTextNode(" ______ ");
                        b.parentNode.replaceChild(rep, b);
                    });
                    text = (clone.innerText || clone.textContent || '').replace(/\\s+/g, ' ').trim();
                }

                // 3. Check for reading passage / stimulus container
                const stimulusEl = document.querySelector(
                    '[data-testid="stimulus-container"], .stimulus-container, .passage-container, [data-testid="passage-content"]'
                );
                if (stimulusEl) {
                    const sClone = stimulusEl.cloneNode(true);
                    sClone.querySelectorAll('svg, button, .sr-only').forEach(b => b.remove());
                    const sText = (sClone.innerText || sClone.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (sText && !text.includes(sText.slice(0, 40))) {
                        text = "Passage / Context:\\n" + sText + "\\n\\nQuestion:\\n" + text;
                    }
                }

                // Question image (strictly exclude option buttons, avatars, icons)
                let image = '';
                const candidateImgs = Array.from(document.querySelectorAll(
                    '[data-highlight-block="stem"] img, [data-testid="question-media"] img, ' +
                    '.question-media img, .media-container img, #questionText img, img.resizeable-image'
                ));
                for (const im of candidateImgs) {
                    if (im.closest('[data-testid^="option-trigger-"]') ||
                        im.closest('.option') ||
                        im.closest('[role="radiogroup"]') ||
                        im.closest('[role="group"]')) {
                        continue;
                    }
                    const src = im.getAttribute('src') || '';
                    if (src && !src.includes('avatar') && !src.includes('logo') && !src.includes('icon') && !src.includes('read-aloud')) {
                        image = src;
                        break;
                    }
                }

                return { qid: qid, text: text, image: image };
            }
        """)
        return info or {"qid": None, "text": "", "image": ""}
    except Exception:
        return {"qid": None, "text": "", "image": ""}


async def _wait_for_question_or_end(page, last_key: str = "", max_wait: int = 60) -> tuple[str, any]:
    """
    Polls the page for up to `max_wait` seconds.
    - If option buttons appear for a NEW question: returns ('question', question_info)
    - If results screen appears: returns ('ended', None)
    - If redemption screen appears: returns ('redemption_selected', None)
    - If powerup or continue button appears (and not on active question): clicks it
    Returns ('timeout', None) if nothing appears after max_wait.
    """
    elapsed = 0.0
    step = 0.6
    intermission_logged = False

    while elapsed < max_wait:
        # 1. Check if results screen is visible
        try:
            results_el = await page.query_selector(SEL_RESULTS_CONTAINER)
            if results_el and await results_el.is_visible():
                return ('ended', None)
            cur_url = (page.url or "").lower()
            if any(p in cur_url for p in ("/game-summary", "/results", "/summary", "/report")):
                return ('ended', None)
        except Exception:
            pass

        # 2a. Check if option buttons are present and visible (active question!)
        try:
            buttons = await _get_option_buttons(page)
            if buttons and len(buttons) > 0:
                q_info = await _extract_question_info(page)
                q_text = q_info.get("text", "")
                q_img = q_info.get("image", "")
                q_id = q_info.get("qid", "")
                cur_key = q_id or q_text or q_img

                # If this question is still the old question during page transition, wait!
                if last_key and cur_key == last_key:
                    pass
                else:
                    return ('question', q_info)
        except Exception:
            pass

        # 2b. Check if Fill-in-the-Blank (FIB) text input is present and visible!
        try:
            fib_inputs = await page.query_selector_all(SEL_FIB_INPUT)
            if fib_inputs and len(fib_inputs) > 0:
                first_vis = await fib_inputs[0].is_visible()
                if first_vis:
                    q_info = await _extract_question_info(page)
                    q_text = q_info.get("text", "")
                    q_img = q_info.get("image", "")
                    q_id = q_info.get("qid", "")
                    cur_key = q_id or q_text or q_img

                    if last_key and cur_key == last_key:
                        pass
                    else:
                        return ('question', q_info)
        except Exception:
            pass

        # 3. Check for Redemption Question screen (второй шанс)
        try:
            redemption_btns = await page.query_selector_all(SEL_REDEMPTION_BUTTON)
            if redemption_btns and len(redemption_btns) > 0:
                first_btn = redemption_btns[0]
                if await first_btn.is_visible():
                    log_info("🔥 Redemption Question screen (Второй шанс) detected!")
                    target_card = random.choice(redemption_btns)
                    log_step(f"Selecting redemption card (1 of {len(redemption_btns)})...")
                    await _safe_click(target_card, "redemption question card")
                    await asyncio.sleep(1.5)
                    return ('redemption_selected', None)
        except Exception:
            pass

        # 4. Check for interstitial buttons (Next, Continue, Powerup) ONLY when NOT on an active question!
        try:
            has_question = await page.evaluate("""
                () => {
                    const q = document.querySelector(
                        '[data-highlight-block="stem"], [data-testid="question-scroll-container"], ' +
                        '[data-quesid], [data-testid="quiz-container"], #questionText, [data-cy="question-text"]'
                    );
                    if (q) {
                        const r = q.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    }
                    return false;
                }
            """)
            if not has_question:
                continue_btn = await page.query_selector(SEL_CONTINUE_BUTTON)
                if continue_btn and await continue_btn.is_visible():
                    log_step("Clicking Next / Continue / Powerup button...")
                    await _safe_click(continue_btn, "intermission continue")
                    await asyncio.sleep(0.5)
        except Exception:
            pass

        # 5. Log waiting for leaderboard/streak screen
        if not intermission_logged and elapsed > 2.5:
            log_step("⏳ Intermission (leaderboard, streak, or animation) — waiting for next question...")
            intermission_logged = True

        await asyncio.sleep(step)
        elapsed += step

    # Final check for results after timeout
    try:
        results_el = await page.query_selector(SEL_RESULTS_CONTAINER)
        if results_el:
            return ('ended', None)
    except Exception:
        pass

    return ('timeout', None)


async def _read_question_counter(page) -> tuple[int, int]:
    """
    Read the current/total question numbers from the Wayground test page.
    Supports classic data-cy spans and modern assessment counters ('Питання 1 з 50', 'Вопрос 1 из 50', etc.).
    Returns (current, total). Returns (0, 0) if not found.
    """
    try:
        res = await page.evaluate("""
            () => {
                // 1. Classic data-cy spans
                const curEl = document.querySelector('span[data-cy="current-question-number"]');
                const totEl = document.querySelector('span[data-cy="total-question-number"]');
                if (curEl && totEl) {
                    const c = parseInt(curEl.innerText.trim(), 10);
                    const t = parseInt(totEl.innerText.trim(), 10);
                    if (!isNaN(c) && !isNaN(t) && t > 0) return [c, t];
                }

                // 2. Modern footer / text counters: "Питання 1 з 50", "Вопрос 1 из 50", "Question 1 of 50", "1 / 50"
                const elements = Array.from(document.querySelectorAll('footer, div, span, p')).filter(el => {
                    return el.children.length === 0 && /(?:питання|вопрос|question)?\\s*\\b(\\d+)\\s*(?:з|из|of|\\/)\\s*(\\d+)\\b/i.test(el.innerText || '');
                });
                for (const el of elements) {
                    const m = (el.innerText || '').match(/(?:питання|вопрос|question)?\\s*\\b(\\d+)\\s*(?:з|из|of|\\/)\\s*(\\d+)\\b/i);
                    if (m) {
                        const c = parseInt(m[1], 10);
                        const t = parseInt(m[2], 10);
                        if (!isNaN(c) && !isNaN(t) && t > 0) return [c, t];
                    }
                }
                return [0, 0];
            }
        """)
        if res and isinstance(res, list) and len(res) == 2:
            return res[0], res[1]
    except Exception:
        pass
    return 0, 0


async def _advance_if_next_button(page) -> bool:
    """
    In modern assessment/test mode (and certain quiz shells), choosing an answer option
    only selects the radio button or checkbox. A 'Next' / 'Submit' button ('Далі', 'Submit', etc.)
    must be clicked to actually submit the answer and transition to the next question.
    """
    try:
        btn_handle = await page.evaluate_handle("""
            () => {
                const candidates = Array.from(document.querySelectorAll(
                    'button[data-testid="next-button"], button[data-cy="next-button"], ' +
                    'button[data-testid="submit-button"], button[data-cy="submit-button"], ' +
                    'button[data-testid="navigation-next-button"], button.submit-btn, ' +
                    'button.next-button, button'
                ));

                for (const b of candidates) {
                    // Ignore option triggers and radio/checkboxes
                    if (b.closest('[data-testid^="option-trigger-"]') ||
                        b.closest('.option') ||
                        b.closest('[role="radiogroup"]') ||
                        b.closest('[role="group"]') ||
                        b.closest('.selectors-container') ||
                        b.closest('.screen-redemption-question-selector')) {
                        continue;
                    }

                    // Must be visible
                    const rect = b.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0 ||
                        window.getComputedStyle(b).visibility === 'hidden' ||
                        window.getComputedStyle(b).display === 'none') {
                        continue;
                    }

                    const text = (b.innerText || '').trim();
                    const aria = (b.getAttribute('aria-label') || '').trim();
                    const testId = (b.getAttribute('data-testid') || '').toLowerCase();
                    const cy = (b.getAttribute('data-cy') || '').toLowerCase();

                    // Match Next / Submit / Finish in UK, RU, EN
                    const isNextOrSubmit = (
                        /(?:^|\\s)(?:далі|далее|next|submit|отправить|надіслати|завершити|завершить|finish|continue|підтвердити|подтвердить)\\b/i.test(text) ||
                        /(?:^|\\s)(?:далі|далее|next|submit|finish)\\b/i.test(aria) ||
                        testId.includes('next') || testId.includes('submit') || testId.includes('finish') ||
                        cy.includes('next') || cy.includes('submit')
                    );

                    // Ensure it's not a 'Back' / 'Previous' / 'Назад' button
                    const isBack = /(?:назад|back|prev|previous)/i.test(text) ||
                                   /(?:назад|back|prev)/i.test(aria) ||
                                   testId.includes('prev') || testId.includes('back');

                    if (isNextOrSubmit && !isBack) {
                        return b;
                    }
                }
                return null;
            }
        """)
        if btn_handle:
            el = btn_handle.as_element()
            if el and await el.is_visible():
                btn_txt = (await el.inner_text()).strip().replace('\\n', ' ')
                log_step(f"Clicking Next / Submit: \\\"{btn_txt or 'Далі'}\\\"...")
                clicked = await _safe_click(el, "next/submit navigation")
                return clicked
    except Exception:
        pass
    return False


async def _wait_for_transition(page, old_text: str = "", old_image: str = "", old_q_num: int = 0, timeout: float = 6.0) -> bool:
    """
    After submitting an answer, wait for the page to finish transitioning
    away from the answered question so that we don't accidentally read
    the old question text or old buttons.
    """
    elapsed = 0.0
    step = 0.2
    while elapsed < timeout:
        await asyncio.sleep(step)
        elapsed += step

        # 1. Results page appeared?
        try:
            results_el = await page.query_selector(SEL_RESULTS_CONTAINER)
            if results_el and await results_el.is_visible():
                return True
            cur_url = (page.url or "").lower()
            if any(p in cur_url for p in ("/game-summary", "/results", "/summary", "/report")):
                return True
        except Exception:
            pass

        # 2. Check if redemption question appeared
        try:
            r_btns = await page.query_selector_all(SEL_REDEMPTION_BUTTON)
            if r_btns and len(r_btns) > 0 and await r_btns[0].is_visible():
                return True
        except Exception:
            pass

        # 3. Check if question info has changed to a NEW question
        try:
            cur_info = await _extract_question_info(page)
            cur_text = cur_info.get("text", "")
            cur_img = cur_info.get("image", "")

            # If question text has changed to a non-empty new question
            if cur_text and old_text and cur_text != old_text:
                await asyncio.sleep(0.3)  # Allow DOM to render new option buttons completely
                return True

            # If image changed
            if cur_img and old_image and cur_img != old_image:
                await asyncio.sleep(0.3)
                return True

            # If classic mode transitioned into intermission (neither option buttons nor FIB inputs visible)
            btns = await page.query_selector_all(SEL_OPTION_BUTTON)
            fibs = await page.query_selector_all(SEL_FIB_INPUT)
            has_btn = bool(btns and await btns[0].is_visible())
            has_fib = bool(fibs and await fibs[0].is_visible())
            if not has_btn and not has_fib:
                return True
        except Exception:
            pass

    return False


# ─── Main Automation Loop ─────────────────────────────────────

async def automate_test(
    test_page,
    answers_db: dict[str, list[str]],
    wrong_count: int = 0,
    expected_total: int | None = None,
    use_ai: bool = True,
    ai_only: bool = False,
):
    """
    Main loop: detect question on test page, match with DB or solve via AI Solver, click answer.
    Supports single-answer, multi-select (MSQ), image questions, and media options.
    wrong_count: how many questions to answer INCORRECTLY on purpose.
    expected_total: total number of real questions in test (excluding lookup aliases).
    use_ai: whether to use AI as a fallback or primary solver.
    ai_only: if True, solve 100% of questions with AI without DB lookups.
    """
    answered = 0
    correct = 0
    wrong = 0

    # Determine real question count
    _, page_total = await _read_question_counter(test_page)
    if page_total > 0:
        total = page_total
    elif expected_total and expected_total > 0:
        total = expected_total
    else:
        disp = get_display_questions(answers_db) if answers_db else []
        total = len(disp) if disp else (len(answers_db) if answers_db else 0)

    if wrong_count >= total and total > 0:
        log_error(f"You requested {wrong_count} wrong answers, but the test only has {total} questions!")
        wrong_count = max(0, total - 1)
        log_info(f"Adjusted to {wrong_count} wrong answers.")

    _wrong_indices_initialized = False
    if wrong_count > 0 and total > 0:
        wrong_indices = set(random.sample(range(1, total + 1), wrong_count))
        log_info(f"🎲 Will deliberately answer {wrong_count} questions wrong (Q: {sorted(list(wrong_indices))})")
    else:
        wrong_indices = set()
        if wrong_count == 0:
            _wrong_indices_initialized = True

    if ai_only or not answers_db:
        total_label = f"{total} questions detected" if total > 0 else "question count will be read dynamically"
        log_info(f"🤖 Starting AI Solver ({AI_MODEL}) — {total_label}.")
    else:
        log_info(f"Starting automation: {total} questions in test ({len(answers_db)} lookup keys loaded).")
    if wrong_count > 0 and total > 0:
        expected_correct = total - wrong_count
        expected_pct = int(100 * expected_correct / total) if total > 0 else 0
        log_info(f"Target score: ~{expected_correct}/{total} ({expected_pct}%)")
    log_info("Waiting for the first question to appear...")

    last_question_key = ""

    while True:
        # Wait for the next question or game over screen (passes last_question_key to guarantee novelty!)
        status, q_info = await _wait_for_question_or_end(test_page, last_key=last_question_key, max_wait=60)
        if status == 'ended':
            log_info("✅ Test completion detected (results screen visible).")
            break
        elif status == 'timeout':
            log_info("⚠ No question or results detected after 60s of waiting. Proceeding to results.")
            break
        elif status == 'redemption_selected':
            last_question_key = ""  # Reset debounce so repeated redemption question is answered!
            await asyncio.sleep(0.5)
            continue

        qid = q_info.get("qid")
        question_text = q_info.get("text", "")
        question_image = q_info.get("image", "")

        # ── Read live counter from page early for tracking & stats ──
        page_current, page_total = await _read_question_counter(test_page)
        if page_total > 0 and page_total != total:
            total = page_total
            if wrong_count > 0:
                invalid_wrong = [w for w in wrong_indices if w > total]
                if invalid_wrong:
                    wrong_indices = {w for w in wrong_indices if w <= total}
                    curr_q = page_current or (answered + 1)
                    pool = [i for i in range(curr_q, total + 1) if i not in wrong_indices]
                    needed = len(invalid_wrong)
                    if pool and needed > 0:
                        wrong_indices.update(random.sample(pool, min(needed, len(pool))))
                    log_info(f"🎲 Corrected total to {total}: re-scheduled wrong questions to {sorted(list(wrong_indices))}")
        elif page_total > 0:
            total = page_total

        current_key = qid or question_text or question_image
        if not current_key or current_key == last_question_key:
            await asyncio.sleep(0.5)
            continue

        last_question_key = current_key
        answered += 1
        display_num = page_current if page_current > 0 else answered

        # ── "Thinking" delay — human-like ──
        think_time = calc_think_time(question_text)
        display_q = f"Q: \"{question_text[:40]}...\"" if question_text else f"Q [Image/Media {qid or 'ID'}]:"
        log_progress(display_num, total, display_q)
        log_step(f"⏱ Thinking for {think_time}s...")
        await asyncio.sleep(think_time)

        # ── Re-verify live question info right before matching to ensure zero desync ──
        fresh_q_info = await _extract_question_info(test_page)
        if fresh_q_info.get("text"):
            question_text = fresh_q_info["text"]
        if fresh_q_info.get("image"):
            question_image = fresh_q_info["image"]
        if fresh_q_info.get("qid"):
            qid = fresh_q_info["qid"]

        # ── Lazy re-computation of wrong_indices when resuming mid-test or in AI mode ──
        if not _wrong_indices_initialized:
            _wrong_indices_initialized = True
            if wrong_count > 0 and total > 0:
                cur_start = page_current if page_current > 0 else 1
                remaining = total - cur_start + 1
                actual_wrong = min(wrong_count, remaining)
                wrong_indices = set(random.sample(
                    range(cur_start, cur_start + remaining), actual_wrong
                ))
                log_info(f"🎲 Initialized {actual_wrong} wrong questions: {sorted(list(wrong_indices))} from total {total}")

        deliberate_wrong = display_num in wrong_indices

        # ── Find correct answer(s) from DB ──
        correct_answers = []
        if not ai_only and answers_db:
            found = find_answers(
                question=question_text,
                answers_db=answers_db,
                qid=qid,
                image_url=question_image
            )
            if found:
                correct_answers = found

        # ── Detect MSQ mode ──
        has_radio = await test_page.query_selector(
            '[role="radiogroup"], [role="radio"], [data-testid="radio"], input[type="radio"], .option.is-radio'
        ) is not None

        has_checkbox = await test_page.query_selector(
            "button.option.is-msq, .option.is-msq, [data-testid='checkbox'], input[type='checkbox'], [role='checkbox']"
        ) is not None

        msq_text_hints = any(h in question_text.lower() for h in [
            "select all", "choose all", "all that apply", "all correct", "select two", "select three",
            "choose two", "choose three", "выберите все", "выберите несколько", "выберите два",
            "выберите три", "отметьте все", "which of the following are"
        ]) if question_text else False

        is_msq = (
            len(correct_answers) > 1
            or ((has_checkbox or msq_text_hints) and not has_radio)
        )

        # ── Detect question type: Fill-in-the-Blank (FIB) vs Option Buttons ──
        fib_inputs = await test_page.query_selector_all(SEL_FIB_INPUT)
        visible_fib = []
        if fib_inputs:
            for fi in fib_inputs:
                try:
                    if await fi.is_visible():
                        visible_fib.append(fi)
                except Exception:
                    pass

        # ─────────────────────────────────────────────────
        # Fill-in-the-Blank (FIB) / Text Input Question
        # ─────────────────────────────────────────────────
        if visible_fib:
            log_info(f"✏️  Fill-in-the-blank detected ({len(visible_fib)} blank(s))")
            await highlight_question(test_page)

            for fi in visible_fib:
                await highlight_answer(test_page, fi)

            answers_to_fill = []
            ai_fib_wrongs = []
            if correct_answers:
                answers_to_fill = list(correct_answers[:len(visible_fib)])

            # If no DB answer found (or AI mode) and AI is enabled
            if not answers_to_fill and use_ai:
                ai_source_note = "AI mode active" if (ai_only or not answers_db) else "No DB match"
                log_step(f"🤖 {ai_source_note} — querying AI Solver ({AI_MODEL}) for missing term(s)...")

                image_b64 = None
                if question_image:
                    try:
                        img_el = await test_page.query_selector(SEL_QUESTION_MEDIA) or await test_page.query_selector("img.resizeable-image")
                        if img_el and await img_el.is_visible():
                            buf = await img_el.screenshot()
                            image_b64 = base64.b64encode(buf).decode("utf-8")
                    except Exception:
                        pass
                if not image_b64 and not question_text:
                    try:
                        stem_el = await test_page.query_selector(SEL_CURRENT_QUESTION)
                        if stem_el and await stem_el.is_visible():
                            buf = await stem_el.screenshot()
                            image_b64 = base64.b64encode(buf).decode("utf-8")
                    except Exception:
                        pass

                loop = asyncio.get_event_loop()
                ai_fib_answers, ai_fib_wrongs, reasoning = await loop.run_in_executor(
                    None,
                    solve_fib_with_ai,
                    question_text,
                    len(visible_fib),
                    image_b64
                )
                if ai_fib_answers:
                    answers_to_fill = ai_fib_answers
                    reason_short = f" ({reasoning[:70]}...)" if len(reasoning) > 70 else (f" ({reasoning})" if reasoning else "")
                    log_found(f"💡 AI Solver predicted: {answers_to_fill}{reason_short}")

            # Fallback if still empty
            if not answers_to_fill:
                log_step(f"{C_YELLOW}[SKIP] No DB answer or AI prediction for blank — guessing 'yes'{C_RESET}")
                answers_to_fill = ["yes"] * len(visible_fib)

            # Handle deliberate wrong with realistic human-like mistakes
            if deliberate_wrong:
                wrong += 1
                log_wrong(f"Q{answered}: Deliberately entering realistic WRONG answer for FIB! ({wrong}/{wrong_count})")
                plausible_list = []
                for idx, ans in enumerate(answers_to_fill):
                    if idx < len(ai_fib_wrongs) and ai_fib_wrongs[idx] and ai_fib_wrongs[idx].strip().lower() != ans.strip().lower():
                        plausible_list.append(ai_fib_wrongs[idx].strip())
                    else:
                        plausible_list.append(generate_plausible_wrong(ans))
                answers_to_fill = plausible_list
            else:
                correct += 1
                ans_disp = ", ".join(f'"{a}"' for a in answers_to_fill)
                log_found(f"{display_q} -> A: [{ans_disp}]")

            # Fill each blank
            for i, fi in enumerate(visible_fib):
                ans_val = answers_to_fill[i] if i < len(answers_to_fill) else answers_to_fill[0]
                log_step(f"  Typing into blank [{i+1}/{len(visible_fib)}]: \"{ans_val}\"")
                try:
                    await fi.scroll_into_view_if_needed()
                    await fi.click()
                    await asyncio.sleep(0.1)
                    await fi.fill(ans_val)
                    await fi.evaluate("""(el, val) => {
                        el.value = val;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""", ans_val)
                    await asyncio.sleep(0.2)
                except Exception as ex:
                    log_error(f"Failed to fill input: {ex}")

            # Advance / Submit
            await asyncio.sleep(0.4)
            advanced = await _advance_if_next_button(test_page)
            if not advanced and visible_fib:
                try:
                    await visible_fib[-1].press("Enter")
                    await asyncio.sleep(0.5)
                    advanced = await _advance_if_next_button(test_page)
                except Exception:
                    pass

            if not advanced:
                submit_btn = await test_page.query_selector(SEL_SUBMIT_BUTTON)
                if submit_btn and await submit_btn.is_visible():
                    log_step("Clicking Submit...")
                    await _safe_click(submit_btn, "FIB submit")

            await asyncio.sleep(CLICK_DELAY_MS / 1000)
            await clear_highlights(test_page)
            await _wait_for_transition(
                test_page,
                old_text=question_text,
                old_image=question_image,
                old_q_num=page_current or answered
            )
            continue

        # ── Get all option buttons with rich info and ranked precision matching ──
        buttons = await _get_option_buttons(test_page)
        correct_buttons = []
        wrong_buttons = []
        buttons_info = []

        if buttons:
            for i, btn in enumerate(buttons):
                b_info = await _extract_button_info(btn, idx=i)
                buttons_info.append(b_info)

        if correct_answers and buttons_info:
            c_indices, w_indices = rank_and_match_buttons(buttons_info, correct_answers, is_msq=is_msq)
            for ci in c_indices:
                b_info = buttons_info[ci]
                label = b_info.get("text") or b_info.get("alt") or f"Option {ci+1}"
                correct_buttons.append((buttons[ci], label))

            for wi in w_indices:
                b_info = buttons_info[wi]
                label = b_info.get("text") or b_info.get("alt") or f"Option {wi+1}"
                wrong_buttons.append((buttons[wi], label))

        # ── AI Solver: If no DB match (or pure AI mode) and AI is enabled ──
        if not correct_buttons and use_ai and buttons_info:
            ai_source_note = "AI mode active" if (ai_only or not answers_db) else "No DB match"
            log_step(f"🤖 {ai_source_note} — querying AI Solver ({AI_MODEL})...")

            # Try to grab question image/diagram if present for multimodal analysis
            image_b64 = None
            if question_image:
                try:
                    img_el = await test_page.query_selector(SEL_QUESTION_MEDIA) or await test_page.query_selector("img.resizeable-image")
                    if img_el and await img_el.is_visible():
                        buf = await img_el.screenshot()
                        image_b64 = base64.b64encode(buf).decode("utf-8")
                except Exception:
                    pass

            # If options are images or lack text, screenshot the container to let vision AI see options
            has_visual_options = any(not b.get("text") and (b.get("img_src") or b.get("alt")) for b in buttons_info) or all(not b.get("text") for b in buttons_info)
            if has_visual_options or (not image_b64 and not question_text):
                try:
                    container_el = await test_page.query_selector(
                        '[data-testid="question-scroll-container"], .screen-container, [data-testid="quiz-container"]'
                    )
                    if container_el and await container_el.is_visible():
                        buf = await container_el.screenshot()
                        image_b64 = base64.b64encode(buf).decode("utf-8")
                except Exception:
                    pass

            if not image_b64 and not question_text:
                try:
                    stem_el = await test_page.query_selector(SEL_CURRENT_QUESTION)
                    if stem_el and await stem_el.is_visible():
                        buf = await stem_el.screenshot()
                        image_b64 = base64.b64encode(buf).decode("utf-8")
                except Exception:
                    pass

            loop = asyncio.get_event_loop()
            ai_indices, reasoning = await loop.run_in_executor(
                None,
                solve_question_with_ai,
                question_text,
                buttons_info,
                is_msq,
                image_b64
            )

            if ai_indices:
                # If radio buttons exist in DOM, strictly enforce single choice even if AI model returned multiple
                if has_radio and len(ai_indices) > 1:
                    log_step(f"⚠️ Radio group detected but AI returned multiple ({ai_indices}) — selecting top choice [{ai_indices[0]}]")
                    ai_indices = ai_indices[:1]

                for idx in ai_indices:
                    if 0 <= idx < len(buttons):
                        b_info = buttons_info[idx]
                        label = b_info.get("text") or b_info.get("alt") or f"Option {idx+1}"
                        correct_buttons.append((buttons[idx], label))

                for i in range(len(buttons)):
                    if i not in ai_indices:
                        b_info = buttons_info[i]
                        label = b_info.get("text") or b_info.get("alt") or f"Option {i+1}"
                        wrong_buttons.append((buttons[i], label))

                chosen_labels = ", ".join(f'"{lbl}"' for _, lbl in correct_buttons)
                reason_short = f" ({reasoning[:70]}...)" if len(reasoning) > 70 else (f" ({reasoning})" if reasoning else "")
                log_found(f"💡 AI Solver selected: {chosen_labels}{reason_short}")
                correct_answers = [lbl for _, lbl in correct_buttons]

                # Update is_msq state based on AI's actual selection and DOM radio constraints
                if len(correct_buttons) > 1 and not has_radio:
                    is_msq = True
                elif len(correct_buttons) <= 1:
                    is_msq = False

        # Fallback if neither DB nor AI found a match
        if not correct_buttons:
            log_step(f"{C_YELLOW}[SKIP] No match from DB or AI — guessing randomly{C_RESET}")
            if buttons:
                random_idx = random.randint(0, len(buttons) - 1)
                random_btn = buttons[random_idx]
                r_info = await _extract_button_info(random_btn, idx=random_idx)
                r_label = r_info.get("text") or r_info.get("alt") or f"Option {random_idx+1}"
                log_step(f"Guessing: \"{r_label}\"")
                await highlight_answer(test_page, random_btn)
                await asyncio.sleep(0.4)
                if not await _safe_click(random_btn, "random guess"):
                    continue
                await asyncio.sleep(0.4)
                await _advance_if_next_button(test_page)
                await asyncio.sleep(CLICK_DELAY_MS / 1000)
                await clear_highlights(test_page)
                await _wait_for_transition(test_page, old_text=question_text, old_image=question_image, old_q_num=page_current or answered)
            continue

        # ─────────────────────────────────────────────────
        # MSQ: Multi-Select Question
        # ─────────────────────────────────────────────────
        if is_msq:
            log_info(f"📋 MSQ detected — {len(correct_answers)} correct answer(s)")

            if deliberate_wrong:
                wrong += 1
                log_wrong(f"Q{answered}: Deliberately picking WRONG for MSQ! ({wrong}/{wrong_count})")
                targets = []
                if wrong_buttons:
                    targets.append(random.choice(wrong_buttons))
                if len(correct_buttons) > 1:
                    targets.extend(correct_buttons[:len(correct_buttons) - 1])
            else:
                correct += 1
                targets = correct_buttons
                ans_str = ", ".join(f'"{a}"' for a in correct_answers)
                log_found(f"{display_q} -> A: [{ans_str}]")

            for i, (btn, btn_text) in enumerate(targets):
                await highlight_answer(test_page, btn)
                await asyncio.sleep(random.uniform(0.4, 0.8))
                log_step(f"  Selecting [{i+1}/{len(targets)}]: \"{btn_text}\"")
                if not await _safe_click(btn, f"MSQ option '{btn_text}'"):
                    break
                await asyncio.sleep(random.uniform(0.3, 0.6))
            else:
                await asyncio.sleep(random.uniform(0.5, 1.0))
                # Check for Next / Submit button
                advanced = await _advance_if_next_button(test_page)
                if not advanced:
                    submit_btn = await test_page.query_selector(SEL_SUBMIT_BUTTON)
                    if submit_btn:
                        log_step("Clicking Submit (Отправить)...")
                        if not await _safe_click(submit_btn, "MSQ submit"):
                            continue
                    else:
                        log_error("Submit button not found!")
                        await test_page.screenshot(path="error_debug.png")
                        continue

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
                log_found(f"{display_q} -> A: \"{correct_answers[0]}\"")

            await highlight_answer(test_page, target_btn)
            await asyncio.sleep(0.8)

            log_step(f"Clicking: \"{target_text}\"")
            if not await _safe_click(target_btn, f"answer '{target_text}'"):
                continue

            # In assessment / test mode (or whenever a Next / Submit button is required to advance):
            await asyncio.sleep(0.4)
            await _advance_if_next_button(test_page)

        # Post-click delay
        await asyncio.sleep(CLICK_DELAY_MS / 1000)

        # Clear highlights
        await clear_highlights(test_page)

        # Wait for page to finish transitioning to the next question (prevents 1-question phase shift!)
        await _wait_for_transition(
            test_page,
            old_text=question_text,
            old_image=question_image,
            old_q_num=page_current or answered
        )

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
    Supports both modern assessment mode summary and classic game summary.
    Prints accuracy, points, correct/incorrect, avg time, and streak.
    """
    log_info("Waiting for results page to load...")

    try:
        await test_page.wait_for_selector(
            SEL_RESULTS_CONTAINER,
            timeout=timeout * 1000
        )
    except PlaywrightTimeout:
        log_step("Results page did not appear within timeout. Skipping.")
        return

    # Settle animations and tooltips
    await asyncio.sleep(1.5)

    stats = await test_page.evaluate("""
        () => {
            const data = {
                accuracy: "",
                score: "",
                total_questions: "",
                correct: "",
                incorrect: "",
                ungraded: "",
                avg_time: "",
                streak: "",
            };

            // 1. Modern Assessment Mode Summary
            const summary = document.querySelector('[data-cy="screen-summary"], .screen-summary, .assessment-mode-summary');
            if (summary) {
                const allElements = Array.from(summary.querySelectorAll('span, div, p'));

                // Accuracy (% badge or bar width)
                for (const el of allElements) {
                    const txt = (el.innerText || el.textContent || '').trim();
                    if (/^\\d+(\\.\\d+)?\\s*%$/.test(txt) && !data.accuracy) {
                        data.accuracy = txt;
                        break;
                    }
                }
                if (!data.accuracy) {
                    const bar = summary.querySelector('.bg-ads-success-400');
                    if (bar && bar.style && bar.style.width) {
                        data.accuracy = bar.style.width;
                    }
                }

                // Score / Points (tooltip or fraction text)
                const tooltipContent = summary.querySelector('.show-tooltip .content, .tooltip .content, .content.apply-shadow');
                if (tooltipContent) {
                    data.score = (tooltipContent.innerText || tooltipContent.textContent || '').trim();
                } else {
                    for (const el of allElements) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (/^\d+(\.\d+)?\s*\/\s*\d+/.test(txt)) {
                            data.score = txt;
                            break;
                        }
                    }
                }

                // Total questions (e.g. "30 питання", "30 questions", "30 вопросов")
                for (const el of allElements) {
                    const txt = (el.innerText || el.textContent || '').trim();
                    const m = txt.match(/^(\d+)\s*(?:питання|питань|запитання|запитань|вопрос|question)/i);
                    if (m) {
                        data.total_questions = parseInt(m[1], 10);
                        break;
                    }
                }
                if (!data.total_questions && data.score) {
                    const mTot = data.score.match(/\/\s*(\d+)/);
                    if (mTot) data.total_questions = parseInt(mTot[1], 10);
                }

                // Badges: Correct, Incorrect, Avg Time
                for (const el of allElements) {
                    const txt = (el.innerText || el.textContent || '').trim();
                    // Correct
                    const mCorr = txt.match(/^(\d+)\s*(?:правильн|correct|верн)/i);
                    if (mCorr && !data.correct) {
                        data.correct = parseInt(mCorr[1], 10);
                    }
                    // Incorrect
                    const mIncorr = txt.match(/^(\d+)\s*(?:неправильн|incorrect|неверн)/i);
                    if (mIncorr && !data.incorrect) {
                        data.incorrect = parseInt(mIncorr[1], 10);
                    }
                    // Ungraded
                    const mUngraded = txt.match(/^(\d+)\s*(?:ungraded|без оцінки|не оцен|не оцін)/i);
                    if (mUngraded && !data.ungraded) {
                        data.ungraded = parseInt(mUngraded[1], 10);
                    }
                    // Avg time
                    const mTime = txt.match(/(\d+(?:\.\d+)?\s*(?:s|сек|sec|m|мин))\s*(?:на запитання|\/питання|\/вопрос|\/question|час\/питання|время\/вопрос|time\/question|avg time)?/i);
                    if (mTime && !data.avg_time && (txt.toLowerCase().includes('час') || txt.toLowerCase().includes('time') || txt.toLowerCase().includes('время'))) {
                        data.avg_time = mTime[1].trim();
                    }
                }
            }

            // 2. Classic Game Summary (fallback / augmentation)
            const classicCorrect = document.querySelector('div[data-cy="stat-correct-container"] span, [data-testid="stat-correct"]');
            if (classicCorrect && !data.correct) data.correct = (classicCorrect.innerText || classicCorrect.textContent || '').trim();

            const classicIncorrect = document.querySelector('div[data-cy="stat-incorrect-container"] span, [data-testid="stat-incorrect"]');
            if (classicIncorrect && !data.incorrect) data.incorrect = (classicIncorrect.innerText || classicIncorrect.textContent || '').trim();

            const classicAvgTime = document.querySelector('div[data-cy="stat-avg-time-container"] span, [data-testid="stat-time"]');
            if (classicAvgTime && !data.avg_time) data.avg_time = (classicAvgTime.innerText || classicAvgTime.textContent || '').trim();

            const classicStreak = document.querySelector('div[data-cy="stat-streak-container"] span, [data-testid="stat-streak"]');
            if (classicStreak && !data.streak) data.streak = (classicStreak.innerText || classicStreak.textContent || '').trim();

            const classicTooltip = document.querySelector('.accuracy-chart-wrapper .show-tooltip .content span, .accuracy-chart-wrapper');
            if (classicTooltip && !data.score && !data.accuracy) {
                const t = (classicTooltip.innerText || classicTooltip.textContent || '').trim();
                if (t.includes('%')) data.accuracy = t;
                else data.score = t;
            }

            return data;
        }
    """)

    # Fallback to individual selectors if evaluate didn't find them
    if not stats.get("correct"):
        try:
            el = await test_page.query_selector(SEL_STAT_CORRECT)
            if el:
                stats["correct"] = (await el.inner_text()).strip()
        except Exception:
            pass
    if not stats.get("incorrect"):
        try:
            el = await test_page.query_selector(SEL_STAT_INCORRECT)
            if el:
                stats["incorrect"] = (await el.inner_text()).strip()
        except Exception:
            pass
    if not stats.get("avg_time"):
        try:
            el = await test_page.query_selector(SEL_STAT_AVG_TIME)
            if el:
                stats["avg_time"] = (await el.inner_text()).strip()
        except Exception:
            pass
    if not stats.get("streak"):
        try:
            el = await test_page.query_selector(SEL_STAT_STREAK)
            if el:
                stats["streak"] = (await el.inner_text()).strip()
        except Exception:
            pass
    if not stats.get("accuracy"):
        try:
            el = await test_page.query_selector(SEL_ACCURACY_TOOLTIP)
            if el:
                txt = (await el.inner_text()).strip()
                if "%" in txt:
                    stats["accuracy"] = txt
                else:
                    stats["score"] = txt
        except Exception:
            pass

    accuracy = stats.get("accuracy", "")
    score = stats.get("score", "")
    total_qs = stats.get("total_questions", "")
    correct = stats.get("correct", "")
    incorrect = stats.get("incorrect", "")
    ungraded = stats.get("ungraded", "")
    avg_time = stats.get("avg_time", "")
    streak = stats.get("streak", "")

    has_any = any([accuracy, score, total_qs, correct, incorrect, ungraded, avg_time, streak])

    print()
    print(f"{C_CYAN}{'═'*60}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}  📊  RESULTS FROM WAYGROUND{C_RESET}")
    print(f"{C_CYAN}{'═'*60}{C_RESET}")

    if has_any:
        if accuracy:
            acc_num = int(re.sub(r'[^0-9]', '', accuracy) or 0)
            acc_color = C_GREEN if acc_num >= 80 else (C_YELLOW if acc_num >= 50 else C_RED)
            print(f"  {C_BOLD}Точність (Accuracy):{C_RESET}     {acc_color}{accuracy}{C_RESET}")
        if score:
            print(f"  {C_BOLD}Бали (Points/Score):{C_RESET}     {C_CYAN}{score}{C_RESET}")
        if total_qs:
            print(f"  {C_BOLD}Всього питань (Total):{C_RESET}   {total_qs}")
        if correct:
            print(f"  {C_GREEN}Правильно (Correct):{C_RESET}     {C_GREEN}{correct}{C_RESET}")
        if incorrect:
            print(f"  {C_RED}Неправильно (Wrong):{C_RESET}     {C_RED}{incorrect}{C_RESET}")
        if ungraded:
            print(f"  {C_CYAN}Ungraded (Без оцінки):{C_RESET}   {ungraded}")
        if avg_time:
            print(f"  {C_CYAN}Час/питання (Time):{C_RESET}      {avg_time}")
        if streak:
            print(f"  {C_YELLOW}Серія (Streak):{C_RESET}          {streak}")
    else:
        log_step("Summary screen reached, but detailed stat badges could not be parsed.")

    print(f"{C_CYAN}{'═'*60}{C_RESET}\n")
    return stats
