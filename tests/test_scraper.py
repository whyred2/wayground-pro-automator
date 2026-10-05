"""Regression checks for existing tabs and CheatNetwork's modal transitions."""

import contextlib
import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import answer_tabs
import scraper
import tabs
import main as app


KEYS = {"Question?": ["Correct"]}
INPUT = "https://wayground.com/join?gc=55508525"


def page(url="https://cheatnetwork.eu/services/quizizz"):
    return SimpleNamespace(url=url, is_closed=Mock(return_value=False),
                           title=AsyncMock(return_value="Answers"), goto=AsyncMock(), close=AsyncMock(),
                           wait_for_load_state=AsyncMock(), evaluate=AsyncMock(),
                           query_selector_all=AsyncMock(return_value=[object()]))


class Clock:
    value = 0.0

    def now(self):
        return self.value

    async def sleep(self, seconds):
        self.value += seconds


class CapturedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)


class ScraperTests(CapturedTests):
    async def scrape_sequence(self, states, *, quiz_input=INPUT, login_reply="", wait=120, download=300):
        target = page()
        clock = Clock()
        sequence = iter(states)
        last_state = states[-1]

        async def state(_):
            return {"status": next(sequence, last_state), "questions": 1 if last_state == "ready" else 0}

        with patch.object(scraper, "read_cheatnetwork_state", side_effect=state), \
                patch.object(scraper, "_fill_and_submit", new=AsyncMock(return_value=True)) as submit, \
                patch.object(scraper, "_parse_question_boxes", new=AsyncMock(return_value=KEYS)), \
                patch.object(scraper, "monotonic", side_effect=clock.now), \
                patch.object(scraper.asyncio, "sleep", new=clock.sleep), \
                patch("builtins.input", return_value=login_reply) as prompt:
            result = await scraper.scrape_answers(target, quiz_input, wait_timeout=wait, download_timeout=download)
        return result, target, submit, prompt, clock.value

    async def test_existing_answers_are_read_without_navigation_or_submission(self):
        result, target, submit, prompt, _ = await self.scrape_sequence(["ready"])
        self.assertEqual(result, KEYS)
        submit.assert_not_awaited()
        target.goto.assert_not_awaited()
        prompt.assert_not_called()

    async def test_download_dialog_is_waited_out_without_resubmitting(self):
        result, target, submit, prompt, elapsed = await self.scrape_sequence(
            ["form", "form"] + ["downloading"] * 90 + ["ready"], wait=10, download=120)
        self.assertEqual(result, KEYS)
        self.assertGreater(elapsed, 40)
        submit.assert_awaited_once()
        target.goto.assert_not_awaited()
        prompt.assert_not_called()

    async def test_transient_login_notice_can_change_to_downloading(self):
        result, target, submit, prompt, _ = await self.scrape_sequence(
            ["form", "form", "login", "login", "downloading", "downloading", "ready"])
        self.assertEqual(result, KEYS)
        submit.assert_awaited_once()
        prompt.assert_not_called()
        target.goto.assert_not_awaited()

    async def test_download_seen_before_render_does_not_resubmit_when_dialog_disappears(self):
        result, target, submit, _, _ = await self.scrape_sequence(["downloading", "form", "ready"])
        self.assertEqual(result, KEYS)
        submit.assert_not_awaited()
        target.goto.assert_not_awaited()

    async def test_persistent_login_pauses_then_reads_download_without_new_request(self):
        result, target, submit, prompt, _ = await self.scrape_sequence(
            ["form", "form"] + ["login"] * 7 + ["downloading", "ready"])
        self.assertEqual(result, KEYS)
        prompt.assert_called_once()
        submit.assert_awaited_once()
        target.goto.assert_not_awaited()

    async def test_retry_requires_explicit_login_completion_and_a_visible_form(self):
        result, target, submit, prompt, _ = await self.scrape_sequence(
            ["form", "form"] + ["login"] * 7 + ["form", "downloading", "ready"])
        self.assertEqual(result, KEYS)
        self.assertEqual(submit.await_count, 2)
        prompt.assert_called_once()
        target.goto.assert_not_awaited()

    async def test_download_timeout_keeps_page_and_does_not_retry(self):
        result, target, submit, _, _ = await self.scrape_sequence(
            ["form", "form", "downloading"], wait=1, download=2)
        self.assertIsNone(result)
        submit.assert_awaited_once()
        target.goto.assert_not_awaited()
        target.close.assert_not_awaited()

    async def test_closed_page_returns_none_without_playwright_error(self):
        target = page()
        target.wait_for_load_state.side_effect = RuntimeError("Target page, context or browser has been closed")
        self.assertIsNone(await scraper.scrape_answers(target, INPUT))

    async def test_manual_read_does_not_submit_a_form(self):
        result, target, submit, _, _ = await self.scrape_sequence(["form"], quiz_input=None, wait=1)
        self.assertIsNone(result)
        submit.assert_not_awaited()
        target.goto.assert_not_awaited()


