"""Regression checks for Quizit authentication, supplied keys and browser fallback."""

import asyncio
import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import api
import quizit


PIN = "00355925"
BOT_URL = f"https://api.quizit.online/quizizz/bot?pin={PIN}"
RESULT = {"solved": True, "questions": [{
    "id": "q1", "type": "MCQ", "question": {"text": "<p>Question?</p>"},
    "answers": [{"text": "<p>Correct answer</p>"}],
}]}


class ApiTests(unittest.TestCase):
    def setUp(self):
        api.reset_answer_state()
        self.addCleanup(api.reset_answer_state)
        settings = patch.multiple(api, _allow_quizit_bot=True,
                                  _in_progress_pins=set(), _completed_pins={})
        settings.start()
        self.addCleanup(settings.stop)
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def test_current_result_preserves_ids_and_text_keys(self):
        db = api.parse_quizit_answers(RESULT)
        self.assertEqual(db["id:q1"], ["Correct answer"])
        self.assertEqual(db["Question?"], ["Correct answer"])

    def test_unsolved_result_is_not_treated_as_answer_keys(self):
        with self.assertRaisesRegex(ValueError, "could not retrieve"):
            api.parse_quizit_answers(dict(RESULT, solved=False))

    def test_malformed_questions_are_rejected(self):
        for questions in ({"q1": {}}, [None], [], "questions"):
            with self.subTest(questions=questions), self.assertRaises(Exception):
                api.parse_quizit_answers({"questions": questions})

    def test_unauthorized_sets_login_flag_and_prevents_repeated_anonymous_calls(self):
        error = urllib.error.HTTPError(BOT_URL, 401, "Unauthorized", {}, io.BytesIO())
        with patch.object(api, "fetch_game_answers", side_effect=ValueError("hidden")), \
                patch.object(api.urllib.request, "urlopen", side_effect=error) as request:
            self.assertIsNone(api.fetch_answers_by_any_identifier(PIN)[0])
            self.assertTrue(api.is_quizit_sign_in_required())
            self.assertIsNone(api.fetch_answers_by_any_identifier(PIN)[0])
        self.assertEqual(request.call_count, 1)
        self.assertNotIn(PIN, api._in_progress_pins)
        self.assertNotIn(PIN, api._completed_pins)

    def test_pending_request_is_not_sent_twice(self):
        api._in_progress_pins.add(PIN)
        with patch.object(api.time, "sleep"), patch.object(api.urllib.request, "urlopen") as request:
            with self.assertRaisesRegex(ValueError, "already in progress"):
                api.fetch_quizit_answers(PIN)
        request.assert_not_called()


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        self.sign_in = SimpleNamespace(is_visible=AsyncMock(return_value=False))
        self.field = SimpleNamespace(fill=AsyncMock())
        self.button = SimpleNamespace(click=AsyncMock())
        self.method = SimpleNamespace(inner_text=AsyncMock(return_value="Standard"), click=AsyncMock())
        self.option = SimpleNamespace(click=AsyncMock())
        self.response = SimpleNamespace(url=BOT_URL, status=200, json=AsyncMock(return_value=RESULT))
        future = asyncio.get_running_loop().create_future()
        future.set_result(self.response)
        response_context = MagicMock()
        response_context.__aenter__ = AsyncMock(return_value=SimpleNamespace(value=future))
        response_context.__aexit__ = AsyncMock(return_value=False)

        def locator(role, **kwargs):
            return {"link": self.sign_in, "textbox": self.field, "button": self.button,
                    "combobox": self.method, "option": self.option}[role]

        self.page = SimpleNamespace(
            url="about:blank", is_closed=lambda: False,
            goto=AsyncMock(), wait_for_url=AsyncMock(), close=AsyncMock(),
            get_by_role=MagicMock(side_effect=locator),
            expect_response=MagicMock(return_value=response_context),
        )
        self.context = SimpleNamespace(pages=[], new_page=AsyncMock(return_value=self.page))

    async def test_signed_in_flow_captures_site_request_and_closes_owned_result_tab(self):
        db = await quizit.fetch_quizit_browser_answers(self.context, PIN)
        self.assertEqual(db["id:q1"], ["Correct answer"])
        self.field.fill.assert_awaited_once_with(PIN)
        self.button.click.assert_awaited_once()
        self.page.close.assert_awaited_once()
        predicate = self.page.expect_response.call_args.args[0]
        self.assertTrue(predicate(self.response))
        self.assertEqual(self.page.expect_response.call_args.kwargs["timeout"], 35000)

    async def test_user_sign_in_retries_using_normal_site_button(self):
        self.sign_in.is_visible.side_effect = [True, False]
        with patch("builtins.input", return_value="") as prompt:
            db = await quizit.fetch_quizit_browser_answers(self.context, PIN)
        self.assertTrue(db)
        self.page.wait_for_url.assert_awaited_once_with("**/auth/login**", timeout=10000)
        self.assertEqual(self.button.click.await_count, 2)
        prompt.assert_called_once()

    async def test_skipped_login_sends_no_authenticated_request_and_keeps_login_tab(self):
        self.sign_in.is_visible.return_value = True
        with patch("builtins.input", return_value="s"):
            self.assertIsNone(await quizit.fetch_quizit_browser_answers(self.context, PIN))
        self.page.expect_response.assert_not_called()
        self.page.close.assert_not_awaited()

    async def test_incomplete_login_does_not_retry(self):
        self.sign_in.is_visible.return_value = True
        with patch("builtins.input", return_value=""):
            self.assertIsNone(await quizit.fetch_quizit_browser_answers(self.context, PIN))
        self.page.expect_response.assert_not_called()

    async def test_existing_tab_is_preserved(self):
        self.page.url = quizit.QUIZIT_URL
        self.context.pages = [self.page]
        self.assertTrue(await quizit.fetch_quizit_browser_answers(self.context, PIN))
        self.context.new_page.assert_not_awaited()
        self.page.goto.assert_not_awaited()
        self.page.close.assert_not_awaited()

    async def test_ai_selection_is_changed_to_standard(self):
        self.method.inner_text.return_value = "Undetectable (no bot)"
        self.assertTrue(await quizit.fetch_quizit_browser_answers(self.context, PIN))
        self.method.click.assert_awaited_once()
        self.option.click.assert_awaited_once()

    async def test_expired_session_or_service_error_is_not_parsed(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                self.response.status = status
                self.assertIsNone(await quizit.fetch_quizit_browser_answers(self.context, PIN))
        self.response.json.assert_not_awaited()

    async def test_unsolved_response_does_not_return_keys(self):
        self.response.json.return_value = dict(RESULT, solved=False)
        self.assertIsNone(await quizit.fetch_quizit_browser_answers(self.context, PIN))

    async def test_response_filter_rejects_other_games_and_domains(self):
        for url in (BOT_URL.replace(PIN, "123456"), BOT_URL.replace("api.quizit.online", "other.example"),
                    BOT_URL.replace("/bot", "/questions")):
            with self.subTest(url=url):
                self.assertFalse(quizit._matches_bot_response(SimpleNamespace(url=url), PIN))

    async def test_pin_resolution_preserves_zeroes_and_prefers_manual_input(self):
        self.page.url = "https://wayground.com/join/game/encrypted-session"
        with patch.object(quizit, "extract_identifiers_from_page") as extract:
            self.assertEqual(await quizit.resolve_quizit_pin(self.page, PIN, "123456"), PIN)
        extract.assert_not_called()

    async def test_encrypted_session_uses_captured_pin(self):
        self.page.url = "https://wayground.com/join/game/encrypted-session"
        with patch.object(quizit, "get_discovered_pin", return_value=None), \
                patch.object(quizit, "extract_identifiers_from_page", new=AsyncMock(return_value={"pin": PIN})):
            self.assertEqual(await quizit.resolve_quizit_pin(self.page), PIN)


if __name__ == "__main__":
    unittest.main()
