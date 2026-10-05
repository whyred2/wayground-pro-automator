"""Offline checks that failed AI requests never fabricate answer predictions."""

import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ai_solver
import config


OPTIONS = [{"text": "alpha"}, {"text": "beta"}, {"text": "gamma"}]


class AnswerParsingTests(unittest.TestCase):
    def test_mcq_invalid_output_has_no_prediction(self):
        for raw in (
            "", "No answer available", "Service returned 2 errors", "{}",
            '{"reasoning":"Option 1 and B need further analysis"}',
            '{"selected_indices":[]}', '{"selected_indices":[99]}',
            '{"selected_indices":[true]}', '{"selected_indices":[1,99]}',
            '{"selected_indices":[1,2]}', '{"selected_indices":[1',
        ):
            with self.subTest(raw=raw):
                self.assertEqual(ai_solver._parse_ai_response(raw, 3, False, OPTIONS)[0], [])

    def test_mcq_explicit_first_choice_is_preserved(self):
        for raw in ('{"selected_indices":[1]}', '{"selected_indices":[0]}',
                    '{"answer":"A"}', '{"answer":"alpha"}', 'Answer: A', '1'):
            with self.subTest(raw=raw):
                self.assertEqual(ai_solver._parse_ai_response(raw, 3, False, OPTIONS)[0], [0])

    def test_mcq_markdown_json_and_msq_are_preserved(self):
        self.assertEqual(ai_solver._parse_ai_response(
            '```json\n{"selected_indices":[2],"reasoning":"valid"}\n```', 3, False, OPTIONS
        ), ([1], "valid"))
        self.assertEqual(ai_solver._parse_ai_response(
            '{"selected_indices":[3,1,3]}', 3, True, OPTIONS
        )[0], [2, 0])
        self.assertEqual(ai_solver._parse_ai_response('Answer: A, C', 3, True, OPTIONS)[0], [0, 2])

    def test_mcq_empty_or_ambiguous_option_text_does_not_match(self):
        self.assertEqual(ai_solver._parse_candidate_indices(
            "unrecognized", 2, [{"text": ""}, {"text": "known"}]
        ), [])
        self.assertEqual(ai_solver._parse_candidate_indices(
            "same", 2, [{"text": "same"}, {"text": "same"}]
        ), [])
        self.assertEqual(ai_solver._parse_candidate_indices("alp", 3, OPTIONS), [])

    def test_fib_invalid_output_has_no_prediction(self):
        for raw in (
            "", "No answer available", "yes", "{}", '{"reasoning":"unsure"}',
            '{"answer":null}', '{"answer":true}', '{"answers":[null]}',
            '{"answers":[{"text":"yes"}]}', '{"answers":[""]}',
            '{"answer":"yes"', '{"answer":NaN}', '{"answer":Infinity}',
        ):
            with self.subTest(raw=raw):
                self.assertEqual(ai_solver._parse_fib_response(raw)[:2], ([], []))

    def test_fib_explicit_yes_and_numeric_zero_are_preserved(self):
        for raw, expected in (( '{"answer":"yes"}', "yes"), ('"yes"', "yes"),
                              ('{"answer":0}', "0")):
            with self.subTest(raw=raw):
                answers, wrongs, _ = ai_solver._parse_fib_response(raw)
                self.assertEqual(answers, [expected])
                self.assertEqual(len(wrongs), 1)
                self.assertNotEqual(wrongs[0], expected)

    def test_fib_incomplete_answers_are_not_repeated(self):
        for raw in ('{"answer":"yes"}', '{"answers":["yes", ""]}',
                    '{"answers":["yes", null]}', '{"answers":["yes","no","maybe"]}'):
            with self.subTest(raw=raw):
                self.assertEqual(ai_solver._parse_fib_response(raw, 2)[:2], ([], []))

    def test_fib_repeated_explicit_answers_and_wrongs_are_preserved(self):
        self.assertEqual(ai_solver._parse_fib_response(
            '{"answers":["yes","yes"],"plausible_wrongs":["no","no"],"reasoning":"valid"}', 2
        ), (["yes", "yes"], ["no", "no"], "valid"))


class SolverFailureTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.multiple(
            config, AI_API_KEY="", AI_MODEL="test-model", AI_GATEWAY_MODEL="",
            AI_API_BASE="https://direct.example/v1", AI_GATEWAY_URL="",
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        self.sleep = patch("ai_solver.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def make_client(self, content=None, error=None, no_choices=False):
        client = MagicMock()
        if error:
            client.chat.completions.create.side_effect = error
        else:
            choices = [] if no_choices else [SimpleNamespace(message=SimpleNamespace(content=content))]
            client.chat.completions.create.return_value = SimpleNamespace(choices=choices)
        return client

    def gateway_response(self, payload):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return response

    def assert_empty_predictions(self, mcq_kwargs=None, fib_kwargs=None):
        self.assertEqual(ai_solver.solve_question_with_ai("Q", OPTIONS, **(mcq_kwargs or {}))[0], [])
        self.assertEqual(ai_solver.solve_fib_with_ai("Q", **(fib_kwargs or {}))[:2], ([], []))

    def test_missing_configuration_returns_no_prediction(self):
        with patch("ai_solver.get_ai_client") as sdk, patch("ai_solver.urllib.request.urlopen") as network:
            self.assert_empty_predictions()
        sdk.assert_not_called()
        network.assert_not_called()

    def test_gateway_network_failure_returns_no_prediction(self):
        with patch.object(config, "AI_GATEWAY_URL", "https://gateway.example"), \
                patch("ai_solver.urllib.request.urlopen", side_effect=OSError("offline")):
            self.assert_empty_predictions()

    def test_gateway_missing_answers_do_not_default(self):
        for payload in ({}, {"reasoning": "unsure"}, {"selected_indices": [99]},
                        {"answers": [None]}, {"answer": ""}):
            with self.subTest(payload=payload), \
                    patch.object(config, "AI_GATEWAY_URL", "https://gateway.example"), \
                    patch("ai_solver.urllib.request.urlopen", return_value=self.gateway_response(payload)):
                self.assert_empty_predictions()

    def test_gateway_incomplete_fib_is_rejected(self):
        with patch.object(config, "AI_GATEWAY_URL", "https://gateway.example"), \
                patch("ai_solver.urllib.request.urlopen", return_value=self.gateway_response({"answers": ["yes"]})):
            self.assertEqual(ai_solver.solve_fib_with_ai("Q", num_blanks=2)[:2], ([], []))

    def test_gateway_explicit_answers_are_preserved(self):
        for index in (0, 1):
            with self.subTest(index=index), patch("ai_solver.urllib.request.urlopen", return_value=self.gateway_response(
                {"selected_indices": [index]}
            )):
                self.assertEqual(ai_solver._solve_via_gateway_mcq("https://gateway.example", "Q", OPTIONS)[0], [0])
        with patch("ai_solver.urllib.request.urlopen", return_value=self.gateway_response({"answer": "yes"})):
            self.assertEqual(ai_solver._solve_via_gateway_fib("https://gateway.example", "Q")[0], ["yes"])

    def test_direct_empty_choices_return_no_prediction(self):
        with patch.object(config, "AI_API_KEY", "test-key"), \
                patch("ai_solver.get_ai_client", return_value=self.make_client(no_choices=True)):
            self.assert_empty_predictions()

    def test_direct_malformed_choices_return_no_prediction(self):
        with patch.object(config, "AI_API_KEY", "test-key"), \
                patch("ai_solver.get_ai_client", return_value=self.make_client(content="Service returned 2 errors")):
            self.assert_empty_predictions()

    def test_direct_request_failures_return_no_prediction(self):
        client = self.make_client(error=RuntimeError("request failed"))
        with patch.object(config, "AI_API_KEY", "test-key"), patch("ai_solver.get_ai_client", return_value=client):
            self.assert_empty_predictions(mcq_kwargs={"max_retries": 0}, fib_kwargs={"max_retries": 0})
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_direct_client_initialization_failure_returns_no_prediction(self):
        with patch.object(config, "AI_API_KEY", "test-key"), \
                patch("ai_solver.get_ai_client", side_effect=RuntimeError("bad client")):
            self.assert_empty_predictions()

    def test_gateway_failure_can_use_explicit_direct_answers(self):
        client = self.make_client(content='{"selected_indices":[1],"answer":"yes"}')
        with patch.multiple(config, AI_API_KEY="test-key", AI_GATEWAY_URL="https://gateway.example"), \
                patch("ai_solver.urllib.request.urlopen", side_effect=OSError("offline")), \
                patch("ai_solver.get_ai_client", return_value=client):
            self.assertEqual(ai_solver.solve_question_with_ai("Q", OPTIONS)[0], [0])
            self.assertEqual(ai_solver.solve_fib_with_ai("Q")[0], ["yes"])

    def test_explicit_first_choice_can_be_salvaged_from_validation_error(self):
        error = RuntimeError("{'failed_generation': '{\"selected_indices\":[1],\"reasoning\":\"valid\"}'}")
        with patch.object(config, "AI_API_KEY", "test-key"), \
                patch("ai_solver.get_ai_client", return_value=self.make_client(error=error)):
            self.assertEqual(ai_solver.solve_question_with_ai("Q", OPTIONS, max_retries=0)[0], [0])


if __name__ == "__main__":
    unittest.main()