class DialogDomTests(CapturedTests):
    async def inspect(self, fixture):
        # Execute the production DOM inspection against controlled visible/hidden
        # elements. No browser, network or third-party account is used here.
        program = """
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function element(data) {
  return {innerText:data.text || '', visibility:data.visibility || 'visible',
    getClientRects:() => data.visible === false ? [] : [{}],
    querySelectorAll:() => (data.answers || []).map(text => element({text}))};
}
const document = {querySelectorAll: selector => {
  if (selector.includes('role=')) return (input.fixture.dialogs || []).map(element);
  if (selector.includes('question-box')) return (input.fixture.boxes || []).map(element);
  return (input.fixture.inputs || []).map(element);
}};
const location = {pathname:input.fixture.path || '/services/quizizz'};
const getComputedStyle = el => ({visibility:el.visibility});
process.stdout.write(JSON.stringify(eval('(' + input.code + ')')()));
"""

        async def evaluate(code):
            completed = await asyncio.to_thread(
                subprocess.run, ["node", "-e", program], input=json.dumps({"code": code, "fixture": fixture}),
                capture_output=True, text=True, check=True, timeout=5)
            return json.loads(completed.stdout)

        target = page()
        target.evaluate.side_effect = evaluate
        return await scraper.read_cheatnetwork_state(target)

    async def test_hidden_login_dialog_does_not_hide_ready_answers(self):
        state = await self.inspect({"dialogs": [{"text": "Not logged in", "visible": False}],
                                    "boxes": [{"answers": ["Correct"]}]})
        self.assertEqual(state["status"], "ready")

    async def test_download_takes_precedence_over_login_and_partial_answers(self):
        state = await self.inspect({"dialogs": [{"text": "Not logged in"}, {"text": "Downloading answers..."}],
                                    "boxes": [{"answers": ["Partial answer"]}]})
        self.assertEqual(state["status"], "downloading")

    async def test_empty_or_hidden_question_boxes_are_not_ready(self):
        state = await self.inspect({"boxes": [{"answers": []}, {"answers": ["hidden"], "visible": False}],
                                    "inputs": [{}]})
        self.assertEqual(state["status"], "form")


class AnswerTabTests(CapturedTests):
    async def test_ready_tabs_are_discovered_across_all_browser_contexts(self):
        ready, form, unrelated = page(), page(), page("https://wayground.com/join?gc=55508525")
        browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[unrelated, form]), SimpleNamespace(pages=[ready])])
        with patch.object(answer_tabs, "read_cheatnetwork_state", new=AsyncMock(side_effect=[
            {"status": "form"}, {"status": "ready"}
        ])), patch.object(answer_tabs, "pick_tab", new=AsyncMock(return_value=ready)) as select:
            self.assertIs(await answer_tabs.select_existing_answer_tab(browser, ready_only=True), ready)
        self.assertEqual(select.call_args.args[0], [ready])
        self.assertTrue(select.call_args.kwargs["allow_skip"])

    async def test_existing_answer_tab_is_not_navigated_or_closed(self):
        existing = page("https://cheatnetwork.eu/services/quizizz/answers#quiz")
        browser = SimpleNamespace(is_connected=Mock(return_value=True))
        context = SimpleNamespace(new_page=AsyncMock())
        with patch.object(answer_tabs, "select_existing_answer_tab", new=AsyncMock(return_value=existing)), \
                patch.object(answer_tabs, "scrape_answers", new=AsyncMock(return_value=KEYS)):
            self.assertEqual((await answer_tabs.retrieve_cheatnetwork_answers(browser, context, INPUT, "unused"))[0], KEYS)
        existing.goto.assert_not_awaited()
        existing.close.assert_not_awaited()
        context.new_page.assert_not_awaited()

    async def test_only_owned_temporary_tab_is_closed_after_success(self):
        temporary = page()
        browser = SimpleNamespace(is_connected=Mock(return_value=True))
        context = SimpleNamespace(new_page=AsyncMock(return_value=temporary))
        with patch.object(answer_tabs, "select_existing_answer_tab", new=AsyncMock(return_value=None)), \
                patch.object(answer_tabs, "scrape_answers", new=AsyncMock(return_value=KEYS)):
            self.assertEqual((await answer_tabs.retrieve_cheatnetwork_answers(browser, context, INPUT, temporary.url))[0], KEYS)
        temporary.close.assert_awaited_once()

    async def test_answer_tab_closed_during_manual_wait_can_be_reselected(self):
        original, replacement = page(), page()
        browser = SimpleNamespace(is_connected=Mock(return_value=True))
        context = SimpleNamespace(new_page=AsyncMock())

        def close_during_prompt(_):
            original.is_closed.return_value = True
            return ""

        with patch.object(answer_tabs, "select_existing_answer_tab", new=AsyncMock(side_effect=[original, replacement])), \
                patch.object(answer_tabs, "scrape_answers", new=AsyncMock(side_effect=[None, KEYS])) as scrape, \
                patch("builtins.input", side_effect=close_during_prompt):
            self.assertEqual((await answer_tabs.retrieve_cheatnetwork_answers(browser, context, INPUT, "unused"))[0], KEYS)
        self.assertIs(scrape.call_args_list[-1].args[0], replacement)
        replacement.close.assert_not_awaited()
        context.new_page.assert_not_awaited()

    async def test_closed_browser_stops_without_prompting_or_creating_new_tab(self):
        existing = page()
        browser = SimpleNamespace(is_connected=Mock(return_value=False))
        context = SimpleNamespace(new_page=AsyncMock())
        with patch.object(answer_tabs, "scrape_answers", new=AsyncMock(return_value=None)), \
                patch("builtins.input") as prompt:
            self.assertIsNone((await answer_tabs.retrieve_cheatnetwork_answers(
                browser, context, INPUT, "unused", preferred_page=existing))[0])
        prompt.assert_not_called()
        context.new_page.assert_not_awaited()

    async def test_optional_tab_selection_can_continue_automatic_lookup(self):
        with patch("builtins.input", return_value="0"):
            self.assertIsNone(await tabs.pick_tab([page()], "ANSWERS", "", allow_skip=True))


