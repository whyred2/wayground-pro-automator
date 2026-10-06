"""Offline checks for availability, selection, and runtime AI settings."""

import contextlib
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    import openai
except ImportError:
    # These tests replace the SDK boundary and need no installed SDK or network.
    openai = ModuleType("openai")
    openai.OpenAI = MagicMock()
    sys.modules["openai"] = openai

import ai_setup
import ai_solver
import config


class SelectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = patch.multiple(config, AI_API_KEY="test-key", GROQ_API_KEY="", AI_MODEL="test-model",
                                       AI_GATEWAY_MODEL="",
                                       AI_API_BASE="https://direct.example/v1",
                                       AI_GATEWAY_URL="https://gateway.example")
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        self.args = SimpleNamespace(ai=False, no_ai=False, ai_provider=None,
                                    ai_key=None, ai_model=None, ai_base=None)

    async def test_direct_selection_uses_only_direct_api(self):
        with patch("ai_setup.test_ai_connection", return_value=(True, "ok")) as check, \
                patch("builtins.input", return_value="2"):
            self.assertTrue(await ai_setup.configure_ai(self.args))
        self.assertEqual(config.AI_GATEWAY_URL, "")
        self.assertEqual(config.AI_API_KEY, "test-key")
        self.assertEqual(check.call_count, 4)
        self.assertIn("Available", self.output.getvalue())

    async def test_unavailable_option_requires_another_choice(self):
        def check(**kwargs):
            return (False, "offline") if kwargs["gateway_url"] else (True, "ok")
        with patch("ai_setup.test_ai_connection", side_effect=check), \
                patch("builtins.input", side_effect=["oops", "1", "2"]) as prompt:
            self.assertTrue(await ai_setup.configure_ai(self.args))
        self.assertEqual(prompt.call_count, 3)
        self.assertEqual(config.AI_GATEWAY_URL, "")
        self.assertIn("Unavailable", self.output.getvalue())

    async def test_all_unavailable_default_disables_ai(self):
        with patch("ai_setup.test_ai_connection", return_value=(False, "offline")), \
                patch("builtins.input", return_value=""):
            self.assertTrue(await ai_setup.configure_ai(self.args))
        self.assertTrue(self.args.no_ai)

    async def test_ai_only_cannot_start_without_available_engine(self):
        self.args.ai = True
        self.args.ai_provider = "gateway"
        with patch("ai_setup.test_ai_connection", return_value=(False, "offline")), \
                patch("builtins.input") as prompt:
            self.assertFalse(await ai_setup.configure_ai(self.args))
        prompt.assert_not_called()

    async def test_explicit_gateway_skips_prompt_and_personal_fallback(self):
        self.args.ai_provider = "gateway"
        with patch("ai_setup.test_ai_connection", return_value=(True, "ok")) as check, \
                patch("builtins.input") as prompt:
            self.assertTrue(await ai_setup.configure_ai(self.args))
        prompt.assert_not_called()
        self.assertEqual(check.call_args.kwargs["api_key"], "")
        self.assertEqual(config.AI_API_KEY, "")

    async def test_no_ai_skips_checks(self):
        self.args.no_ai = True
        with patch("ai_setup.test_ai_connection") as check:
            self.assertTrue(await ai_setup.configure_ai(self.args))
        check.assert_not_called()

    async def test_missing_key_is_unavailable_without_api_call(self):
        config.AI_API_KEY = ""
        self.args.ai_provider = "direct"
        with patch("ai_setup.test_ai_connection") as check:
            self.assertTrue(await ai_setup.configure_ai(self.args))
        check.assert_not_called()
        self.assertTrue(self.args.no_ai)
        self.assertIn("API key is not configured", self.output.getvalue())

    async def test_default_qwen_uses_gateway_without_personal_key(self):
        config.AI_API_KEY = ""
        config.AI_MODEL = "qwen/qwen3.8-27b"
        config.AI_API_BASE = "https://api.groq.com/openai/v1"
        with patch("ai_setup.test_ai_connection", return_value=(True, "ok")) as check, \
                patch("builtins.input", return_value="2"):
            self.assertTrue(await ai_setup.configure_ai(self.args))
        qwen_call = next(call for call in check.call_args_list if call.kwargs["model"] == "qwen/qwen3.8-27b")
        self.assertEqual(qwen_call.kwargs["api_key"], "")
        self.assertEqual(qwen_call.kwargs["gateway_url"], "https://gateway.example")
        self.assertEqual(config.AI_GATEWAY_MODEL, "qwen/qwen3.8-27b")
        self.assertIn("Qwen 3.8 27B / Groq via Gateway", self.output.getvalue())

    async def test_qwen_with_dedicated_key_stays_on_groq(self):
        config.AI_API_KEY = ""
        config.GROQ_API_KEY = "groq-secret"
        config.AI_MODEL = "qwen/qwen3.8-27b"
        config.AI_API_BASE = "https://api.groq.com/openai/v1"
        self.args.ai_provider = "direct"
        with patch("ai_setup.test_ai_connection", return_value=(True, "ok")) as check:
            self.assertTrue(await ai_setup.configure_ai(self.args))
        self.assertEqual(check.call_args.kwargs["api_key"], "groq-secret")
        self.assertEqual(config.AI_GATEWAY_URL, "")

    async def test_secret_is_redacted_from_status(self):
        self.args.ai_provider = "direct"
        with patch("ai_setup.test_ai_connection", return_value=(False, "invalid test-key")):
            await ai_setup.configure_ai(self.args)
        self.assertNotIn("test-key", self.output.getvalue())

    async def test_groq_presets_apply_the_checked_model_and_credentials(self):
        for provider, model in (("groq-120b", "openai/gpt-oss-120b"),
                                ("groq-20b", "openai/gpt-oss-20b")):
            with self.subTest(provider=provider):
                config.GROQ_API_KEY = "groq-secret"
                self.args.ai_provider = provider
                with patch("ai_setup.test_ai_connection", return_value=(True, "ok")) as check:
                    self.assertTrue(await ai_setup.configure_ai(self.args))
                self.assertEqual(check.call_args.kwargs["model"], model)
                self.assertEqual(check.call_args.kwargs["api_key"], "groq-secret")
                self.assertEqual(config.AI_MODEL, model)
                self.assertEqual(config.AI_API_KEY, "groq-secret")
                self.assertEqual(config.AI_API_BASE, "https://api.groq.com/openai/v1")
                self.assertEqual(config.AI_GATEWAY_URL, "")

    async def test_groq_does_not_receive_another_providers_key(self):
        self.args.ai_provider = "groq-120b"
        config.AI_GATEWAY_URL = ""
        with patch("ai_setup.test_ai_connection") as check:
            self.assertTrue(await ai_setup.configure_ai(self.args))
        check.assert_not_called()
        self.assertTrue(self.args.no_ai)
        self.assertIn("No Groq API key or gateway configured", self.output.getvalue())

    async def test_groq_preset_uses_gateway_without_personal_key(self):
        self.args.ai_provider = "groq-120b"
        with patch("ai_setup.test_ai_connection", return_value=(True, "ok")) as check:
            self.assertTrue(await ai_setup.configure_ai(self.args))
        self.assertEqual(check.call_args.kwargs["api_key"], "")
        self.assertEqual(check.call_args.kwargs["model"], "openai/gpt-oss-120b")
        self.assertEqual(check.call_args.kwargs["gateway_url"], "https://gateway.example")
        self.assertEqual(config.AI_GATEWAY_MODEL, "openai/gpt-oss-120b")
        self.assertEqual(config.AI_API_KEY, "")

    async def test_groq_reuses_key_for_configured_groq_endpoint(self):
        config.AI_API_BASE = "https://api.groq.com/openai/v1"
        self.args.ai_provider = "groq-20b"
        with patch("ai_setup.test_ai_connection", return_value=(True, "ok")) as check:
            self.assertTrue(await ai_setup.configure_ai(self.args))
        self.assertEqual(check.call_args.kwargs["api_key"], "test-key")

    async def test_interactive_groq_and_off_numbers(self):
        config.GROQ_API_KEY = "groq-secret"
        with patch("ai_setup.test_ai_connection", return_value=(True, "ok")), \
                patch("builtins.input", return_value="4"):
            self.assertTrue(await ai_setup.configure_ai(self.args))
        self.assertEqual(config.AI_MODEL, "openai/gpt-oss-20b")
        with patch("ai_setup.test_ai_connection", return_value=(True, "ok")), \
                patch("builtins.input", return_value="5"):
            self.assertTrue(await ai_setup.configure_ai(self.args))
        self.assertTrue(self.args.no_ai)


