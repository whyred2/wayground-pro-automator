"""Offline regression checks for direct game retrieval and captured answer keys."""

import asyncio
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import api


PIN = "62021302"
ROOM_HASH = "6a97f663c066154e1288665f"
QUIZ_ID = "646ee67e6f3311001ecb7f8f"
LINK = f"https://wayground.com/join?gc={PIN}&source=liveDashboard"


def question(qid="q1", answer=0, text="Question?", kind="MCQ"):
    return {"_id": qid, "type": kind, "structure": {
        "query": {"text": text, "media": []},
        "options": [{"text": "First"}, {"text": "Second"}, {"text": "Third"}],
        "answer": answer,
    }}


def hidden_question(**kwargs):
    q = question(**kwargs)
    del q["structure"]["answer"]
    return q


def blank_question(texts=("technical writing",), target_ids=("blank-1",)):
    options = [{"id": f"option-{index}", "text": text} for index, text in enumerate(texts)]
    return {"_id": "blank-q", "type": "BLANK", "ver": 4, "structure": {
        "kind": "BLANK", "query": {"text": "Definition " + " ".join(
            f'<blank id="{target_id}"></blank>' for target_id in target_ids), "media": []},
        "options": options,
        "targets": [{"id": target_id, "optionId": [options[index]["id"]]}
                    for index, target_id in enumerate(target_ids)],
        "answer": [{"targetId": target_id, "optionId": [options[index]["id"]]}
                   for index, target_id in enumerate(target_ids)],
    }}


class ParsingTests(unittest.TestCase):
    def test_zero_index_in_quizserver_response(self):
        db = api.parse_wayground_answers({"data": {"quiz": {"info": {
            "questions": [question(text="<p>Question&nbsp;one</p>")]
        }}}})
        self.assertEqual(db["Question one"], ["First"])
        self.assertEqual(db["id:q1"], ["First"])

    def test_game_question_map_preserves_map_ids(self):
        q = question(answer=[0, 2], kind="MSQ")
        del q["_id"]
        db = api.parse_wayground_answers({"questions": {"game-qid": q}})
        self.assertEqual(db["id:game-qid"], ["First", "Third"])

    def test_fib_text_and_numeric_text_are_literal_answers(self):
        db = api.parse_wayground_answers({"questions": [
            question("fib", answer=["<p>business writing</p>", "42"], kind="FIB")
        ]})
        self.assertEqual(db["id:fib"], ["business writing", "42"])

    def test_hidden_answers_are_not_guessed_from_options(self):
        q = question()
        del q["structure"]["answer"]
        self.assertEqual(api.parse_wayground_answers({"questions": {"q1": q}}), {})

    def test_invalid_answer_values_do_not_select_first_option(self):
        for answer in (None, False, -1, 50, {}, [None, {}, -1]):
            with self.subTest(answer=answer):
                self.assertEqual(api.parse_wayground_answers({"questions": [question(answer=answer)]}), {})

    def test_placeholder_room_questions_do_not_hide_quiz_questions(self):
        db = api.parse_wayground_answers({"room": {"questions": ["", ""]},
                                          "quiz": {"info": {"questions": [question()]}}})
        self.assertEqual(db["id:q1"], ["First"])

    def test_option_images_and_question_image_aliases(self):
        q = question(answer=[0, 1], text="")
        q["structure"]["query"]["media"] = [{"url": "https://example.org/query.png?v=1"}]
        q["structure"]["options"][1] = {"media": [{"url": "https://example.org/answer.png?v=1"}]}
        db = api.parse_wayground_answers({"questions": [q]})
        self.assertEqual(db["img:query.png"], ["First", "answer.png"])

    def test_each_blank_option_keeps_its_index_fallback(self):
        q = question(answer=[0, 1])
        q["structure"]["options"] = [{}, {}]
        self.assertEqual(api.parse_wayground_answers({"questions": [q]})["id:q1"],
                         ["option-0", "index:0", "option-1", "index:1"])

    def test_duplicate_wording_keeps_distinct_question_ids(self):
        db = api.parse_wayground_answers({"questions": [question("a", 0), question("b", 1)]})
        self.assertEqual(db["id:a"], ["First"])
        self.assertEqual(db["id:b"], ["Second"])

    def test_malformed_media_does_not_drop_other_answers(self):
        q = question()
        q["structure"]["query"]["media"] = 5
        q["structure"]["options"][0]["media"] = None
        self.assertEqual(api.parse_wayground_answers({"questions": [q]})["id:q1"], ["First"])

    def test_blank_resolves_explicit_target_option_ids(self):
        db = api.parse_wayground_answers({"questions": [blank_question()]})
        self.assertEqual(db["id:blank-q"], ["technical writing"])

    def test_blank_numeric_text_is_literal_and_alternatives_are_one_input(self):
        q = blank_question(texts=("42", "forty-two"))
        q["structure"]["answer"][0]["optionId"].append("option-1")
        q["structure"]["targets"][0]["optionId"].append("option-1")
        self.assertEqual(api.parse_wayground_answers({"questions": [q]})["id:blank-q"], ["42"])

    def test_multiple_blanks_follow_query_order_and_keep_repeated_answers(self):
        for texts in (("technical", "writing"), ("same", "same")):
            with self.subTest(texts=texts):
                q = blank_question(texts=texts, target_ids=("first", "second"))
                q["structure"]["targets"].reverse()
                q["structure"]["answer"].reverse()
                db = api.parse_wayground_answers({"questions": [q]})
                self.assertEqual(db["id:blank-q"], list(texts))
                self.assertEqual(db["Definition"], list(texts))

    def test_unknown_or_conflicting_blank_references_are_not_guessed(self):
        for change in (
            lambda q: q["structure"]["answer"][0].update(optionId=["missing"]),
            lambda q: q["structure"]["answer"][0].update(targetId="missing"),
            lambda q: q["structure"].update(answer=[]),
            lambda q: q["structure"]["targets"][0].update(optionId=["different"]),
        ):
            with self.subTest(change=change):
                q = blank_question()
                change(q)
                self.assertEqual(api.parse_wayground_answers({"questions": [q]}), {})