class MainFlowTests(CapturedTests):
    async def run_phases(self, existing, direct_keys=KEYS, *, connected=True,
                         existing_keys=KEYS, automation_result=None):
        test_page = page("https://wayground.com/join?gc=55508525")
        browser = SimpleNamespace(is_connected=Mock(return_value=connected))
        args = SimpleNamespace(ai=False, no_ai=True, wrong=1, quiz_input=INPUT,
                               answers_url="https://cheatnetwork.eu/services/quizizz")
        with patch.object(app, "configure_ai", new=AsyncMock(return_value=True)) as configure, \
                patch.object(app, "select_existing_answer_tab", new=AsyncMock(return_value=existing)) as select, \
                patch.object(app, "scrape_answers", new=AsyncMock(return_value=existing_keys)) as scrape, \
                patch.object(app, "retrieve_answers", new=AsyncMock(return_value=(direct_keys, "Direct API"))) as direct, \
                patch.object(app, "_read_question_counter", new=AsyncMock(return_value=(1, 3))), \
                patch.object(app, "automate_test", new=AsyncMock(return_value=automation_result)) as automate, \
                patch.object(app, "scrape_results", new=AsyncMock()) as results, \
                patch.object(app, "clear_screen"), patch.object(app, "print_banner"):
            result = await app._run_phases(test_page, browser, args)
        return result, configure, scrape, direct, automate, results, select

    async def test_old_business_writing_tab_cannot_override_technical_writing_api_keys(self):
        existing = page("https://cheatnetwork.eu/services/quizizz/answers#quiz")
        technical_keys = {"id:technical-question": ["Provide sources"]}
        old_keys = {"The heading includes...": ["Your Address and Date"]}
        _, _, scrape, direct, automate, _, select = await self.run_phases(
            existing, direct_keys=technical_keys, existing_keys=old_keys)
        direct.assert_awaited_once()
        select.assert_not_awaited()
        scrape.assert_not_awaited()
        self.assertEqual(automate.call_args.args[1], technical_keys)
        self.assertNotIn("The heading includes...", automate.call_args.args[1])
        existing.close.assert_not_awaited()

    async def test_existing_tab_is_offered_when_target_api_keys_are_unavailable(self):
        existing = page("https://cheatnetwork.eu/services/quizizz/answers#quiz")
        _, _, scrape, direct, automate, _, select = await self.run_phases(existing, direct_keys=None)
        direct.assert_awaited_once()
        select.assert_awaited_once()
        scrape.assert_awaited_once_with(existing, quiz_input=None)
        self.assertEqual(automate.call_args.args[1], KEYS)
        existing.goto.assert_not_awaited()
        existing.close.assert_not_awaited()

    async def test_skipping_existing_answers_continues_direct_api(self):
        _, _, scrape, direct, automate, _, _ = await self.run_phases(None)
        scrape.assert_not_awaited()
        direct.assert_awaited_once()
        self.assertEqual(automate.call_args.args[1], KEYS)

    async def test_closed_browser_stops_before_any_answer_work(self):
        result, configure, scrape, direct, automate, _, _ = await self.run_phases(None, connected=False)
        self.assertIs(result, False)
        configure.assert_not_awaited()
        scrape.assert_not_awaited()
        direct.assert_not_awaited()
        automate.assert_not_awaited()

    async def test_missing_answer_stop_is_propagated_without_reading_results(self):
        result, _, _, _, automate, results, _ = await self.run_phases(None, automation_result=False)
        self.assertIs(result, False)
        automate.assert_awaited_once()
        results.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
