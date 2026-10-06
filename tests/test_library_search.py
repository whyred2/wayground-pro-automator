"""Find verified quizzes beyond the first broad search page."""

import contextlib
import copy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, call, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import api
import main as app
from matching import get_display_questions
from test_open_verification import keyed_question, open_question, game_questions


QUIZ_ID = "68862510ed25b6e4a794a2d5"
TITLE = "Technical Writing Quiz"


def hit(index, count=5):
    return {"quizId": f"{index:024x}", "name": TITLE, "noOfQuestions": count}


class LibrarySearchTests(unittest.TestCase):
    def setUp(self):
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def test_source_on_second_exact_title_page_returns_45_keys_and_one_manual_record(self):
        source = [keyed_question(index) for index in range(45)] + [open_question()]
        initial = [hit(index) for index in range(10)]
        first_phrase_page = [hit(index) for index in range(12)]
        second_phrase_page = [hit(index) for index in range(12, 24)]
        second_phrase_page[10] = {"quizId": QUIZ_ID, "name": TITLE, "noOfQuestions": 46}
        with patch.object(api, "_search_public_quizzes", side_effect=[
            initial, first_phrase_page, second_phrase_page,
        ]) as search, patch.object(api, "_fetch_quiz_payload", return_value={"questions": source}) as fetch:
            answers = api._fetch_library_answers(TITLE, game_questions(source))
        self.assertEqual(sum(key.startswith("id:") for key in answers), 45)
        self.assertEqual(len(get_display_questions(answers)), 46)
        self.assertTrue(answers.questions["id:written-response"].manual_required)
        fetch.assert_called_once_with(QUIZ_ID)
        self.assertEqual(search.call_args_list, [
            call(TITLE), call(TITLE, offset=0, page_size=12, exact_phrase=True),
            call(TITLE, offset=12, page_size=12, exact_phrase=True),
        ])

    def test_successful_fast_search_does_not_request_extra_pages(self):
        source = [keyed_question(1)]
        with patch.object(api, "_search_public_quizzes", return_value=[
            {"quizId": QUIZ_ID, "name": TITLE, "noOfQuestions": 1},
        ]) as search, patch.object(api, "_fetch_quiz_payload", return_value={"questions": source}):
            self.assertTrue(api._fetch_library_answers(TITLE, game_questions(source)))
        search.assert_called_once_with(TITLE)

    def test_phrase_search_uses_quotes_offset_and_page_size(self):
        with patch.object(api, "_request_json", return_value={"data": {"hits": []}}) as request:
            api._search_public_quizzes(TITLE, offset=12, page_size=12, exact_phrase=True)
        payload = request.call_args.args[1]
        self.assertEqual(payload["query"], '"Technical Writing Quiz"')
        self.assertEqual((payload["from"], payload["size"]), (12, 12))

    def test_pagination_advances_by_actual_count_when_server_caps_pages(self):
        pages = [[hit(1)], [hit(2), hit(3)], [hit(4), hit(5)], [hit(6)]]
        with patch.object(api, "_search_public_quizzes", side_effect=pages) as search:
            self.assertEqual(len(list(api._library_candidate_batches(TITLE))), 4)
        self.assertEqual([args.kwargs.get("offset") for args in search.call_args_list[1:]], [0, 2, 4])

    def test_repeated_search_page_stops_instead_of_polling_forever(self):
        same_page = [hit(1), hit(2)]
        with patch.object(api, "_search_public_quizzes", side_effect=[[], same_page, same_page]) as search:
            self.assertEqual(len(list(api._library_candidate_batches(TITLE))), 2)
        self.assertEqual(search.call_count, 3)

    def test_direct_public_quiz_preserves_the_manual_record(self):
        source = [keyed_question(1), open_question()]
        with patch.object(api, "_fetch_quiz_payload", return_value={"questions": source}):
            db = api.fetch_api_answers(QUIZ_ID)
        self.assertEqual(len(get_display_questions(db)), 2)
        self.assertEqual(sum(key.startswith("id:") for key in db), 1)
        self.assertTrue(db.questions["id:written-response"].manual_required)

    def test_unkeyed_open_record_does_not_short_circuit_hidden_game_keys(self):
        source = [keyed_question(1), open_question()]
        public_keys = api.parse_wayground_answers({"questions": source}, include_unkeyed=True)
        hidden_game = {"questions": game_questions(source)}
        with patch.object(api, "_request_json", return_value=hidden_game), \
                patch.object(api, "_game_resource_metadata", return_value={"name": TITLE}), \
                patch.object(api, "_fetch_library_answers", return_value=public_keys) as library:
            self.assertIs(api.fetch_game_answers("room-hash-60685869"), public_keys)
        library.assert_called_once()

    def test_supplied_game_keys_keep_the_manual_question_without_extra_lookup(self):
        source = [keyed_question(1), open_question()]
        with patch.object(api, "_request_json", return_value={"questions": source}), \
                patch.object(api, "_fetch_library_answers") as library:
            db = api.fetch_game_answers("room-hash-60685869")
        self.assertEqual(len(get_display_questions(db)), 2)
        self.assertTrue(db.questions["id:written-response"].manual_required)
        library.assert_not_called()


class ManualDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_table_and_summary_show_key_count_separately_from_question_count(self):
        source = [keyed_question(1), open_question()]
        db = api.parse_wayground_answers({"questions": source}, include_unkeyed=True)
        page = SimpleNamespace(is_closed=Mock(return_value=False))
        browser = SimpleNamespace(is_connected=Mock(return_value=True))
        args = SimpleNamespace(ai=False, no_ai=True, wrong=1, quiz_input="60685869", answers_url="unused")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), \
                patch.object(app, "configure_ai", new=AsyncMock(return_value=True)), \
                patch.object(app, "retrieve_answers", new=AsyncMock(return_value=(db, "Verified API"))), \
                patch.object(app, "_read_question_counter", new=AsyncMock(return_value=(0, 0))), \
                patch.object(app, "automate_test", new=AsyncMock(return_value=False)), \
                patch.object(app, "clear_screen"), patch.object(app, "print_banner"):
            self.assertIs(await app._run_phases(page, browser, args), False)
        text = captured.getvalue()
        self.assertIn("1 answer keys for 2 questions", text)
        self.assertIn("Written response required", text)
        self.assertNotIn("Target score", text)


if __name__ == "__main__":
    unittest.main()