class DirectRetrievalTests(unittest.TestCase):
    def setUp(self):
        api.reset_answer_state()
        self.addCleanup(api.reset_answer_state)
        self.bot_setting = patch.object(api, "_allow_quizit_bot", True)
        self.bot_setting.start()
        self.addCleanup(self.bot_setting.stop)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_pin_uses_check_room_then_get_questions(self):
        with patch.object(api, "_request_json", side_effect=[
            {"room": {"hash": ROOM_HASH, "questions": [""]}},
            {"questions": {"q1": question()}},
        ]) as request:
            self.assertEqual(api.fetch_game_answers(PIN)["id:q1"], ["First"])
        self.assertEqual(request.call_args_list[0].args,
                         ("https://wayground.com/play-api/v5/checkRoom", {"roomCode": PIN}))
        self.assertEqual(request.call_args_list[1].args,
                         ("https://wayground.com/play-api/v4/getQuestions", {"roomHash": ROOM_HASH}))

    def test_room_hash_does_not_join_a_player(self):
        with patch.object(api, "_request_json", return_value={"questions": [question()]}) as request:
            api.fetch_game_answers(ROOM_HASH)
        self.assertEqual(request.call_count, 1)
        self.assertIn("/getQuestions", request.call_args.args[0])

    def test_answers_in_check_room_need_no_extra_request(self):
        with patch.object(api, "_request_json", return_value={"room": {"questions": [question()]}}) as request:
            self.assertTrue(api.fetch_game_answers(PIN))
        self.assertEqual(request.call_count, 1)

    def test_hidden_game_keys_report_question_count(self):
        with patch.object(api, "_request_json", return_value={"questions": [hidden_question()]}), \
                patch.object(api, "_game_resource_metadata", return_value={}):
            with self.assertRaisesRegex(ValueError, "1 questions.*no supported answer keys"):
                api.fetch_game_answers(ROOM_HASH)

    def test_public_quiz_fallback_when_game_keys_are_hidden(self):
        with patch.object(api, "_request_json", return_value={"questions": [hidden_question()]}), \
                patch.object(api, "_game_resource_metadata", return_value={"quiz_id": QUIZ_ID}), \
                patch.object(api, "_fetch_quiz_payload", return_value={"questions": [question()]}) as quiz:
            self.assertEqual(api.fetch_game_answers(ROOM_HASH)["id:q1"], ["First"])
        quiz.assert_called_once_with(QUIZ_ID)

    def test_failed_public_quiz_still_tries_library_search(self):
        with patch.object(api, "_request_json", return_value={"questions": [hidden_question()]}), \
                patch.object(api, "_game_resource_metadata", return_value={"quiz_id": QUIZ_ID, "name": "Title"}), \
                patch.object(api, "_fetch_quiz_payload", side_effect=ValueError("private")), \
                patch.object(api, "_fetch_library_answers", return_value={"id:q1": ["First"]}) as library:
            self.assertTrue(api.fetch_game_answers(ROOM_HASH))
        library.assert_called_once_with("Title", [hidden_question()])

    def test_pin_with_opaque_quiz_id_resolves_verified_public_source(self):
        opaque_id = "a" * 64
        with patch.object(api, "_request_json", side_effect=[
            {"room": {"hash": ROOM_HASH, "quizId": opaque_id}},
            {"questions": [hidden_question()]},
            {"data": {"items": [{"_id": ROOM_HASH, "quizId": opaque_id}],
                      "quizzes": {opaque_id: {"name": "Title"}}}},
            {"data": {"hits": [{"quizId": QUIZ_ID, "name": "Title", "noOfQuestions": 1}]}},
            {"data": {"quiz": {"info": {"questions": [question()]}}}},
        ]) as request:
            self.assertEqual(api.fetch_game_answers(PIN)["id:q1"], ["First"])
        self.assertEqual(request.call_count, 5)
        self.assertIn("/search/public", request.call_args_list[3].args[0])
        self.assertIn(QUIZ_ID, request.call_args_list[4].args[0])

    def test_direct_success_does_not_call_quizit(self):
        with patch.object(api, "fetch_game_answers", return_value={"id:q1": ["First"]}) as game, \
                patch.object(api, "fetch_quizit_answers") as bot:
            db, source = api.fetch_answers_by_any_identifier(LINK)
        game.assert_called_once_with(PIN)
        bot.assert_not_called()
        self.assertTrue(db)
        self.assertIn("Wayground Game API", source)

    def test_quizit_fallback_runs_after_direct_failure(self):
        order = []
        def direct(_):
            order.append("direct")
            raise ValueError("hidden")
        def fallback(_):
            order.append("bot")
            return {"id:q1": ["First"]}
        with patch.object(api, "fetch_game_answers", side_effect=direct), \
                patch.object(api, "fetch_quizit_answers", side_effect=fallback):
            self.assertTrue(api.fetch_answers_by_any_identifier(PIN)[0])
        self.assertEqual(order, ["direct", "bot"])

    def test_no_bot_setting_still_uses_direct_api(self):
        with patch.object(api, "_allow_quizit_bot", False), \
                patch.object(api, "fetch_game_answers", side_effect=ValueError("hidden")) as game, \
                patch.object(api, "fetch_quizit_answers") as bot:
            self.assertIsNone(api.fetch_answers_by_any_identifier(LINK)[0])
        game.assert_called_once_with(PIN)
        bot.assert_not_called()

    def test_opaque_quiz_id_is_rejected_before_network(self):
        with patch.object(api, "_request_json") as request:
            with self.assertRaises(ValueError):
                api.fetch_api_answers("a" * 64)
        request.assert_not_called()

    def test_urls_and_leading_zero_pins(self):
        cases = {
            "https://wayground.com/join?gc=00355925": ("pin", "00355925"),
            f"https://wayground.com/join/quiz/{QUIZ_ID}/start": ("quiz", QUIZ_ID),
            f"https://wayground.com/join?quizId={QUIZ_ID}": ("quiz", QUIZ_ID),
            "https://wayground.com/join/game/U2FsdGVkX19foo62021302": ("", ""),
            "https://example.org/wayground.com?gc=62021302": ("", ""),
            "some 1234 random 5678 text": ("", ""),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(api._classify_identifier(value), expected)


class LibraryVerificationTests(unittest.TestCase):
    def setUp(self):
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_subset_returns_only_game_question_keys(self):
        db = api._verified_quiz_answers([hidden_question(qid="q2")],
                                       {"questions": [question(), question(qid="q2", answer=1)]})
        self.assertEqual(db["id:q2"], ["Second"])
        self.assertNotIn("id:q1", db)

    def test_blank_options_hidden_by_game_are_verified_using_unchanged_targets(self):
        source = blank_question()
        game = copy.deepcopy(source)
        game["structure"]["options"] = []
        del game["structure"]["answer"]
        self.assertEqual(api._verified_quiz_answers([game], {"questions": [source]})["id:blank-q"],
                         ["technical writing"])

    def test_hidden_blank_requires_matching_targets_and_question_version(self):
        source = blank_question()
        for change in (
            lambda q: q["structure"]["targets"][0].update(optionId=["edited-option"]),
            lambda q: q["structure"].update(targets=[]),
            lambda q: q.update(ver=5),
        ):
            with self.subTest(change=change):
                game = copy.deepcopy(source)
                game["structure"]["options"] = []
                del game["structure"]["answer"]
                change(game)
                self.assertEqual(api._verified_quiz_answers([game], {"questions": [source]}), {})

    def test_hidden_multiple_choice_options_still_reject_library_keys(self):
        game = hidden_question()
        game["structure"]["options"] = []
        self.assertEqual(api._verified_quiz_answers([game], {"questions": [question()]}), {})

    def test_changed_content_or_options_rejects_even_matching_ids(self):
        original = question()
        changes = [
            lambda q: q["structure"]["query"].update(text="Edited question?"),
            lambda q: q["structure"]["options"].reverse(),
            lambda q: q["structure"]["query"]["media"].append({"url": "different.png"}),
            lambda q: q.update(type="MSQ"),
            lambda q: q["structure"].update(kind="MSQ"),
        ]
        for change in changes:
            with self.subTest(change=change):
                source = copy.deepcopy(original)
                change(source)
                self.assertEqual(api._verified_quiz_answers([hidden_question()], {"questions": [source]}), {})

    def test_missing_ids_missing_keys_and_duplicate_ids_are_rejected(self):
        for source in ([question(qid="different")], [hidden_question()], [question(), question(answer=1)]):
            with self.subTest(source=source):
                self.assertEqual(api._verified_quiz_answers([hidden_question()], {"questions": source}), {})
        self.assertEqual(api._verified_quiz_answers([hidden_question(), hidden_question()],
                                                   {"questions": [question()]}), {})

    def test_same_title_is_insufficient_and_search_continues_to_verified_source(self):
        wrong_id = "b" * 24
        with patch.object(api, "_search_public_quizzes", return_value=[
            {"quizId": wrong_id, "name": "Title", "noOfQuestions": 1},
            {"quizId": QUIZ_ID, "name": "Title", "noOfQuestions": 1},
        ]), patch.object(api, "_fetch_quiz_payload", side_effect=[
            {"questions": [question(qid="wrong")]}, {"questions": [question()]},
        ]) as fetch:
            self.assertEqual(api._fetch_library_answers("Title", [hidden_question()])["id:q1"], ["First"])
        self.assertEqual([call.args[0] for call in fetch.call_args_list], [wrong_id, QUIZ_ID])

    def test_library_candidate_requests_are_bounded_and_deduplicated(self):
        candidates = [{"quizId": f"{i:024x}", "name": "Title", "noOfQuestions": 1} for i in range(6)]
        candidates.insert(1, dict(candidates[0]))
        candidates.insert(0, {"quizId": "not-an-id", "name": "Title"})
        with patch.object(api, "_search_public_quizzes", return_value=candidates), \
                patch.object(api, "_fetch_quiz_payload", side_effect=ValueError("unavailable")) as fetch:
            self.assertEqual(api._fetch_library_answers("Title", [hidden_question()]), {})
        self.assertEqual(fetch.call_count, 5)
        self.assertEqual(len({call.args[0] for call in fetch.call_args_list}), 5)

    def test_public_search_uses_anonymous_session_and_quiz_filter(self):
        with patch.object(api, "_request_json", return_value={"data": {"hits": [{"quizId": QUIZ_ID}, None]}}) as request:
            self.assertEqual(api._search_public_quizzes("Title"), [{"quizId": QUIZ_ID}])
        url, payload, headers = request.call_args.args
        self.assertIn("/v3/search/public", url)
        self.assertEqual(payload["query"], "Title")
        self.assertEqual(payload["filters"], {"contentTypes": ["quiz"]})
        self.assertEqual(headers, {"X-Q-Sessionid": payload["sessionId"]})


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        api.reset_answer_state()
        self.addCleanup(api.reset_answer_state)

    def response(self, body, post=None, url="https://wayground.com/play-api/v4/getQuestions"):
        return SimpleNamespace(url=url, status=200,
                               headers={"content-type": "application/json"},
                               request=SimpleNamespace(method="POST", post_data=json.dumps(post) if post else None),
                               json=AsyncMock(return_value=body))

    async def test_capture_answers_even_after_pin_discovered(self):
        api._discovered_pin = PIN
        await api.intercept_response(self.response({"questions": {"q1": question()}}))
        self.assertEqual(api._cached_answers_db["id:q1"], ["First"])

    async def test_capture_multiple_responses_without_spawning_bot(self):
        with patch.object(api, "fetch_quizit_answers") as bot:
            await api.intercept_response(self.response({"questions": [question("a")]}, {"roomCode": PIN}))
            await api.intercept_response(self.response({"questions": [question("b", 1)]}))
        self.assertEqual(api._cached_answers_db["id:a"], ["First"])
        self.assertEqual(api._cached_answers_db["id:b"], ["Second"])
        bot.assert_not_called()

    async def test_discover_room_when_keys_are_hidden(self):
        await api.intercept_response(self.response({"room": {"hash": ROOM_HASH, "questions": [""]}},
                                                   {"roomCode": PIN}))
        self.assertEqual(api._discovered_pin, PIN)
        self.assertEqual(api._discovered_hash, ROOM_HASH)
        self.assertFalse(api._answers_ready_event.is_set())

    async def test_pin_url_and_dom_are_not_retried_repeatedly(self):
        page = SimpleNamespace(url=LINK)
        with patch.object(api, "extract_identifiers_from_page", new=AsyncMock(return_value={"pin": PIN, "hash": ROOM_HASH})), \
                patch.object(api, "fetch_answers_by_any_identifier", return_value=(None, "")) as fetch:
            self.assertIsNone((await api.retrieve_answers(page, quiz_input=PIN, timeout=0.01))[0])
        fetch.assert_called_once_with(PIN)

    async def test_reset_clears_previous_test_answers(self):
        await api.intercept_response(self.response({"questions": [question()]}))
        api.reset_answer_state()
        self.assertIsNone(api._cached_answers_db)
        self.assertFalse(api._answers_ready_event.is_set())


if __name__ == "__main__":
    unittest.main()
