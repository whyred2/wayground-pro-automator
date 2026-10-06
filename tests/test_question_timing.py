"""Verify real desktop waits against the question-length timing and live controls."""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import automation
import runtime_control
from runtime_control import RuntimeControl, question_delay_seconds


class FormulaTests(unittest.TestCase):
    def test_longer_question_adds_reading_time_above_selected_minimum(self):
        self.assertEqual(question_delay_seconds("x" * 20, 10, jitter=0), 11)
        self.assertEqual(question_delay_seconds("x" * 200, 10, jitter=0), 20)
        self.assertEqual(question_delay_seconds("x" * 200, 15, jitter=0), 25)

    def test_variation_uses_original_range_and_never_crosses_minimum(self):
        self.assertEqual(question_delay_seconds("x" * 200, 10, jitter=-0.3), 14)
        self.assertEqual(question_delay_seconds("x" * 200, 10, jitter=0.3), 26)
        self.assertEqual(question_delay_seconds("Short", 10, jitter=-0.3), 10)

    def test_legacy_cli_keeps_same_formula_and_media_fallback(self):
        with patch("runtime_control.random.uniform", return_value=0):
            self.assertEqual(automation.calc_think_time("x" * 200), 20)
            self.assertEqual(automation.calc_think_time(""), 11.2)


class WaitingTests(unittest.IsolatedAsyncioTestCase):
    async def run_wait(self, *, minimum=10, text="x" * 200, change=None, paused=False):
        events = []
        control = RuntimeControl(events.append, delay=minimum)
        clock = [0.0]
        real_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            clock[0] += seconds
            if change:
                change(control, clock[0])
            await real_sleep(0)

        with patch("runtime_control.random.uniform", return_value=0) as variation:
            control.begin_question(key="q1", number=1, total=10, text=text)
            control.pause(paused)
            with patch.object(runtime_control, "time", SimpleNamespace(monotonic=lambda: clock[0])), \
                 patch.object(runtime_control, "asyncio", SimpleNamespace(sleep=fake_sleep)):
                result = await control.before_submit(["A"], source="API", verified=True)
            self.assertEqual(variation.call_count, 1)
        return control, events, clock[0], result

    async def test_actual_wait_and_countdown_use_variable_duration(self):
        control, events, elapsed, result = await self.run_wait()
        self.assertFalse(result)
        self.assertEqual(control.phase, "submitting")
        countdown = [event["remaining"] for event in events if event["type"] == "countdown"]
        self.assertEqual(countdown[0], 20)
        self.assertGreaterEqual(elapsed, 20)
        self.assertLess(elapsed, 20.051)

    async def test_changing_minimum_while_waiting_shortens_current_countdown(self):
        def lower(control, elapsed):
            if elapsed >= 5:
                control.delay = 5
        _, events, elapsed, _ = await self.run_wait(change=lower)
        countdown = [event["remaining"] for event in events if event["type"] == "countdown"]
        self.assertEqual(countdown[0], 20)
        self.assertGreaterEqual(elapsed, 15)
        self.assertLess(elapsed, 15.051)

    async def test_changing_minimum_while_waiting_extends_current_countdown(self):
        def extend(control, elapsed):
            if elapsed >= 5:
                control.delay = 15
        _, _, elapsed, _ = await self.run_wait(change=extend)
        self.assertGreaterEqual(elapsed, 25)
        self.assertLess(elapsed, 25.051)

    async def test_zero_explicitly_skips_automatic_waiting(self):
        _, events, elapsed, result = await self.run_wait(minimum=0)
        self.assertFalse(result)
        self.assertEqual(elapsed, 0)
        self.assertFalse(any(event["type"] == "countdown" for event in events))

    async def test_answer_now_bypasses_long_wait_without_resuming_paused_run(self):
        control, _, elapsed, result = await self.run_wait(
            text="x" * 1000, paused=True,
            change=lambda control, _: control.answer_now(),
        )
        self.assertFalse(result)
        self.assertTrue(control.paused)
        self.assertLess(elapsed, 0.1)


if __name__ == "__main__":
    unittest.main()
