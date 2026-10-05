"""Repeated stems are separate questions, with separate keys and option sets."""

import contextlib
import copy
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import api
import automation
import scraper
from answer_db import AnswerDatabase
from matching import find_answers, get_display_questions


STEM = "Choose the correct sentence."


def question(qid, correct, other="A different distractor."):
    return {"_id": qid, "type": "MCQ", "structure": {
        "query": {"text": STEM, "media": []},
        "options": [{"text": correct}, {"text": other}], "answer": 0,
    }}


def variant_keys():
    return api.parse_wayground_answers({"questions": [
        question("first", "You're eating my dinner.", "Your eating my dinner."),
        question("second", "I have two dogs.", "I have too dogs."),
    ]})


class QuestionRecordsTests(unittest.TestCase):
    def test_repeated_stems_keep_rows_and_do_not_merge_answer_sets(self):
        db = variant_keys()
        self.assertEqual(get_display_questions(db), [
            (STEM, ["You're eating my dinner."]), (STEM, ["I have two dogs."]),
        ])
        self.assertNotIn(STEM, db)
        self.assertEqual(find_answers(STEM, db, qid="first"), ["You're eating my dinner."])
        self.assertEqual(find_answers(STEM, db, qid="second"), ["I have two dogs."])

    def test_51_question_ids_produce_51_display_rows_despite_31_stems(self):
        questions = [question(f"q-{i}", f"Correct sentence {i}.") for i in range(51)]
        for i, q in enumerate(questions):
            q["structure"]["query"]["text"] = f"Question {i % 31}?"
        db = api.parse_wayground_answers({"questions": questions})
        rows = get_display_questions(db)
        self.assertEqual(len(rows), 51)
        self.assertEqual(len({text for text, _ in rows}), 31)
        self.assertEqual(sum(key.startswith("id:") for key in db), 51)
        self.assertEqual([answer for _, answer in rows], [[f"Correct sentence {i}."] for i in range(51)])

    def test_option_sets_resolve_a_duplicate_stem_without_question_id(self):
        db = variant_keys()
        buttons = [{"text": "I have too dogs."}, {"text": "I have two dogs."}]
        self.assertEqual(find_answers(STEM, db, options_info=buttons), ["I have two dogs."])

    def test_shared_correct_option_is_insufficient_without_matching_full_set(self):
        db = api.parse_wayground_answers({"questions": [
            question("first", "shared", "first distractor"),
            question("second", "second correct", "shared"),
        ]})
        self.assertEqual(find_answers(STEM, db, options_info=[
            {"text": "shared"}, {"text": "second correct"},
        ]), ["second correct"])

    def test_conflicting_keys_without_id_or_options_are_not_guessed(self):
        self.assertIsNone(find_answers(STEM, variant_keys()))

    def test_identical_stems_and_options_with_conflicting_keys_are_ambiguous(self):
        first = question("first", "one", "two")
        second = copy.deepcopy(first)
        second["_id"] = "second"
        second["structure"]["answer"] = 1
        db = api.parse_wayground_answers({"questions": [first, second]})
        self.assertIsNone(find_answers(STEM, db, options_info=[{"text": "one"}, {"text": "two"}]))
        self.assertEqual(find_answers(STEM, db, qid="second"), ["two"])

    def test_same_answers_still_keep_each_occurrence(self):
        db = api.parse_wayground_answers({"questions": [question("first", "same"), question("second", "same")]})
        self.assertEqual(len(get_display_questions(db)), 2)
        self.assertEqual(find_answers(STEM, db), ["same"])

    def test_duplicate_image_names_cannot_replace_id_keys(self):
        questions = [question("first", "one"), question("second", "two")]
        for q in questions:
            q["structure"]["query"] = {"text": "", "media": [{"url": "https://example.com/same.png"}]}
        db = api.parse_wayground_answers({"questions": questions})
        self.assertEqual(len(get_display_questions(db)), 2)
        self.assertIsNone(find_answers("", db, image_url="https://example.com/same.png"))
        self.assertEqual(find_answers("", db, qid="second"), ["two"])

    def test_image_options_resolve_variants_ignoring_url_query_and_option_order(self):
        db = AnswerDatabase()
        db.add_question(STEM, ["first.png"], qid="first", options=[
            {"img_src": "https://example.com/first.png"}, {"text": "first distractor"}])
        db.add_question(STEM, ["second.png"], qid="second", options=[
            {"img_src": "https://example.com/second.png"}, {"text": "second distractor"}])
        self.assertEqual(find_answers(STEM, db, options_info=[
            {"text": "second distractor"}, {"img_src": "https://cdn.example/second.png?v=1"}]), ["second.png"])

    def test_capture_merges_records_by_id_instead_of_collapsing_by_text(self):
        db = api.parse_wayground_answers({"questions": [question("first", "one")]})
        db.update(api.parse_wayground_answers({"questions": [question("second", "two")]}))
        db.update(api.parse_wayground_answers({"questions": [question("first", "updated one")]}))
        self.assertEqual(get_display_questions(db), [(STEM, ["updated one"]), (STEM, ["two"])])
        self.assertEqual(db["id:first"], ["updated one"])

    def test_quizit_also_preserves_duplicate_question_records(self):
        db = api.parse_quizit_answers({"questions": [
            {"id": "first", "question": STEM, "answers": ["one"]},
            {"id": "second", "question": STEM, "answers": ["two"]},
        ]})
        self.assertEqual(get_display_questions(db), [(STEM, ["one"]), (STEM, ["two"])])
        self.assertIsNone(find_answers(STEM, db))

    def test_real_multiselect_answers_remain_in_one_record(self):
        q = question("multi", "one", "two")
        q["type"] = "MSQ"
        q["structure"]["answer"] = [0, 1]
        self.assertEqual(get_display_questions(api.parse_wayground_answers({"questions": [q]})),
                         [(STEM, ["one", "two"])])

    def test_plain_dictionary_sources_remain_compatible(self):
        self.assertEqual(get_display_questions({STEM: ["one"]}), [(STEM, ["one"])])
        self.assertEqual(find_answers(STEM, {STEM: ["one"]}), ["one"])


class RepeatedQuestionAutomationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    async def test_cheatnetwork_duplicate_rows_do_not_become_a_multiselect_answer(self):
        page = SimpleNamespace(evaluate=AsyncMock(return_value=[
            {"question": STEM, "answers": ["one"]}, {"question": STEM, "answers": ["two"]},
        ]))
        db = await scraper._parse_question_boxes(page)
        self.assertTrue(db)
        self.assertEqual(get_display_questions(db), [(STEM, ["one"]), (STEM, ["two"])])
        self.assertIsNone(find_answers(STEM, db))

    async def test_next_identical_stem_is_detected_by_question_number(self):
        info = {"text": STEM, "qid": None, "image": ""}
        page = SimpleNamespace(url="https://wayground.com/join/game/test", query_selector=AsyncMock(return_value=None))
        with patch.object(automation, "_get_option_buttons", new=AsyncMock(return_value=[object()])), \
                patch.object(automation, "_extract_question_info", new=AsyncMock(return_value=info)), \
                patch.object(automation, "_read_question_counter", new=AsyncMock(return_value=(2, 51))):
            status, found = await automation._wait_for_question_or_end(
                page, last_key=automation._question_key(info, 1), max_wait=1)
        self.assertEqual(status, "question")
        self.assertEqual(found["number"], 2)

    async def test_transition_accepts_new_counter_with_same_text(self):
        page = SimpleNamespace(url="https://wayground.com/join/game/test", query_selector=AsyncMock(return_value=None),
                               query_selector_all=AsyncMock(return_value=[]))
        with patch.object(automation, "_extract_question_info", new=AsyncMock(return_value={"text": STEM})), \
                patch.object(automation, "_read_question_counter", new=AsyncMock(return_value=(2, 51))), \
                patch.object(automation.asyncio, "sleep", new=AsyncMock()):
            self.assertTrue(await automation._wait_for_transition(page, old_text=STEM, old_q_num=1))

    async def test_same_stem_with_new_options_is_detected_without_id_or_counter(self):
        from matching import _option_signature
        previous = {"text": STEM, "option_key": repr(sorted(_option_signature([{"text": "old"}]).items()))}
        page = SimpleNamespace(url="https://wayground.com/join/game/test", query_selector=AsyncMock(return_value=None))
        with patch.object(automation, "_get_option_buttons", new=AsyncMock(return_value=[object()])), \
                patch.object(automation, "_extract_button_info", new=AsyncMock(return_value={"text": "new"})), \
                patch.object(automation, "_extract_question_info", new=AsyncMock(return_value={"text": STEM})), \
                patch.object(automation, "_read_question_counter", new=AsyncMock(return_value=(0, 0))):
            status, found = await automation._wait_for_question_or_end(
                page, last_key=automation._question_key(previous), max_wait=1)
        self.assertEqual(status, "question")
        self.assertNotEqual(automation._question_key(found), automation._question_key(previous))

    async def test_consecutive_identical_stems_without_ids_use_separate_option_keys(self):
        db = variant_keys()
        state = {"index": 0}
        records = list(db.questions.values())
        info = {"text": STEM, "qid": None, "image": ""}
        option_handles = [[object(), object()], [object(), object()]]
        option_info = {handle: record.options[i] for record, handles in zip(records, option_handles)
                       for i, handle in enumerate(handles)}

        async def wait(*args, **kwargs):
            return ("ended", None) if state["index"] == 2 else ("question", dict(info))

        async def advance(*args):
            state["index"] += 1
            return True

        page = SimpleNamespace(query_selector=AsyncMock(return_value=object()),
                               query_selector_all=AsyncMock(return_value=[]))
        click = AsyncMock(return_value=True)
        replacements = {
            "_read_question_counter": AsyncMock(side_effect=lambda _: (state["index"] + 1, 2)),
            "_wait_for_question_or_end": AsyncMock(side_effect=wait),
            "_extract_question_info": AsyncMock(return_value=info),
            "_get_option_buttons": AsyncMock(side_effect=lambda _: option_handles[state["index"]]),
            "_extract_button_info": AsyncMock(side_effect=lambda btn, idx: option_info[btn]),
            "_advance_if_next_button": AsyncMock(side_effect=advance), "_safe_click": click,
            "_wait_for_transition": AsyncMock(), "highlight_question": AsyncMock(),
            "highlight_answer": AsyncMock(), "clear_highlights": AsyncMock(),
            "calc_think_time": Mock(return_value=0), "solve_question_with_ai": Mock(),
        }
        with contextlib.ExitStack() as stack:
            for name, value in replacements.items():
                stack.enter_context(patch.object(automation, name, value))
            stack.enter_context(patch.object(automation.asyncio, "sleep", new=AsyncMock()))
            self.assertIs(await automation.automate_test(page, db, use_ai=False), True)
        self.assertEqual(state["index"], 2)
        self.assertEqual([call.args[0] for call in click.await_args_list],
                         [option_handles[0][0], option_handles[1][0]])
        replacements["solve_question_with_ai"].assert_not_called()

    async def test_timeout_does_not_report_a_partly_answered_quiz_as_completed(self):
        page = SimpleNamespace()
        with patch.object(automation, "_read_question_counter", new=AsyncMock(return_value=(31, 51))), \
                patch.object(automation, "_wait_for_question_or_end", new=AsyncMock(return_value=("timeout", None))):
            self.assertIs(await automation.automate_test(page, variant_keys(), use_ai=False), False)


if __name__ == "__main__":
    unittest.main()
