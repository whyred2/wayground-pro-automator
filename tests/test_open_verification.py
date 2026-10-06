"""Verify fixed answer keys without inventing keys for written responses."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import api


def keyed_question(index):
    return {
        "_id": f"keyed-{index}", "type": "MCQ", "ver": 2,
        "structure": {
            "kind": "MCQ", "query": {"text": f"Question {index}", "media": []},
            "options": [{"id": "yes", "text": "True"},
                        {"id": "no", "text": "False"}],
            "settings": {"hasCorrectAnswer": True}, "answer": index % 2,
        },
    }


def open_question():
    return {
        "_id": "written-response", "type": "OPEN", "ver": 4,
        "structure": {
            "kind": "OPEN", "query": {"text": "Explain your reasoning.", "media": []},
            "options": [], "settings": {"hasCorrectAnswer": False},
        },
    }


def game_questions(source):
    game = copy.deepcopy(source)
    for question in game:
        question["structure"].pop("answer", None)
    return game


class OpenVerificationTests(unittest.TestCase):
    def test_46_verified_questions_keep_45_keys_and_the_written_response(self):
        source = [keyed_question(index) for index in range(45)] + [open_question()]
        db = api._verified_quiz_answers(game_questions(source), {"questions": source})

        self.assertEqual(len(db.questions), 46)
        for index in range(45):
            self.assertEqual(db[f"id:keyed-{index}"], ["True" if index % 2 == 0 else "False"])
        self.assertEqual(sum(bool(record.answers) for record in db.questions.values()), 45)
        self.assertEqual(sum(key.startswith("id:") for key in db), 45)
        self.assertEqual(db.questions["id:written-response"].answers, [])
        self.assertTrue(db.questions["id:written-response"].manual_required)
        self.assertEqual(db.questions["id:written-response"].text, "Explain your reasoning.")
        self.assertFalse(db.questions["id:keyed-0"].manual_required)
        self.assertNotIn("id:written-response", db)

    def test_written_response_remains_in_the_verified_game_order(self):
        source = [keyed_question(1), open_question(), keyed_question(2)]
        db = api._verified_quiz_answers(game_questions(source), {"questions": source})
        self.assertEqual(list(db.questions), ["id:keyed-1", "id:written-response", "id:keyed-2"])

    def test_no_fixed_key_must_be_explicit_in_both_game_and_source(self):
        for side in ("game", "source"):
            for flag in (None, True, 0, "false"):
                with self.subTest(side=side, flag=flag):
                    source = [keyed_question(1), open_question()]
                    game = game_questions(source)
                    question = (game if side == "game" else source)[1]
                    if flag is None:
                        question["structure"]["settings"].pop("hasCorrectAnswer")
                    else:
                        question["structure"]["settings"]["hasCorrectAnswer"] = flag
                    self.assertEqual(api._verified_quiz_answers(game, {"questions": source}), {})

    def test_non_open_question_cannot_omit_a_key_using_the_same_flag(self):
        for kind in ("MCQ", "MSQ", "FIB", "BLANK"):
            with self.subTest(kind=kind):
                source = [keyed_question(1), open_question()]
                source[1]["type"] = kind
                source[1]["structure"]["kind"] = kind
                self.assertEqual(api._verified_quiz_answers(game_questions(source),
                                                           {"questions": source}), {})

    def test_conflicting_type_and_kind_cannot_exempt_a_missing_key(self):
        source = [keyed_question(1), open_question()]
        source[1]["structure"]["kind"] = "MCQ"
        self.assertEqual(api._verified_quiz_answers(game_questions(source), {"questions": source}), {})

    def test_changed_written_response_is_still_rejected(self):
        for field in ("query", "options", "kind"):
            with self.subTest(field=field):
                source = [keyed_question(1), open_question()]
                game = game_questions(source)
                source[1]["structure"][field] = {
                    "query": {"text": "A different essay", "media": []},
                    "options": [{"text": "An unexpected option"}],
                    "kind": "MCQ",
                }[field]
                self.assertEqual(api._verified_quiz_answers(game, {"questions": source}), {})

    def test_source_must_include_the_written_response_id(self):
        source = [keyed_question(1), open_question()]
        self.assertEqual(api._verified_quiz_answers(game_questions(source),
                                                   {"questions": source[:1]}), {})

    def test_missing_or_invalid_fixed_key_rejects_the_entire_source(self):
        for answer in (None, [], False, {}, 99):
            with self.subTest(answer=answer):
                source = [keyed_question(1), open_question()]
                game = game_questions(source)
                source[0]["structure"]["answer"] = answer
                self.assertEqual(api._verified_quiz_answers(game, {"questions": source}), {})

    def test_empty_record_never_treats_an_open_response_as_a_known_key(self):
        source = [keyed_question(1), open_question()]
        source[1]["structure"]["answer"] = [0]
        source[1]["structure"]["options"] = [{"text": "A sample response"}]
        db = api._verified_quiz_answers(game_questions(source), {"questions": source})
        self.assertEqual(db.questions["id:written-response"].answers, [])
        self.assertTrue(db.questions["id:written-response"].manual_required)
        self.assertNotIn("id:written-response", db)


if __name__ == "__main__":
    unittest.main()
