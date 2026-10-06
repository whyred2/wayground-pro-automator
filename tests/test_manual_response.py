"""Unkeyed open responses require user input, not a fill-in-the-blank prediction."""

import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from answer_db import AnswerDatabase
import automation


OPEN_TEXT = "Explain how technical writing differs from creative writing."


class ManualResponseTests(unittest.IsolatedAsyncioTestCase):
    async def run_question(self, answers, question, *, wrong_count=0, ai_only=False):
        field = SimpleNamespace(
            is_visible=AsyncMock(return_value=True), scroll_into_view_if_needed=AsyncMock(),
            click=AsyncMock(), fill=AsyncMock(), evaluate=AsyncMock(), press=AsyncMock(),
        )
        page = SimpleNamespace(
            query_selector=AsyncMock(return_value=None),
            query_selector_all=AsyncMock(return_value=[field]),
        )
        observed = SimpleNamespace(
            advance=AsyncMock(return_value=True), clicks=AsyncMock(return_value=True),
            clear=AsyncMock(), found=Mock(), errors=Mock(), info=Mock(),
            fib_solver=Mock(return_value=(["invented response"], [], "prediction")),
            option_solver=Mock(return_value=([0], "prediction")),
            options=AsyncMock(return_value=[]),
        )
        replacements = {
            "_read_question_counter": AsyncMock(return_value=(1, 2)),
            "_wait_for_question_or_end": AsyncMock(side_effect=[("question", question), ("ended", None)]),
            "_extract_question_info": AsyncMock(return_value=question),
            "_get_option_buttons": observed.options,
            "_advance_if_next_button": observed.advance,
            "_safe_click": observed.clicks,
            "_wait_for_transition": AsyncMock(),
            "clear_highlights": observed.clear,
            "highlight_question": AsyncMock(), "highlight_answer": AsyncMock(),
            "solve_fib_with_ai": observed.fib_solver,
            "solve_question_with_ai": observed.option_solver,
            "log_found": observed.found, "log_error": observed.errors, "log_info": observed.info,
            "calc_think_time": Mock(return_value=0),
        }
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for name, value in replacements.items():
                stack.enter_context(patch.object(automation, name, value))
            stack.enter_context(patch.object(automation.asyncio, "sleep", AsyncMock()))
            stack.enter_context(patch.object(automation.random, "sample", return_value=[1]))
            stack.enter_context(patch.object(automation, "generate_plausible_wrong", return_value="wrong term"))
            result = await automation.automate_test(
                page, answers, use_ai=True, ai_only=ai_only, wrong_count=wrong_count,
            )
        return result, field, observed

    def open_answers(self):
        answers = AnswerDatabase()
        answers.add_question(OPEN_TEXT, [], qid="open-question", manual_required=True)
        return answers

    def assert_manual_stop(self, result, field, seen):
        self.assertIs(result, False)
        field.fill.assert_not_awaited()
        field.click.assert_not_awaited()
        field.press.assert_not_awaited()
        seen.clicks.assert_not_awaited()
        seen.advance.assert_not_awaited()
        seen.fib_solver.assert_not_called()
        seen.option_solver.assert_not_called()
        seen.options.assert_not_awaited()
        seen.found.assert_not_called()
        seen.clear.assert_awaited_once()
        seen.errors.assert_called_once()
        message = seen.errors.call_args.args[0]
        self.assertIn("no fixed answer key", message)
        self.assertIn("your own response manually", message)
        self.assertIn("No answer was submitted", message)
        self.assertFalse(any("Correct:" in call.args[0] for call in seen.info.call_args_list))

    async def test_known_open_question_id_stops_before_ai_despite_truncated_stem(self):
        result, field, seen = await self.run_question(
            self.open_answers(),
            {"qid": "open-question", "text": "Explain how technical writing...", "image": ""},
        )
        self.assert_manual_stop(result, field, seen)

    async def test_open_question_without_dom_id_matches_unique_normalized_text(self):
        result, field, seen = await self.run_question(
            self.open_answers(),
            {"qid": None, "text": "  EXPLAIN how technical writing differs from creative writing!  ", "image": ""},
        )
        self.assert_manual_stop(result, field, seen)

    async def test_ai_only_still_respects_known_manual_question_metadata(self):
        result, field, seen = await self.run_question(
            self.open_answers(), {"qid": "open-question", "text": OPEN_TEXT, "image": ""},
            ai_only=True,
        )
        self.assert_manual_stop(result, field, seen)

    async def test_manual_question_is_not_submitted_as_a_deliberate_mistake(self):
        result, field, seen = await self.run_question(
            self.open_answers(), {"qid": "open-question", "text": OPEN_TEXT, "image": ""},
            wrong_count=1,
        )
        self.assert_manual_stop(result, field, seen)
        self.assertFalse(any("Target score:" in call.args[0] for call in seen.info.call_args_list))

    async def test_normal_keyed_blank_in_same_test_still_fills_without_score_prediction(self):
        answers = self.open_answers()
        answers.add_question("Provide the missing term.", ["citation"], qid="blank-question")
        result, field, seen = await self.run_question(
            answers, {"qid": "blank-question", "text": "Provide the missing term.", "image": ""},
            wrong_count=1,
        )
        self.assertIs(result, True)
        field.fill.assert_awaited_once_with("wrong term")
        seen.advance.assert_awaited_once()
        seen.fib_solver.assert_not_called()
        seen.errors.assert_not_called()
        self.assertFalse(any("Target score:" in call.args[0] for call in seen.info.call_args_list))

    async def test_shared_stem_with_unknown_id_is_not_assumed_to_be_manual(self):
        answers = self.open_answers()
        answers.add_question(OPEN_TEXT, ["citation"], qid="normal-question")
        result, field, seen = await self.run_question(
            answers, {"qid": "unknown-question", "text": OPEN_TEXT, "image": ""},
        )
        self.assertIs(result, True)
        seen.fib_solver.assert_called_once()
        field.fill.assert_awaited_once_with("invented response")
        seen.errors.assert_not_called()

    async def test_known_normal_id_wins_over_manual_record_with_same_stem(self):
        answers = self.open_answers()
        answers.add_question(OPEN_TEXT, ["citation"], qid="normal-question")
        result, field, seen = await self.run_question(
            answers, {"qid": "normal-question", "text": OPEN_TEXT, "image": ""},
        )
        self.assertIs(result, True)
        field.fill.assert_awaited_once_with("citation")
        seen.fib_solver.assert_not_called()
        seen.errors.assert_not_called()


if __name__ == "__main__":
    unittest.main()
