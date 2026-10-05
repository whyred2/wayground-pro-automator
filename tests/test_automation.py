"""Automation must leave unresolved questions untouched instead of inventing answers."""

import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import automation


QUESTION = {"qid": "target-question", "text": "Provide the missing term.", "image": ""}


def blank():
    return SimpleNamespace(
        is_visible=AsyncMock(return_value=True),
        scroll_into_view_if_needed=AsyncMock(), click=AsyncMock(), fill=AsyncMock(),
        evaluate=AsyncMock(), press=AsyncMock(),
    )


class AnswerAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    async def run_question(
        self, *, answers=None, blanks=0, options=(), use_ai=False,
        fib_prediction=([], [], "Unavailable"), option_prediction=([], "Unavailable"),
        solver_error=None, wrong_count=0, multiselect=False,
    ):
        inputs = [blank() for _ in range(blanks)]
        buttons = [object() for _ in options]
        button_info = [
            {"text": text, "alt": "", "img_src": "", "cy_index": idx}
            for idx, text in enumerate(options)
        ]

        async def selector(value):
            if value.startswith('[role="radiogroup"]') and buttons and not multiselect:
                return object()
            if value.startswith("button.option.is-msq") and multiselect:
                return object()
            return None

        page = SimpleNamespace(
            query_selector=AsyncMock(side_effect=selector),
            query_selector_all=AsyncMock(return_value=inputs),
        )
        observed = SimpleNamespace(
            advance=AsyncMock(return_value=True), clicks=AsyncMock(return_value=True),
            clear=AsyncMock(), found=Mock(), errors=Mock(), info=Mock(),
            fib_solver=Mock(return_value=fib_prediction, side_effect=solver_error),
            option_solver=Mock(return_value=option_prediction, side_effect=solver_error),
        )
        replacements = {
            "_read_question_counter": AsyncMock(return_value=(1, 2)),
            "_wait_for_question_or_end": AsyncMock(side_effect=[("question", QUESTION), ("ended", None)]),
            "_extract_question_info": AsyncMock(return_value=QUESTION),
            "_get_option_buttons": AsyncMock(return_value=buttons),
            "_extract_button_info": AsyncMock(side_effect=button_info),
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
            for name, value in replacements.items():
                stack.enter_context(patch.object(automation, name, value))
            stack.enter_context(patch.object(automation.asyncio, "sleep", AsyncMock()))
            stack.enter_context(patch.object(automation.random, "sample", return_value=[1]))
            stack.enter_context(patch.object(automation, "generate_plausible_wrong", return_value="wrong term"))
            result = await automation.automate_test(
                page, answers or {}, use_ai=use_ai, wrong_count=wrong_count,
            )
        return result, inputs, buttons, observed

    def assert_untouched(self, result, inputs, observed):
        self.assertIs(result, False)
        for item in inputs:
            item.fill.assert_not_awaited()
            item.click.assert_not_awaited()
            item.press.assert_not_awaited()
        observed.clicks.assert_not_awaited()
        observed.advance.assert_not_awaited()
        observed.clear.assert_awaited_once()
        observed.found.assert_not_called()
        observed.errors.assert_called_once()
        self.assertIn("No answer was submitted", observed.errors.call_args.args[0])
        self.assertFalse(any("Automation complete" in call.args[0] for call in observed.info.call_args_list))
        self.assertFalse(any("Correct:" in call.args[0] for call in observed.info.call_args_list))

    async def test_blank_missing_key_with_ai_disabled_stops_without_yes(self):
        result, inputs, _, seen = await self.run_question(blanks=1)
        self.assert_untouched(result, inputs, seen)
        seen.fib_solver.assert_not_called()

    async def test_missing_answer_stops_even_when_deliberate_wrong_requested(self):
        result, inputs, _, seen = await self.run_question(blanks=1, wrong_count=1)
        self.assert_untouched(result, inputs, seen)

    async def test_partial_multiblank_key_is_not_repeated(self):
        result, inputs, _, seen = await self.run_question(
            blanks=2, answers={"id:target-question": ["citation"]},
        )
        self.assert_untouched(result, inputs, seen)

    async def test_partial_prediction_is_not_repeated(self):
        result, inputs, _, seen = await self.run_question(
            blanks=2, use_ai=True, fib_prediction=(["citation"], [], "Only one term"),
        )
        self.assert_untouched(result, inputs, seen)
        seen.fib_solver.assert_called_once()

    async def test_empty_prediction_stops(self):
        result, inputs, _, seen = await self.run_question(blanks=1, use_ai=True)
        self.assert_untouched(result, inputs, seen)

    async def test_blank_solver_exception_stops(self):
        result, inputs, _, seen = await self.run_question(
            blanks=1, use_ai=True, solver_error=RuntimeError("API offline"),
        )
        self.assert_untouched(result, inputs, seen)

    async def test_empty_text_is_not_a_complete_key(self):
        result, inputs, _, seen = await self.run_question(
            blanks=2, answers={"id:target-question": ["citation", " "]},
        )
        self.assert_untouched(result, inputs, seen)

    async def test_known_yes_remains_valid(self):
        result, inputs, _, seen = await self.run_question(
            blanks=1, answers={"id:target-question": ["yes"]},
        )
        self.assertIs(result, True)
        inputs[0].fill.assert_awaited_once_with("yes")
        seen.advance.assert_awaited_once()
        seen.fib_solver.assert_not_called()
        self.assertTrue(any("Correct: 1" in call.args[0] for call in seen.info.call_args_list))

    async def test_multiblank_answers_keep_order_and_repeated_terms(self):
        result, inputs, _, seen = await self.run_question(
            blanks=2, answers={"id:target-question": ["citation", "citation"]},
        )
        self.assertIs(result, True)
        for item in inputs:
            item.fill.assert_awaited_once_with("citation")
        seen.advance.assert_awaited_once()

    async def test_complete_ai_prediction_replaces_partial_key(self):
        result, inputs, _, seen = await self.run_question(
            blanks=2, use_ai=True, answers={"id:target-question": ["old"]},
            fib_prediction=(["source", "citation"], [], "Resolved both blanks"),
        )
        self.assertIs(result, True)
        inputs[0].fill.assert_awaited_once_with("source")
        inputs[1].fill.assert_awaited_once_with("citation")
        seen.advance.assert_awaited_once()

    async def test_valid_blank_still_supports_deliberate_wrong(self):
        result, inputs, _, seen = await self.run_question(
            blanks=1, answers={"id:target-question": ["citation"]}, wrong_count=1,
        )
        self.assertIs(result, True)
        inputs[0].fill.assert_awaited_once_with("wrong term")
        seen.advance.assert_awaited_once()

    async def test_missing_option_key_stops_without_random_choice(self):
        result, inputs, _, seen = await self.run_question(options=("A", "B"))
        self.assert_untouched(result, inputs, seen)
        seen.option_solver.assert_not_called()

    async def test_no_options_stops_without_submitting(self):
        result, inputs, _, seen = await self.run_question(
            answers={"id:target-question": ["citation"]}, use_ai=True,
        )
        self.assert_untouched(result, inputs, seen)
        seen.option_solver.assert_not_called()
        self.assertIn("no answer options", seen.errors.call_args.args[0])

    async def test_option_solver_failure_stops_without_random_choice(self):
        result, inputs, _, seen = await self.run_question(options=("A", "B"), use_ai=True)
        self.assert_untouched(result, inputs, seen)

    async def test_option_solver_exception_stops(self):
        result, inputs, _, seen = await self.run_question(
            options=("A", "B"), use_ai=True, solver_error=RuntimeError("API offline"),
        )
        self.assert_untouched(result, inputs, seen)

    async def test_invalid_option_prediction_stops(self):
        result, inputs, _, seen = await self.run_question(
            options=("A", "B"), use_ai=True, option_prediction=([0, 8], "Malformed choice"),
        )
        self.assert_untouched(result, inputs, seen)

    async def test_partial_multiselect_match_stops(self):
        result, inputs, _, seen = await self.run_question(
            options=("source", "other"), multiselect=True,
            answers={"id:target-question": ["source", "citation"]},
        )
        self.assert_untouched(result, inputs, seen)

    async def test_option_aliases_for_same_image_choice_are_complete(self):
        result, _, buttons, seen = await self.run_question(
            options=("", "other"),
            answers={"id:target-question": ["option-0", "index:0"]},
        )
        self.assertIs(result, True)
        seen.clicks.assert_awaited_once_with(buttons[0], "MSQ option 'Option 1'")
        seen.advance.assert_awaited_once()

    async def test_duplicate_correct_texts_for_same_choice_are_complete(self):
        result, _, buttons, seen = await self.run_question(
            options=("source", "other"), multiselect=True,
            answers={"id:target-question": ["source", "source"]},
        )
        self.assertIs(result, True)
        seen.clicks.assert_awaited_once_with(buttons[0], "MSQ option 'source'")
        seen.advance.assert_awaited_once()

    async def test_aliases_do_not_hide_a_missing_multiselect_answer(self):
        result, inputs, _, seen = await self.run_question(
            options=("", "other"), multiselect=True,
            answers={"id:target-question": ["option-0", "index:0", "citation"]},
        )
        self.assert_untouched(result, inputs, seen)

    async def test_valid_option_is_clicked(self):
        result, _, buttons, seen = await self.run_question(
            options=("source", "citation"), answers={"id:target-question": ["citation"]},
        )
        self.assertIs(result, True)
        seen.clicks.assert_awaited_once_with(buttons[1], "answer 'citation'")
        seen.advance.assert_awaited_once()

    async def test_valid_first_ai_option_is_clicked(self):
        result, _, buttons, seen = await self.run_question(
            options=("source", "citation"), use_ai=True, option_prediction=([0], "Source is correct"),
        )
        self.assertIs(result, True)
        seen.clicks.assert_awaited_once_with(buttons[0], "answer 'source'")
        seen.advance.assert_awaited_once()

    async def test_valid_options_still_support_deliberate_wrong(self):
        result, _, buttons, seen = await self.run_question(
            options=("source", "citation"), answers={"id:target-question": ["citation"]},
            wrong_count=1,
        )
        self.assertIs(result, True)
        seen.clicks.assert_awaited_once_with(buttons[0], "answer 'source'")
        seen.advance.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
