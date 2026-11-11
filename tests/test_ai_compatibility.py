"""Exercise API parameter detection, response validation and reuse by real SDK requests."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ai_solver
import config


class ParameterError(Exception):
    status_code = 400

    def __init__(self, parameter, message="Unsupported parameter", code="unsupported_parameter"):
        super().__init__(message)
        self.body = {"param": parameter, "message": message, "code": code}


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        ai_solver._COMPLETION_CAPABILITIES.clear()
        self.addCleanup(ai_solver._COMPLETION_CAPABILITIES.clear)

    def client(self, content='{"selected_indices":[1]}', **choice):
        completion = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=choice.get("finish_reason", "stop"))]))
        return SimpleNamespace(base_url="https://custom.example/v1/", with_options=Mock(),
                               chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))

    def check(self, client, model="custom-model"):
        client.with_options.return_value = client
        with patch("ai_solver.get_ai_client", return_value=client):
            return ai_solver.test_ai_connection("test-key", model, "https://custom.example/v1", "")

    def test_gpt6_probe_and_both_solvers_use_reasoning_compatible_parameters(self):
        for model in ("gpt-6", "gpt-6-astra", "gpt-6-sol", "openai/gpt-6-astra", "gpt-6.1-sol"):
            with self.subTest(model=model):
                client = self.client()
                self.assertTrue(self.check(client, model)[0])
                with patch.multiple(config, AI_API_KEY="test-key", AI_MODEL=model, AI_GATEWAY_URL=""), \
                        patch("ai_solver.get_ai_client", return_value=client):
                    self.assertEqual(ai_solver.solve_question_with_ai("1+1?", [{"text": "2"}, {"text": "3"}])[0], [0])
                    client.chat.completions.create.return_value.choices[0].message.content = '{"answer":"2"}'
                    self.assertEqual(ai_solver.solve_fib_with_ai("1+1 = ___")[0], ["2"])
                for call in client.chat.completions.create.call_args_list:
                    self.assertEqual(call.kwargs["model"], model)
                    self.assertGreaterEqual(call.kwargs["max_completion_tokens"], 4096)
                    self.assertNotIn("max_tokens", call.kwargs)
                    self.assertNotIn("temperature", call.kwargs)

    def test_probe_rejects_empty_wrong_malformed_and_truncated_test_answers(self):
        for content, finish in [("", "stop"), ('{"selected_indices":[2]}', "stop"),
                                ('{"selected_indices":[true]}', "stop"), ("online", "stop"),
                                ('{"selected_indices":[1]}', "length")]:
            with self.subTest(content=content, finish=finish):
                self.assertFalse(self.check(self.client(content, finish_reason=finish))[0])
        client = self.client()
        client.chat.completions.create.return_value.choices = []
        self.assertFalse(self.check(client)[0])

    def test_unknown_alias_detects_token_parameter_then_temperature_and_remembers_them(self):
        client = self.client()
        result = client.chat.completions.create.return_value
        client.chat.completions.create.side_effect = [
            ParameterError("max_tokens"), ParameterError("temperature", code="unsupported_value"), result, result]
        self.assertTrue(self.check(client)[0])
        ai_solver._create_completion(client, "custom-model", 768, messages=[], temperature=0)
        requests = [call.kwargs for call in client.chat.completions.create.call_args_list]
        self.assertIn("max_tokens", requests[0])
        self.assertIn("max_completion_tokens", requests[1])
        self.assertIn("temperature", requests[1])
        for request in requests[2:]:
            self.assertIn("max_completion_tokens", request)
            self.assertNotIn("temperature", request)
            self.assertNotIn("max_tokens", request)

    def test_legacy_proxy_can_explicitly_require_max_tokens_for_gpt6(self):
        client = self.client()
        result = client.chat.completions.create.return_value
        client.chat.completions.create.side_effect = [ParameterError("max_completion_tokens"), result, result]
        self.assertTrue(self.check(client, "gpt-6")[0])
        ai_solver._create_completion(client, "gpt-6", 768, messages=[])
        for call in client.chat.completions.create.call_args_list[1:]:
            self.assertIn("max_tokens", call.kwargs)
            self.assertNotIn("max_completion_tokens", call.kwargs)

    def test_rejected_token_names_do_not_retry_forever(self):
        client = self.client()
        client.chat.completions.create.side_effect = [
            ParameterError("max_tokens"), ParameterError("max_completion_tokens")]
        self.assertFalse(self.check(client)[0])
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertFalse(ai_solver._COMPLETION_CAPABILITIES)

    def test_auth_quota_network_and_token_budget_errors_do_not_trigger_parameter_fallback(self):
        for error in [RuntimeError("offline"), ParameterError("max_tokens", "Token limit exceeds context", "invalid_value"),
                      ParameterError("max_tokens", "Unsupported value: 'max_tokens': exceeds allowed limit", "unsupported_value"),
                      ParameterError("response_format")]:
            with self.subTest(error=error):
                client = self.client()
                client.chat.completions.create.side_effect = error
                self.assertFalse(self.check(client)[0])
                client.chat.completions.create.assert_called_once()
        for status in (401, 429, 500):
            with self.subTest(status=status):
                error = ParameterError("max_tokens")
                error.status_code = status
                client = self.client()
                client.chat.completions.create.side_effect = error
                self.assertFalse(self.check(client)[0])
                client.chat.completions.create.assert_called_once()

    def test_capabilities_are_scoped_to_endpoint_and_model(self):
        first = self.client()
        result = first.chat.completions.create.return_value
        first.chat.completions.create.side_effect = [ParameterError("max_tokens"), result]
        self.assertTrue(self.check(first)[0])
        for base, model in [("https://another.example/v1/", "custom-model"),
                            (first.base_url, "another-model")]:
            client = self.client()
            client.base_url = base
            ai_solver._create_completion(client, model, 256, messages=[])
            self.assertIn("max_tokens", client.chat.completions.create.call_args.kwargs)

    def test_message_only_parameter_errors_are_recognized(self):
        error = ParameterError(None, "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead.")
        error.body = {"message": str(error)}
        self.assertEqual(ai_solver._unsupported_parameter(error), "max_tokens")

    def test_real_sdk_uses_detected_parameters_for_probe_mcq_and_fib(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, self.headers.get("Authorization"), payload))
                parameter = "max_tokens" if "max_tokens" in payload else "temperature" if "temperature" in payload else ""
                if parameter:
                    status = 400
                    body = {"error": {"code": "unsupported_parameter", "param": parameter,
                                      "message": f"Unsupported parameter: '{parameter}'."}}
                else:
                    status = 200
                    fib = "Fill-in-the-blank" in payload["messages"][-1]["content"]
                    answer = {"answer": "2"} if fib else {"selected_indices": [1]}
                    body = {"id": "test", "object": "chat.completion", "created": 0, "model": payload["model"],
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(answer)},
                                         "finish_reason": "stop"}]}
                encoded = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}/v1"
            with patch.multiple(config, AI_API_KEY="local-test-key", AI_API_BASE=base,
                                AI_MODEL="custom-alias", AI_GATEWAY_URL=""):
                self.assertTrue(ai_solver.test_ai_connection()[0])
                self.assertEqual(ai_solver.solve_question_with_ai("1+1?", [{"text": "2"}, {"text": "3"}])[0], [0])
                self.assertEqual(ai_solver.solve_fib_with_ai("1+1 = ___")[0], ["2"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertEqual(len(requests), 5)
        for path, authorization, payload in requests:
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(authorization, "Bearer local-test-key")
            self.assertEqual(payload["model"], "custom-alias")
        for _, _, payload in requests[2:]:
            self.assertIn("max_completion_tokens", payload)
            self.assertNotIn("max_tokens", payload)
            self.assertNotIn("temperature", payload)


if __name__ == "__main__":
    unittest.main()
