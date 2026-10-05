"""Select and check the AI engine before retrieving answers or starting a test."""

import asyncio
from urllib.parse import urlsplit

import config
from ai_solver import test_ai_connection
from ui import log_error, log_info


async def configure_ai(args) -> bool:
    """Return False when the requested AI-only run cannot proceed."""
    if args.no_ai or args.ai_provider == "off":
        args.no_ai = True
        log_info("AI disabled. Using the answer database only.")
        return True

    groq_key = config.GROQ_API_KEY
    if urlsplit(config.AI_API_BASE).hostname == "api.groq.com":
        groq_key = config.AI_API_KEY or groq_key
    # Snapshot each option so concurrent probes and the selected solver use identical settings.
    engines = {
        "gateway": ("Smart Hybrid (Cloudflare / Groq)", "", None,
                    config.AI_API_BASE, config.AI_GATEWAY_URL),
        "direct": (f"Personal API — {config.AI_MODEL}", config.AI_API_KEY,
                   config.AI_MODEL, config.AI_API_BASE, ""),
        "groq-120b": (f"GPT-OSS 120B / {'Groq' if groq_key else 'Gateway'} (text only)", groq_key,
                      "openai/gpt-oss-120b", "https://api.groq.com/openai/v1",
                      "" if groq_key else config.AI_GATEWAY_URL),
        "groq-20b": (f"GPT-OSS 20B / {'Groq' if groq_key else 'Gateway'} (text only)", groq_key,
                     "openai/gpt-oss-20b", "https://api.groq.com/openai/v1",
                     "" if groq_key else config.AI_GATEWAY_URL),
    }

    # The default Qwen model also works through the bundled gateway without BYOK.
    if config.AI_MODEL == "qwen/qwen3.8-27b" and urlsplit(config.AI_API_BASE).hostname == "api.groq.com":
        engines["direct"] = (
            f"Qwen 3.8 27B / {'Groq' if groq_key else 'Groq via Gateway'}", groq_key,
            config.AI_MODEL, config.AI_API_BASE,
            "" if groq_key else config.AI_GATEWAY_URL,
        )

    async def check(provider: str) -> tuple[bool, str]:
        _, key, model, base, gateway = engines[provider]
        if provider == "gateway" and not gateway:
            return False, "Gateway URL is not configured"
        if provider != "gateway" and not key and not gateway:
            return False, "No Groq API key or gateway configured" if provider.startswith("groq-") else "API key is not configured"
        try:
            ok, detail = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: test_ai_connection(
                    api_key=key,
                    model=model,
                    base_url=base,
                    gateway_url=gateway,
                ),
            )
        except Exception as exc:
            ok, detail = False, str(exc)
        for secret in (config.AI_API_KEY, groq_key):
            if secret:
                detail = detail.replace(secret, "[redacted]")
        return ok, detail

    labels = {provider: settings[0] for provider, settings in engines.items()}
    requested = args.ai_provider
    providers = [requested] if requested else list(labels)
    log_info("Checking AI availability (test request)...")
    results = dict(zip(providers, await asyncio.gather(*(check(p) for p in providers))))
    print()
    for number, provider in enumerate(providers, 1):
        ok, detail = results[provider]
        status = "Available" if ok else "Unavailable"
        print(f"  {number}) {labels[provider]} — {status}: {detail}")

    if requested:
        selected = requested if results[requested][0] else None
    else:
        off_number = str(len(providers) + 1)
        print(f"  {off_number}) No AI")
        preferred = "direct" if (args.ai_key or args.ai_model or args.ai_base) else "gateway"
        default = next((p for p in [preferred, *providers] if results[p][0]), None)
        default_number = str(providers.index(default) + 1) if default else off_number
        choices = {str(i): provider for i, provider in enumerate(providers, 1)}
        while True:
            choice = (await asyncio.get_running_loop().run_in_executor(
                None, input, f"  Select AI before the test [default: {default_number}]: "
            )).strip() or default_number
            if choice == off_number:
                selected = None
                break
            if choice not in choices:
                log_error(f"Enter a number from 1 to {off_number}.")
                continue
            selected = choices[choice]
            if not results[selected][0]:
                log_error("This AI engine is unavailable. Select another option.")
                continue
            break

    if selected is None:
        if args.ai:
            log_error("Test not started: AI-only mode requires an available AI engine.")
            return False
        args.no_ai = True
        log_info("AI disabled. Using the answer database only.")
        return True

    _, key, model, base, gateway = engines[selected]
    config.AI_API_KEY = key
    config.AI_API_BASE = base
    config.AI_GATEWAY_URL = gateway
    config.AI_GATEWAY_MODEL = model if gateway and model else ""
    if model is not None:
        config.AI_MODEL = model
    args.no_ai = False
    log_info(f"Selected AI: {labels[selected]} — Available.")
    return True
