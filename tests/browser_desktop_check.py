"""Explicit offline browser integration checks: python tests/browser_desktop_check.py.

Uses a fresh headless Edge process and local fixture HTML, never a live game.
"""

import asyncio
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playwright.async_api import async_playwright
from answer_db import AnswerDatabase
from automation import automate_test, highlight_answer, clear_highlights
from runtime_control import RuntimeControl, RunStopped
from desktop_backend import DesktopBackend
from session_binding import SessionBinding
import config
import re


MCQ = r"""<!doctype html><style>button{padding:15px;margin:8px}</style>
<span data-cy="current-question-number">1</span> / <span data-cy="total-question-number">2</span>
<main id="game"><div data-quesid="q1" id="questionText">Which is correct?</div>
<button class="option" onclick="choose('A')"><p>A</p></button>
<button class="option" onclick="choose('B')"><p>B</p></button></main>
<script>window.submissions=[];let n=1;
function choose(answer){submissions.push(answer);n++;
if(n==2){document.querySelector('[data-cy="current-question-number"]').textContent='2';
document.getElementById('game').innerHTML='<div data-quesid="q2" id="questionText">Which is correct?</div><button class="option" onclick="choose(\'C\')"><p>C</p></button><button class="option" onclick="choose(\'D\')"><p>D</p></button>';
}else{document.getElementById('game').innerHTML='<div data-cy="screen-summary">Completed</div>';}}
</script>"""

OPEN = """<!doctype html><span data-cy="current-question-number">1</span>
<span data-cy="total-question-number">1</span><main id="game">
<div data-quesid="open" id="questionText">Write your own response.</div>
<textarea data-testid="open-ended-input"></textarea><button onclick="send()">Submit</button></main>
<script>window.submissions=[];function send(){submissions.push(document.querySelector('textarea').value);
document.getElementById('game').innerHTML='<div data-cy="screen-summary">Completed</div>';}</script>"""


class BrowserIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(channel="msedge", headless=True)
        self.page = await self.browser.new_page()
        self.events = []
        self.control = RuntimeControl(self.events.append, delay=0, highlight=True)
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()

    async def asyncTearDown(self):
        self.stdout.__exit__(None, None, None)
        await self.browser.close()
        await self.playwright.stop()

    def keys(self):
        keys = AnswerDatabase()
        keys.add_question("Which is correct?", ["A"], qid="q1", options=[{"text": "A"}, {"text": "B"}])
        keys.add_question("Which is correct?", ["D"], qid="q2", options=[{"text": "C"}, {"text": "D"}])
        return keys

    async def until(self, kind):
        async with asyncio.timeout(15):
            while not any(event["type"] == kind for event in self.events):
                await asyncio.sleep(0.03)

    async def test_repeated_stems_submit_distinct_keys_in_real_dom(self):
        await self.page.set_content(MCQ)
        complete = await asyncio.wait_for(automate_test(self.page, self.keys(), expected_total=2,
                                          use_ai=False, control=self.control), 15)
        self.assertTrue(complete)
        self.assertEqual(await self.page.evaluate("submissions"), ["A", "D"])
        self.assertEqual(sum(e["type"] == "submitted" for e in self.events), 2)

    async def test_pause_and_stop_leave_current_question_unsubmitted(self):
        await self.page.set_content(MCQ)
        self.control.delay = 60
        task = asyncio.create_task(automate_test(self.page, self.keys(), expected_total=2,
                                   use_ai=False, control=self.control))
        await self.until("answer")
        self.control.pause(True)
        await asyncio.sleep(0.2)
        self.assertEqual(await self.page.evaluate("submissions"), [])
        self.control.stop()
        with self.assertRaises(RunStopped):
            await task
        self.assertEqual(await self.page.evaluate("submissions"), [])

    async def test_answer_now_advances_once_then_remains_paused(self):
        await self.page.set_content(MCQ)
        self.control.delay = 60
        task = asyncio.create_task(automate_test(self.page, self.keys(), expected_total=2,
                                   use_ai=False, control=self.control))
        await self.until("answer")
        self.control.pause(True)
        self.control.answer_now()
        await self.until("submitted")
        await asyncio.sleep(0.2)
        self.assertEqual(await self.page.evaluate("submissions"), ["A"])
        self.assertTrue(self.control.paused)
        self.control.stop()
        with self.assertRaises(RunStopped):
            await task

    async def test_open_response_waits_for_user_and_continues(self):
        await self.page.set_content(OPEN)
        keys = AnswerDatabase()
        keys.add_question("Write your own response.", [], qid="open", manual_required=True)
        task = asyncio.create_task(automate_test(self.page, keys, expected_total=1,
                                   use_ai=False, control=self.control))
        await self.until("manual")
        self.assertEqual(await self.page.locator("textarea").input_value(), "")
        self.assertEqual(await self.page.evaluate("submissions"), [])
        await self.page.locator("textarea").fill("My own written response.")
        await self.page.get_by_role("button", name="Submit").click()
        self.assertTrue(await asyncio.wait_for(task, 5))
        self.assertEqual(await self.page.evaluate("submissions"), ["My own written response."])

    async def test_highlight_restores_existing_styles_and_leaves_other_elements(self):
        await self.page.set_content('<button id="answer" style="border:2px solid red;box-shadow:1px 2px 3px blue">A</button><div id="other" style="border:3px dotted green">Other</div>')
        handle = await self.page.query_selector("#answer")
        before = await handle.evaluate("el=>[el.style.border,el.style.boxShadow]")
        await highlight_answer(self.page, handle)
        self.assertTrue(await handle.evaluate("el=>el.hasAttribute('data-wg-highlight')"))
        await clear_highlights(self.page)
        self.assertEqual(await handle.evaluate("el=>[el.style.border,el.style.boxShadow]"), before)
        self.assertEqual(await self.page.locator("#other").evaluate("el=>el.style.border"), "3px dotted green")

    async def test_preparation_and_bound_backend_run_use_selected_game(self):
        await self.page.route("**/*", lambda route: route.fulfill(status=200, body=MCQ, content_type="text/html"))
        await self.page.goto("https://wayground.com/join?gc=12345678")
        backend = DesktopBackend(self.events.append)
        backend.loop.close()
        backend.loop = asyncio.get_running_loop()
        backend.browser = self.browser
        backend.pages["tab"] = self.page
        questions = [
            {"_id": qid, "type": "MCQ", "structure": {"query": {"text": "Which is correct?"}, "options": [{"text": value} for value in options]}}
            for qid, options in [("q1", ("A", "B")), ("q2", ("C", "D"))]
        ]
        snapshot = {"name": "Fixture game", "pin": "12345678", "hash": "roomhashvalue", "questions": questions}
        with patch("desktop_backend.api.fetch_game_snapshot", return_value=snapshot), \
             patch("desktop_backend.api.fetch_game_answers", return_value=self.keys()):
            await backend._prepare("tab", mode="keys", cheatnetwork=False)
        self.assertTrue(backend.prepared.ready)
        await backend._start_run(delay=0, wrong_limit=0, highlight=False)
        await asyncio.wait_for(backend.run_task, 15)
        self.assertEqual(await self.page.evaluate("submissions"), ["A", "D"])
        self.assertTrue(any(e["type"] == "finished" and e["complete"] for e in self.events))

    async def test_ai_only_can_start_active_test_without_pin_manifest_or_total(self):
        # A resumed game can expose only its current question, with no PIN or
        # total yet. The AI path must solve from the selected page itself.
        fixture = re.sub(r'<span data-cy="(?:current|total)-question-number">.*?</span>', '', MCQ)
        fixture = fixture.replace("document.querySelector('[data-cy=\"current-question-number\"]').textContent='2';", "")
        await self.page.route("**/*", lambda route: route.fulfill(status=200, body=fixture, content_type="text/html"))
        await self.page.goto("https://wayground.com/join/game/live-fixture")
        backend = DesktopBackend(self.events.append)
        backend.loop.close()
        backend.loop = asyncio.get_running_loop()
        backend.browser = self.browser
        backend.pages["tab"] = self.page
        restore = {name: getattr(config, name) for name in ("AI_API_KEY", "AI_API_BASE", "AI_MODEL", "AI_GATEWAY_URL", "AI_GATEWAY_MODEL")}
        try:
            with patch("desktop_backend.api.fetch_game_snapshot", side_effect=ValueError("Manifest unavailable")), \
                 patch("desktop_backend.api.fetch_game_answers") as keys, \
                 patch("desktop_backend.probe", AsyncMock(return_value=(True, "Test answer received"))), \
                 patch("automation.solve_question_with_ai", Mock(side_effect=[([0], "[Fixture AI]"), ([1], "[Fixture AI]")])):
                await backend._prepare("tab", mode="ai", cheatnetwork=False)
                self.assertTrue(backend.prepared.ready)
                self.assertEqual(backend.prepared.total, 0)
                keys.assert_not_called()
                await backend._start_run(delay=0, wrong_limit=0, highlight=False)
                await asyncio.wait_for(backend.run_task, 15)
            self.assertEqual(await self.page.evaluate("submissions"), ["A", "D"])
            self.assertTrue(any(e["type"] == "finished" and e["complete"] for e in self.events))
        finally:
            for name, value in restore.items():
                setattr(config, name, value)
            if backend.run_task and not backend.run_task.done():
                backend.control.stop()
                backend.run_task.cancel()

    async def test_game_link_prepares_keys_for_already_active_tab(self):
        await self.page.route("**/*", lambda route: route.fulfill(status=200, body=MCQ, content_type="text/html"))
        await self.page.goto("https://wayground.com/join/game/live-fixture")
        backend = DesktopBackend(self.events.append)
        backend.loop.close()
        backend.loop = asyncio.get_running_loop()
        backend.browser = self.browser
        backend.pages["tab"] = self.page
        questions = [
            {"_id": qid, "type": "MCQ", "structure": {"query": {"text": "Which is correct?"}, "options": [{"text": value} for value in options]}}
            for qid, options in [("q1", ("A", "B")), ("q2", ("C", "D"))]
        ]
        snapshot = {"name": "Active fixture", "pin": "12345678", "hash": "roomhashvalue", "questions": questions}
        with patch("desktop_backend.api.fetch_game_snapshot", return_value=snapshot) as fetch, \
             patch("desktop_backend.api.fetch_game_answers", return_value=self.keys()):
            await backend._prepare("tab", mode="keys", pin="https://wayground.com/join?gc=12345678&source=liveDashboard", cheatnetwork=False)
        self.assertTrue(backend.prepared.ready)
        self.assertEqual(backend.prepared.pin, "12345678")
        fetch.assert_called_once_with("12345678")

    async def test_same_session_route_transition_keeps_binding(self):
        await self.page.route("**/*", lambda route: route.fulfill(status=200, body=MCQ, content_type="text/html"))
        await self.page.goto("https://wayground.com/join/game/session-a?gc=12345678")
        binding = await SessionBinding.create(self.page, pin="12345678", room_hash="roomhashvalue")
        await self.page.evaluate("history.pushState({}, '', '/join/assessment/session-a?gc=12345678')")
        await binding.validate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
