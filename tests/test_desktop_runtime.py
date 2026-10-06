"""Desktop controls must gate actual browser actions and preserve session identity."""

import asyncio
import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import automation
import config
import desktop_backend
import desktop_engines
from answer_db import AnswerDatabase
from desktop_backend import DesktopBackend, verified_manifest
from runtime_control import ACTIVE_CONTROL, RuntimeControl, RunStopped, SessionChanged
from runtime_control import ACTIVE_CANCELLATION
from session_binding import SessionBinding, is_game_url


class FakePage:
    def __init__(self):
        self.url = "https://wayground.com/join/game/same-session?gc=12345678"
        self.closed = False
        self.info = {"pin": "12345678", "hash": "", "marker": ""}

    def is_closed(self):
        return self.closed

    async def evaluate(self, script, *args):
        if args:
            self.info["marker"] = args[0]
            return None
        return dict(self.info)

    async def title(self):
        return "Selected game"


def game_question(qid="q1", *, text="Which is correct?", options=("A", "B"), kind="MCQ"):
    return {"_id": qid, "type": kind, "structure": {"query": {"text": text},
            "options": [{"text": answer} for answer in options]}}


class ControlsTests(unittest.IsolatedAsyncioTestCase):
    def control(self, **kwargs):
        self.events = []
        control = RuntimeControl(self.events.append, delay=0, **kwargs)
        control.begin_question(key="q1:1", number=1, total=10, text="Question")
        return control

    async def test_pause_then_answer_now_executes_one_transaction_and_stays_paused(self):
        control = self.control()
        control.pause(True)
        task = asyncio.create_task(control.before_submit(["A"], source="API", verified=True))
        await asyncio.sleep(0.02)
        self.assertFalse(task.done())
        control.answer_now()
        self.assertIs(await asyncio.wait_for(task, 1), False)
        self.assertTrue(await control.checkpoint(action=True))
        control.submitted()
        self.assertTrue(control.paused)
        next_action = asyncio.create_task(control.checkpoint(action=True))
        await asyncio.sleep(0.02)
        self.assertFalse(next_action.done())
        control.stop()
        with self.assertRaises(RunStopped):
            await next_action

    async def test_stop_while_paused_does_not_touch_browser_button(self):
        control = self.control()
        control.pause(True)
        token = ACTIVE_CONTROL.set(control)
        button = SimpleNamespace(click=AsyncMock(), evaluate=AsyncMock())
        try:
            task = asyncio.create_task(automation._safe_click(button, "test"))
            await asyncio.sleep(0.02)
            control.stop()
            with self.assertRaises(RunStopped):
                await task
        finally:
            ACTIVE_CONTROL.reset(token)
        button.click.assert_not_awaited()
        button.evaluate.assert_not_awaited()

    async def test_changed_question_rejects_stale_click(self):
        control = self.control()
        control.question_guard = AsyncMock(return_value=False)
        button = SimpleNamespace(click=AsyncMock(), evaluate=AsyncMock())
        token = ACTIVE_CONTROL.set(control)
        try:
            self.assertFalse(await automation._safe_click(button, "test"))
        finally:
            ACTIVE_CONTROL.reset(token)
        button.click.assert_not_awaited()

    async def test_zero_wrong_limit_disables_future_mistakes_and_keeps_used_history(self):
        control = self.control(wrong_limit=1)
        with patch("runtime_control.random.random", return_value=0):
            self.assertTrue(await control.before_submit(["A"], source="API", verified=True, wrong_answers=["B"]))
        control.submitted()
        control.submitted()
        self.assertEqual(control.wrong_used, 1)
        control.set_wrong_limit(0)
        self.assertEqual(control.wrong_limit, 0)
        self.assertEqual(control.wrong_used, 1)
        settings = next(event for event in reversed(self.events) if event["type"] == "settings")
        self.assertEqual((settings["wrong_used"], settings["wrong_limit"]), (1, 0))
        control.begin_question(key="q2:2", number=2, total=10, text="Next")
        with patch("runtime_control.random.random", return_value=0):
            self.assertFalse(await control.before_submit(["C"], source="API", verified=True, wrong_answers=["D"]))
        self.assertFalse(control.toggle_wrong())

    async def test_zero_wrong_limit_cancels_waiting_mistake_before_submission(self):
        control = self.control(wrong_limit=2)
        control.wrong_used = 1
        control.pause(True)
        with patch("runtime_control.random.random", return_value=0):
            task = asyncio.create_task(control.before_submit(["A"], source="API", verified=True, wrong_answers=["B"]))
            await asyncio.sleep(0.02)
            self.assertTrue(control.deliberate)
            self.assertFalse(task.done())
            control.set_wrong_limit(0)
            preview = next(event for event in reversed(self.events) if event["type"] == "answer")
            self.assertEqual(preview["answers"], ["A"])
            self.assertFalse(preview["can_wrong"])
            self.assertFalse(preview["deliberate"])
            self.assertFalse(control.toggle_wrong())
            control.answer_now()
            self.assertFalse(await asyncio.wait_for(task, 1))
        control.submitted()
        self.assertEqual(control.wrong_used, 1)
        self.assertEqual(control.wrong_limit, 0)

    async def test_negative_wrong_limit_clamps_to_zero_without_erasing_history(self):
        control = self.control(wrong_limit=3)
        control.wrong_used = 1
        control.deliberate = True
        control.set_wrong_limit(-2)
        self.assertEqual(control.wrong_limit, 0)
        self.assertEqual(control.wrong_used, 1)
        self.assertFalse(control.deliberate)

    async def test_zero_limit_keeps_inflight_mistake_history_then_disables_next_mistake(self):
        control = self.control(wrong_limit=1)
        with patch("runtime_control.random.random", return_value=0):
            self.assertTrue(await control.before_submit(["A"], source="API", verified=True, wrong_answers=["B"]))
        self.assertEqual(control.phase, "submitting")
        control.set_wrong_limit(0)
        self.assertTrue(control.deliberate)
        self.assertFalse(control.toggle_wrong())
        control.submitted()
        self.assertEqual((control.wrong_used, control.wrong_limit), (1, 0))
        control.begin_question(key="q2:2", number=2, total=10, text="Next")
        with patch("runtime_control.random.random", return_value=0):
            self.assertFalse(await control.before_submit(["C"], source="API", verified=True, wrong_answers=["D"]))
        self.assertFalse(control.toggle_wrong())
        control.submitted()
        self.assertEqual((control.wrong_used, control.wrong_limit), (1, 0))

    async def test_ai_prediction_cannot_be_deliberately_wrong_or_highlighted_as_key(self):
        control = self.control(wrong_limit=9)
        result = await control.before_submit(["A"], source="AI", verified=False, wrong_answers=["B"])
        self.assertFalse(result)
        self.assertFalse(control.verified)
        self.assertFalse(control.toggle_wrong())

    async def test_successful_switch_applies_only_before_next_ai_request(self):
        apply = Mock()
        control = self.control(apply_engine=apply)
        control.queue_engine("new-engine")
        apply.assert_not_called()
        control.use_pending_engine()
        apply.assert_called_once_with("new-engine")
        control.use_pending_engine()
        apply.assert_called_once()


class BindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.page = FakePage()
        self.binding = await SessionBinding.create(self.page, pin="12345678", room_hash="roomhash")

    async def test_same_tab_question_changes_are_allowed(self):
        await self.binding.validate()
        self.page.info["qid"] = "another-question"
        await self.binding.validate()

    async def test_reloaded_page_requires_preparation(self):
        self.page.info["marker"] = ""
        with self.assertRaises(SessionChanged):
            await self.binding.validate()

    async def test_pin_change_stops_same_route(self):
        self.page.info["pin"] = "99999999"
        with self.assertRaises(SessionChanged):
            await self.binding.validate()

    async def test_closed_tab_stops(self):
        self.page.closed = True
        with self.assertRaises(SessionChanged):
            await self.binding.validate()

    async def test_results_on_foreign_host_are_rejected(self):
        self.page.url = "https://example.com/results"
        with self.assertRaises(SessionChanged):
            await self.binding.validate()

    async def test_real_wayground_summary_is_allowed_after_navigation(self):
        self.page.url = "https://wayground.com/join/game-summary"
        self.page.info["marker"] = ""
        await self.binding.validate()

    def test_target_chooser_excludes_teacher_and_answer_sources(self):
        self.assertTrue(is_game_url("https://wayground.com/join?gc=12345678"))
        for url in ("https://wayground.com/activity/admin/quiz/abc", "https://wayground.com/admin/search", "https://cheatnetwork.eu/services/quizizz", "https://fake.wayground.com/join"):
            self.assertFalse(is_game_url(url))


