"""Startup must work on running games while staying bound to the selected session."""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from answer_db import AnswerDatabase
from desktop_backend import DesktopBackend, game_identifier
from runtime_control import SessionChanged
from session_binding import SessionBinding


class GamePage:
    def __init__(self, url="https://wayground.com/join/game/session-one"):
        self.url = url
        self.info = {"pin": "", "hash": "", "marker": "", "pinSource": "", "hashSource": ""}

    def is_closed(self):
        return False

    async def evaluate(self, script, *args):
        if args:
            self.info["marker"] = args[0]
            return None
        return dict(self.info)

    async def title(self):
        return "Already running test"


def question(qid="q1"):
    return {"_id": qid, "type": "MCQ", "structure": {"query": {"text": "Which is correct?"},
            "options": [{"text": "A"}, {"text": "B"}]}}


class IdentifierTests(unittest.TestCase):
    def test_pin_link_preserves_leading_zeroes(self):
        self.assertEqual(game_identifier("https://wayground.com/join?gc=00392749", "https://wayground.com/join/game/session"),
                         ("00392749", ""))

    def test_supported_game_code_and_hash_parameters(self):
        self.assertEqual(game_identifier("https://quizizz.com/join?roomCode=12345678", "https://quizizz.com/join"), ("12345678", ""))
        self.assertEqual(game_identifier("https://wayground.com/join?roomHash=known-room-hash", "https://wayground.com/join"), ("", "known-room-hash"))

    def test_encrypted_selected_game_url_is_not_an_api_hash(self):
        url = "https://wayground.com/join/game/U2FsdGVkX19encrypted"
        self.assertEqual(game_identifier(url, url), ("", ""))

    def test_other_running_game_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "selected tab"):
            game_identifier("https://wayground.com/join/game/other-session", "https://wayground.com/join/game/chosen-session")

    def test_teacher_url_and_foreign_host_are_rejected(self):
        for value in ("https://wayground.com/activity/admin/quiz/68862510ed25b6e4a794a2d5", "https://fake.wayground.com/join?gc=12345678"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "game PIN or game link"):
                game_identifier(value, "https://wayground.com/join")


class RouteFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_route_change_keeps_same_pin_and_session(self):
        page = GamePage("https://wayground.com/join/game/session-one?gc=12345678")
        page.info.update(pin="12345678", pinSource="url")
        binding = await SessionBinding.create(page, pin="12345678")
        page.url = "https://wayground.com/join/assessment/session-one?gc=12345678"
        await binding.validate()
        self.assertEqual(binding.route[1], "/join/assessment/session-one")

    async def test_session_token_preserves_identity_when_pin_hidden(self):
        page = GamePage()
        binding = await SessionBinding.create(page)
        page.url = "https://wayground.com/join/assessment/session-one"
        await binding.validate()

    async def test_different_token_is_rejected_even_with_stale_matching_pin(self):
        page = GamePage()
        page.info.update(pin="12345678", pinSource="referrer")
        binding = await SessionBinding.create(page, pin="12345678")
        page.url = "https://wayground.com/join/game/session-two"
        with self.assertRaises(SessionChanged):
            await binding.validate()

    async def test_lobby_full_navigation_can_enter_same_identified_game(self):
        page = GamePage("https://wayground.com/join?gc=12345678")
        page.info.update(pin="12345678", pinSource="url")
        binding = await SessionBinding.create(page, pin="12345678")
        page.url = "https://wayground.com/join/game/session-one?gc=12345678"
        page.info["marker"] = ""
        await binding.validate()
        self.assertEqual(page.info["marker"], binding.marker)

    async def test_stored_or_referrer_pin_cannot_authorize_a_new_document(self):
        for source in ("storage", "referrer"):
            page = GamePage("https://wayground.com/join?gc=12345678")
            page.info.update(pin="12345678", pinSource=source)
            binding = await SessionBinding.create(page, pin="12345678")
            page.url = "https://wayground.com/join/game/new-game"
            page.info["marker"] = ""
            with self.subTest(source=source), self.assertRaises(SessionChanged):
                await binding.validate()

    async def test_captured_room_proves_lobby_transition_with_hidden_pin(self):
        page = GamePage("https://wayground.com/join")
        binding = await SessionBinding.create(page, pin="12345678", room_hash="known-room-hash")
        page.url = "https://wayground.com/join/assessment/session-one"
        await binding.validate(captured={"hash": "known-room-hash", "pin": "12345678"})

    async def test_full_reload_of_active_game_requires_repreparation(self):
        page = GamePage()
        binding = await SessionBinding.create(page, pin="12345678")
        page.info.update(marker="", pin="12345678", pinSource="url")
        with self.assertRaisesRegex(SessionChanged, "reloaded"):
            await binding.validate()

    async def test_discovered_room_identity_is_frozen_for_later_changes(self):
        page = GamePage()
        binding = await SessionBinding.create(page)
        await binding.validate(captured={"hash": "known-room-hash"})
        self.assertEqual(binding.room_hash, "known-room-hash")
        with self.assertRaisesRegex(SessionChanged, "session changed"):
            await binding.validate(captured={"hash": "different-room-hash"})


class StartupFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.backend = DesktopBackend(self.events.append)
        self.addCleanup(self.backend.loop.close)
        self.page = GamePage()
        self.backend.pages["tab"] = self.page
        self.snapshot = {"pin": "12345678", "hash": "known-room-hash", "name": "Chosen game", "questions": [question()]}
        self.keys = AnswerDatabase()
        self.keys.add_question("Which is correct?", ["A"], qid="q1", options=[{"text": "A"}, {"text": "B"}])
        self.counter = AsyncMock(return_value=(0, 0))
        self.current = AsyncMock(return_value={"qid": "q1", "text": "Which is correct?"})
        for name, replacement in (("_read_question_counter", self.counter), ("_extract_question_info", self.current),
                                   ("probe", AsyncMock(return_value=(True, "Test answer received"))),
                                   ("apply_engine", Mock())):
            patcher = patch("desktop_backend." + name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def prepare(self, mode="ai", **kwargs):
        await self.backend._prepare("tab", mode=mode, cheatnetwork=False, **kwargs)
        return next(event for event in reversed(self.events) if event["type"] == "prepared")

    async def test_ai_only_needs_no_identifier_manifest_or_total(self):
        with patch("desktop_backend.api.fetch_game_snapshot") as snapshot, patch("desktop_backend.api.fetch_game_answers") as keys:
            event = await self.prepare()
        snapshot.assert_not_called()
        keys.assert_not_called()
        self.assertTrue(event["can_start"])
        self.assertEqual(event["total"], 0)
        self.assertEqual(event["key_count"], 0)
        self.assertFalse(event["complete"])

    async def test_failed_api_does_not_block_ai_only_without_total(self):
        with patch("desktop_backend.api.fetch_game_snapshot", side_effect=ValueError("Expired PIN")):
            event = await self.prepare(pin="12345678")
        self.assertTrue(event["can_start"])
        self.assertEqual(event["total"], 0)
        self.assertTrue(any(event["type"] == "log" for event in self.events))

    async def test_ai_only_ignores_previous_game_identifiers_from_storage_or_referrer(self):
        self.page.info.update(pin="99999999", pinSource="referrer", hash="old-room-hash", hashSource="storage")
        with patch("desktop_backend.api.fetch_game_snapshot") as snapshot:
            event = await self.prepare()
        snapshot.assert_not_called()
        self.assertTrue(event["can_start"])
        self.assertEqual(event["pin"], "")

    async def test_running_game_link_is_accepted_without_an_api_identifier(self):
        event = await self.prepare(pin=self.page.url)
        self.assertTrue(event["can_start"])

    async def test_unavailable_ai_still_disables_start(self):
        with patch("desktop_backend.probe", AsyncMock(return_value=(False, "Unavailable"))):
            event = await self.prepare()
        self.assertFalse(event["can_start"])

    async def test_keys_only_without_identifier_still_requires_a_pin(self):
        with self.assertRaisesRegex(ValueError, "game PIN"):
            await self.prepare(mode="keys")

    async def test_active_test_can_check_keys_using_supplied_pin_link(self):
        self.counter.return_value = (8, 10)
        with patch("desktop_backend.api.fetch_game_snapshot", return_value=self.snapshot) as snapshot, \
             patch("desktop_backend.api.fetch_game_answers", return_value=self.keys):
            event = await self.prepare(mode="keys", pin="https://wayground.com/join?gc=12345678")
        snapshot.assert_called_once_with("12345678")
        self.assertTrue(event["can_start"])
        self.assertEqual(event["pin"], "12345678")
        self.assertEqual(event["current"], 8)

    async def test_supplied_pin_cannot_select_an_unrelated_running_test(self):
        self.current.return_value = {"qid": "another-game", "text": "Other question"}
        with patch("desktop_backend.api.fetch_game_snapshot", return_value=self.snapshot), \
             patch("desktop_backend.api.fetch_game_answers") as keys:
            with self.assertRaisesRegex(ValueError, "already running"):
                await self.prepare(mode="keys", pin="12345678")
        keys.assert_not_called()
        self.assertIsNone(self.backend.prepared)

    async def test_pin_from_old_referrer_does_not_override_entered_current_pin(self):
        self.page.info.update(pin="99999999", pinSource="referrer")
        with patch("desktop_backend.api.fetch_game_snapshot", return_value=self.snapshot), \
             patch("desktop_backend.api.fetch_game_answers", return_value=self.keys):
            event = await self.prepare(mode="keys", pin="12345678")
        self.assertTrue(event["can_start"])
        self.assertEqual(event["pin"], "12345678")

    async def test_actual_live_counter_is_emitted_when_starting_mid_test(self):
        self.counter.return_value = (8, 10)
        await self.prepare()
        self.backend.browser = SimpleNamespace(is_connected=lambda: True)
        with patch("desktop_backend.automate_test", AsyncMock(return_value=False)), \
             patch("desktop_backend.clear_highlights", AsyncMock()):
            await self.backend._start_run(delay=0)
            await self.backend.run_task
        event = next(event for event in self.events if event["type"] == "started")
        self.assertEqual((event["current"], event["total"]), (8, 10))

    async def test_network_room_capture_preserves_pin_across_question_responses(self):
        self.backend.captured["tab"] = {"pin": "12345678", "hash": "known-room-hash"}
        response = SimpleNamespace(url="https://wayground.com/play-api/v4/getQuestions", json=AsyncMock(return_value={"questions": []}),
                                   request=SimpleNamespace(post_data_json={"roomHash": "known-room-hash"}))
        await self.backend._capture_response("tab", response)
        self.assertEqual(self.backend.captured["tab"], {"pin": "12345678", "hash": "known-room-hash"})


if __name__ == "__main__":
    unittest.main()