class ConnectionTests(unittest.TestCase):
    def test_qwen_probe_requires_groq_provider(self):
        for provider, expected in (("Groq Cloud", True), ("Cloudflare Workers AI", False)):
            with self.subTest(provider=provider):
                response = MagicMock()
                response.__enter__.return_value.read.return_value = json.dumps({
                    "selected_indices":[1], "model":"qwen/qwen3.8-27b", "provider":provider,
                }).encode()
                with patch("ai_solver.urllib.request.urlopen", return_value=response):
                    ok, _ = ai_solver.test_ai_connection(api_key="", model="qwen/qwen3.8-27b",
                                                         gateway_url="https://gateway.example")
                self.assertEqual(ok, expected)

    def test_qwen_answers_reject_a_different_provider(self):
        with patch.object(config, "AI_GATEWAY_MODEL", "qwen/qwen3.8-27b"):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"model":"qwen/qwen3.8-27b","provider":"Cloudflare Workers AI"}'
            with patch("ai_solver.urllib.request.urlopen", return_value=response):
                with self.assertRaisesRegex(ValueError, "Groq"):
                    ai_solver._solve_via_gateway_mcq("https://gateway.example", "Q", [{"text":"A"}])
                with self.assertRaisesRegex(ValueError, "Groq"):
                    ai_solver._solve_via_gateway_fib("https://gateway.example", "Q")

    def test_old_gateway_cannot_claim_selected_model_is_available(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"selected_indices":[1],"provider":"Cloudflare Workers AI"}'
        with patch("ai_solver.urllib.request.urlopen", return_value=response):
            ok, detail = ai_solver.test_ai_connection(api_key="", model="openai/gpt-oss-120b",
                                                      gateway_url="https://gateway.example")
        self.assertFalse(ok)
        self.assertIn("update", detail)

    def test_gateway_probe_sends_model_and_checks_confirmation(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"selected_indices":[1],"model":"openai/gpt-oss-20b"}'
        with patch("ai_solver.urllib.request.urlopen", return_value=response) as request:
            ok, _ = ai_solver.test_ai_connection(api_key="", model="openai/gpt-oss-20b",
                                                 gateway_url="https://gateway.example")
        self.assertTrue(ok)
        self.assertEqual(json.loads(request.call_args.args[0].data)["model"], "openai/gpt-oss-20b")

    def test_both_gateway_answer_paths_send_selected_model(self):
        with patch.object(config, "AI_GATEWAY_MODEL", "openai/gpt-oss-120b"):
            for solve, args, answer in (
                (ai_solver._solve_via_gateway_mcq, ("https://gateway.example", "Q", [{"text":"A"}]), {"selected_indices":[1]}),
                (ai_solver._solve_via_gateway_fib, ("https://gateway.example", "Q"), {"answer":"A"}),
            ):
                response = MagicMock()
                response.__enter__.return_value.read.return_value = json.dumps({**answer, "model":config.AI_GATEWAY_MODEL}).encode()
                with patch("ai_solver.urllib.request.urlopen", return_value=response) as request:
                    solve(*args)
                self.assertEqual(json.loads(request.call_args.args[0].data)["model"], config.AI_GATEWAY_MODEL)

    def test_groq_reasoning_options_reserve_room_for_final_answer(self):
        for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
            for budget in (5, 512, 768):
                options = ai_solver._completion_options(model, budget)
                self.assertEqual(options["max_tokens"], 2048)
                self.assertEqual(options["extra_body"]["reasoning_effort"], "low")
                self.assertFalse(options["extra_body"]["include_reasoning"])
        self.assertEqual(ai_solver._completion_options("other-model", 512), {"max_tokens":512})

    def test_gateway_checks_solving_instead_of_health(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"selected_indices": [1], "provider": "Groq Cloud (Fallback)"}
        ).encode()
        with patch("ai_solver.urllib.request.urlopen", return_value=response) as request:
            ok, detail = ai_solver.test_ai_connection(api_key="", gateway_url="https://gateway.example")
        self.assertTrue(ok)
        self.assertIn("Groq", detail)
        self.assertEqual(request.call_args.args[0].full_url, "https://gateway.example/api/solve")

    def test_gateway_health_response_does_not_count_as_available(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"status":"online"}'
        with patch("ai_solver.urllib.request.urlopen", return_value=response):
            ok, _ = ai_solver.test_ai_connection(api_key="", gateway_url="https://gateway.example")
        self.assertFalse(ok)

    def test_direct_check_is_bounded_and_honors_disabled_gateway(self):
        client = MagicMock()
        client.with_options.return_value = client
        client.chat.completions.create.return_value.choices = [object()]
        with patch("ai_solver.OpenAI", return_value=client), \
                patch("ai_solver.urllib.request.urlopen") as gateway:
            ok, _ = ai_solver.test_ai_connection(api_key="key", model="model", gateway_url="")
        self.assertTrue(ok)
        gateway.assert_not_called()
        client.with_options.assert_called_once_with(timeout=10.0, max_retries=0)

    def test_runtime_settings_reach_both_answer_paths(self):
        client = MagicMock()
        result = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])
        client.chat.completions.create.return_value = result
        with patch.multiple(config, AI_API_KEY="new-key", AI_MODEL="new-model",
                            AI_API_BASE="https://new.example/v1", AI_GATEWAY_URL=""), \
                patch("ai_solver.OpenAI", return_value=client) as sdk, \
                patch("ai_solver._solve_via_gateway_mcq") as mcq, \
                patch("ai_solver._solve_via_gateway_fib") as fib:
            result.choices[0].message.content = '{"selected_indices":[2]}'
            indices, _ = ai_solver.solve_question_with_ai("Question", [{"text":"A"}, {"text":"B"}])
            self.assertEqual(indices, [1])
            result.choices[0].message.content = '{"answer":"two","plausible_wrong":"three"}'
            answers, _, _ = ai_solver.solve_fib_with_ai("1+1 = ___")
            self.assertEqual(answers, ["two"])
            for call in sdk.call_args_list:
                self.assertEqual(call.kwargs, {"api_key":"new-key", "base_url":"https://new.example/v1",
                                              "timeout": 30.0, "max_retries": 0})
            for call in client.chat.completions.create.call_args_list:
                self.assertEqual(call.kwargs["model"], "new-model")
            mcq.assert_not_called()
            fib.assert_not_called()


if __name__ == "__main__":
    unittest.main()