class ManifestTests(unittest.TestCase):
    def test_all_51_repeated_stems_keep_their_ids_and_answers(self):
        questions = [game_question(f"q{i}", options=(f"Right {i}", f"Wrong {i}")) for i in range(51)]
        keys = AnswerDatabase()
        for i in range(51):
            keys.add_question("Which is correct?", [f"Right {i}"], qid=f"q{i}", options=[{"text": f"Wrong {i}"}, {"text": f"Right {i}"}])
        manifest = verified_manifest(questions, keys)
        self.assertEqual(len(manifest.questions), 51)
        self.assertEqual([r.answers for r in manifest.questions.values()], [[f"Right {i}"] for i in range(51)])

    def test_wrong_source_with_identical_stem_is_rejected(self):
        keys = AnswerDatabase()
        keys.add_question("Which is correct?", ["C"], options=[{"text": "C"}, {"text": "D"}])
        record = next(iter(verified_manifest([game_question()], keys).questions.values()))
        self.assertFalse(record.answers)
        self.assertFalse(record.manual_required)

    def test_same_question_text_cannot_reuse_one_row_for_two_questions(self):
        keys = {"Which is correct?": ["A"]}
        manifest = verified_manifest([game_question("q1"), game_question("q2")], keys)
        self.assertEqual(sum(bool(r.answers) for r in manifest.questions.values()), 1)

    def test_open_question_counts_as_manual_never_as_a_key(self):
        question = game_question(kind="OPEN", options=())
        record = next(iter(verified_manifest([question], None).questions.values()))
        self.assertTrue(record.manual_required)
        self.assertEqual(record.answers, [])


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.backend = DesktopBackend(self.events.append)
        self.addCleanup(self.backend.loop.close)
        self.backend.pages["tab"] = FakePage()
        self.snapshot = {"pin": "12345678", "hash": "roomhash", "name": "Chosen test", "questions": [game_question()]}
        self.keys = AnswerDatabase()
        self.keys.add_question("Which is correct?", ["A"], qid="q1", options=[{"text": "A"}, {"text": "B"}])
        patcher = patch("desktop_backend._read_question_counter", AsyncMock(return_value=(1, 1)))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def prepare(self, *, mode="keys", answers=None):
        with patch("desktop_backend.api.fetch_game_snapshot", return_value=self.snapshot), \
                patch("desktop_backend.api.fetch_game_answers", return_value=answers or self.keys):
            await self.backend._prepare("tab", mode=mode, cheatnetwork=False)

    async def test_keys_only_never_probes_ai_and_requires_complete_keys(self):
        with patch("desktop_backend.probe", AsyncMock()) as probe:
            await self.prepare()
        probe.assert_not_awaited()
        self.assertTrue(self.backend.prepared.ready)
        event = next(e for e in self.events if e["type"] == "prepared")
        self.assertEqual(event["key_count"], 1)
        self.assertEqual(event["total"], 1)

    async def test_unavailable_ai_cannot_start(self):
        with patch("desktop_backend.probe", AsyncMock(return_value=(False, "No provider"))):
            await self.prepare(mode="ai")
        self.assertFalse(self.backend.prepared.ready)
        with self.assertRaisesRegex(RuntimeError, "prepare"):
            await self.backend._start_run()

    async def test_entered_pin_cannot_target_another_game(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            await self.backend._prepare("tab", pin="99999999")

    async def test_incomplete_keys_disable_start(self):
        other = AnswerDatabase()
        other.add_question("Other test", ["C"], qid="other")
        await self.prepare(answers=other)
        self.assertFalse(self.backend.prepared.ready)
        self.assertEqual(self.events[-1]["key_count"], 0)

    async def test_probing_an_engine_does_not_change_current_solver_globals(self):
        original = (config.AI_MODEL, config.AI_GATEWAY_MODEL, config.AI_API_BASE)
        self.backend.control = RuntimeControl(self.events.append)
        with patch("desktop_backend.probe", AsyncMock(return_value=(True, "Test answer received"))):
            await self.backend._check_engine("groq-120b", live=True)
        self.assertEqual((config.AI_MODEL, config.AI_GATEWAY_MODEL, config.AI_API_BASE), original)
        self.assertEqual(self.backend.control._engine_pending.id, "groq-120b")

    async def test_shutdown_disconnects_without_closing_browser(self):
        self.backend.loop = Mock()
        self.backend.playwright = SimpleNamespace(stop=AsyncMock())
        self.backend.browser = SimpleNamespace(close=AsyncMock())
        await self.backend._shutdown()
        self.backend.playwright.stop.assert_awaited_once()
        self.backend.browser.close.assert_not_awaited()

    async def test_disconnect_cancels_a_waiting_run_immediately(self):
        self.backend.control = RuntimeControl(self.events.append)
        self.backend.prepared = object()
        self.backend.run_task = asyncio.create_task(asyncio.Event().wait())
        await asyncio.sleep(0)
        self.backend._disconnected()
        with self.assertRaises(asyncio.CancelledError):
            await self.backend.run_task
        self.assertTrue(self.backend.control.stopped)
        self.assertIsNone(self.backend.prepared)
        self.assertFalse(self.events[-1]["connected"])

    def test_public_engine_catalog_never_exposes_keys(self):
        spec = desktop_engines.Engine("test", "Test", "secret-key", "model", "url", "gateway")
        self.assertNotIn("secret-key", str(spec.public()))

    async def test_cancelled_lookup_cannot_start_more_network_requests(self):
        cancellation = threading.Event()
        cancellation.set()
        token = ACTIVE_CANCELLATION.set(cancellation)
        try:
            with patch("api.urllib.request.urlopen") as request:
                with self.assertRaises(RunStopped):
                    await asyncio.to_thread(desktop_backend.api._request_json, "https://wayground.com/unused")
            request.assert_not_called()
        finally:
            ACTIVE_CANCELLATION.reset(token)


class ManualDesktopTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_response_waits_for_user_then_continues_without_filling(self):
        events = []
        control = RuntimeControl(events.append, delay=0)
        answers = AnswerDatabase()
        answers.add_question("Write a response", [], qid="open", manual_required=True)
        question = {"qid": "open", "text": "Write a response", "image": ""}
        next_question = {"qid": "next", "text": "Next question", "image": ""}
        page = SimpleNamespace(query_selector=AsyncMock(return_value=None), query_selector_all=AsyncMock())
        fib = Mock()
        with contextlib.redirect_stdout(io.StringIO()), \
             patch("automation._wait_for_question_or_end", AsyncMock(side_effect=[("question", question), ("ended", None)])), \
             patch("automation._read_question_counter", AsyncMock(return_value=(1, 2))), \
             patch("automation._extract_question_info", AsyncMock(side_effect=[question, next_question])), \
             patch("automation.clear_highlights", AsyncMock()), \
             patch("automation.solve_fib_with_ai", fib):
            result = await automation.automate_test(page, answers, expected_total=2, use_ai=True, control=control)
        self.assertTrue(result)
        self.assertTrue(any(e["type"] == "manual" for e in events))
        self.assertTrue(any(e["type"] == "submitted" for e in events))
        page.query_selector_all.assert_not_awaited()
        fib.assert_not_called()


class WorkerLifecycleTests(unittest.TestCase):
    def test_idle_worker_closes_its_event_loop_and_thread(self):
        done = threading.Event()
        backend = DesktopBackend(lambda event: done.set() if event["type"] == "closed" else None)
        backend.start()
        backend.request("shutdown")
        self.assertTrue(done.wait(3))
        backend.thread.join(3)
        self.assertFalse(backend.thread.is_alive())
        self.assertTrue(backend.loop.is_closed())


if __name__ == "__main__":
    unittest.main()
