"""
Test automation: highlighting, question answering loop, and results scraping.
Supports text questions, image questions, media options, and robust intermission handling.
"""

import asyncio
import random

from config import (
    SEL_CURRENT_QUESTION, SEL_CURRENT_QUESTION_INNER, SEL_QUESTION_MEDIA,
    SEL_OPTION_BUTTON, SEL_OPTION_TEXT, SEL_SUBMIT_BUTTON, SEL_CONTINUE_BUTTON, SEL_REDEMPTION_BUTTON,
    SEL_CURRENT_Q_NUM, SEL_TOTAL_Q_NUM,
    SEL_RESULTS_CONTAINER, SEL_STAT_CORRECT, SEL_STAT_INCORRECT, SEL_STAT_AVG_TIME, SEL_STAT_STREAK,
    SEL_ACCURACY_TOOLTIP,
    MIN_THINK_SECONDS, THINK_PER_CHAR, THINK_JITTER, CLICK_DELAY_MS,
    C_RESET, C_GREEN, C_RED, C_YELLOW, C_CYAN, C_BOLD, C_DIM,
)
from ui import log_info, log_found, log_progress, log_error, log_step, log_wrong
from matching import find_answers, match_button_option, rank_and_match_buttons, get_display_questions

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

async def _extract_button_info(btn, idx: int = -1) -> dict:
    """
    Extract text, image alt, image src, and cy index from an option button.
    Handles buttons where options are pure images with no inner text,
    as well as modern assessment options with radio markers (A/B/C/D).
    """
    try:
        info = await btn.evaluate("""
            (el) => {
                // Priority to option text container, avoiding radio letter indicator (A/B/C/D)
                let textEl = el.querySelector(
                    '[data-highlight-block^="option"], .min-w-0 [data-testid="text-renderer"], ' +
                    '.option-text-inner, .text-container, #optionText .content-slot p, .content-slot p, .content-slot'
                );
                if (!textEl) {
                    const ps = Array.from(el.querySelectorAll('p, span')).filter(p => !p.closest('[data-testid="radio"]') && !p.classList.contains('sr-only'));
                    if (ps.length > 0) textEl = ps[0];
                }
                const rawText = textEl ? textEl.innerText : el.innerText;
                const img = el.querySelector('img');
                const alt = img ? (img.getAttribute('alt') || '') : '';
                const src = img ? (img.getAttribute('src') || '') : '';
                const cy = el.getAttribute('data-cy') || '';
                const testId = el.getAttribute('data-testid') || '';
                const mIdx = cy.match(/option-(\\\\d+)/) || testId.match(/option-trigger-(\\\\d+)/);
                const cyIdx = mIdx ? parseInt(mIdx[1], 10) : null;
                const aria = el.getAttribute('aria-label') || '';
                return { text: (rawText || '').trim(), alt: alt.trim(), src: src.trim(), cyIdx: cyIdx, aria: aria.trim() };
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
    Supports classic quizizz and modern assessment shells.
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
                    text = (textEl.innerText || '').trim();
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

        # 2. Check if option buttons are present and visible (active question!)
        try:
            buttons = await page.query_selector_all(SEL_OPTION_BUTTON)
            if buttons and len(buttons) > 0:
                first_vis = await buttons[0].is_visible()
                if first_vis:
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

            # If classic mode transitioned into intermission (no option buttons visible)
            btns = await page.query_selector_all(SEL_OPTION_BUTTON)
            if not btns or not await btns[0].is_visible():
                return True
        except Exception:
            pass

    return False


# ─── Main Automation Loop ─────────────────────────────────────

async def automate_test(
    test_page,
    answers_db: dict[str, list[str]],
    wrong_count: int = 0,
    expected_total: int | None = None
):
    """
    Main loop: detect question on test page, match with DB, click answer.
    Supports single-answer, multi-select (MSQ), image questions, and media options.
    wrong_count: how many questions to answer INCORRECTLY on purpose.
    expected_total: total number of real questions in test (excluding lookup aliases).
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
        disp = get_display_questions(answers_db)
        total = len(disp) if disp else len(answers_db)

    if wrong_count >= total and total > 0:
        log_error(f"You requested {wrong_count} wrong answers, but the test only has {total} questions!")
        wrong_count = max(0, total - 1)
        log_info(f"Adjusted to {wrong_count} wrong answers.")

    _wrong_indices_initialized = False
    if wrong_count > 0:
        wrong_indices = set(random.sample(range(1, total + 1), wrong_count))
        log_info(f"🎲 Will deliberately answer {wrong_count} questions wrong (Q: {sorted(list(wrong_indices))})")
    else:
        wrong_indices = set()
        _wrong_indices_initialized = True

    log_info(f"Starting automation: {total} questions in test ({len(answers_db)} lookup keys loaded).")
    if wrong_count > 0:
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

        # ── Lazy re-computation of wrong_indices when resuming mid-test ──
        if not _wrong_indices_initialized:
            _wrong_indices_initialized = True
            if page_current > 1 and wrong_count > 0:
                remaining = total - page_current + 1
                actual_wrong = min(wrong_count, remaining)
                wrong_indices = set(random.sample(
                    range(page_current, page_current + remaining), actual_wrong
                ))
                log_info(f"🎲 Resumed at Q{page_current}: re-sampled {actual_wrong} wrong from remaining {remaining} questions")

        deliberate_wrong = display_num in wrong_indices

        # ── Find correct answer(s) from DB ──
        correct_answers = find_answers(
            question=question_text,
            answers_db=answers_db,
            qid=qid,
            image_url=question_image
        )

        # ── Detect MSQ mode ──
        is_msq = (
            len(correct_answers) > 1
            or await test_page.query_selector(
                "button.option.is-msq, .option.is-msq, [data-testid='checkbox'], input[type='checkbox'], div[role='group']"
            ) is not None
        )

        # ── Highlight question ──
        await highlight_question(test_page)

        # ── Get all option buttons with rich info and ranked precision matching ──
        buttons = await test_page.query_selector_all(SEL_OPTION_BUTTON)
        correct_buttons = []
        wrong_buttons = []

        if correct_answers and buttons:
            buttons_info = []
            for i, btn in enumerate(buttons):
                b_info = await _extract_button_info(btn, idx=i)
                buttons_info.append(b_info)

            c_indices, w_indices = rank_and_match_buttons(buttons_info, correct_answers, is_msq=is_msq)
            for ci in c_indices:
                b_info = buttons_info[ci]
                label = b_info.get("text") or b_info.get("alt") or f"Option {ci+1}"
                correct_buttons.append((buttons[ci], label))

            for wi in w_indices:
                b_info = buttons_info[wi]
                label = b_info.get("text") or b_info.get("alt") or f"Option {wi+1}"
                wrong_buttons.append((buttons[wi], label))

        # Fallback if no match found
        if not correct_buttons:
            log_step(f"{C_YELLOW}[SKIP] No match for question/options — guessing randomly{C_RESET}")
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

    await asyncio.sleep(2)

    results = {}
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

    accuracy_text = ""
    try:
        el = await test_page.query_selector(SEL_ACCURACY_TOOLTIP)
        if el:
            accuracy_text = (await el.inner_text()).strip()
    except Exception:
        pass

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
