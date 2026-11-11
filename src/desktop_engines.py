"""Immutable AI presets: probing never changes a solver request already in flight."""

import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit

import config
from ai_solver import test_ai_connection


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    key: str
    model: str | None
    base: str
    gateway: str
    text_only: bool = False

    def public(self):
        return {"id": self.id, "label": self.label, "text_only": self.text_only}


def engine_catalog():
    gateway = config.AI_GATEWAY_URL
    groq_key = config.GROQ_API_KEY
    if urlsplit(config.AI_API_BASE).hostname == "api.groq.com":
        groq_key = config.AI_API_KEY or groq_key
    groq_base = "https://api.groq.com/openai/v1"
    return {
        "gateway": Engine("gateway", "Smart Hybrid · Cloudflare / Groq", config.AI_API_KEY,
                          None, config.AI_API_BASE, gateway),
        "qwen": Engine("qwen", "Qwen 3.8 27B · Groq", groq_key, "qwen/qwen3.8-27b",
                       groq_base, "" if groq_key else gateway, True),
        "groq-120b": Engine("groq-120b", "GPT-OSS 120B · text only", groq_key,
                            "openai/gpt-oss-120b", groq_base, "" if groq_key else gateway, True),
        "groq-20b": Engine("groq-20b", "GPT-OSS 20B · text only", groq_key,
                           "openai/gpt-oss-20b", groq_base, "" if groq_key else gateway, True),
        "direct": Engine("direct", f"Personal API · {config.AI_MODEL}", config.AI_API_KEY,
                         config.AI_MODEL, config.AI_API_BASE, ""),
    }


def personal_engine(base, key, model):
    """Validate a session-only OpenAI-compatible API without changing active settings."""
    base, key, model = base.strip().rstrip("/"), key.strip(), model.strip()
    try:
        url = urlsplit(base)
        valid = (url.scheme in ("http", "https") and url.hostname and url.port != 0
                 and not url.username and not url.password and not url.query and not url.fragment
                 and not any(char.isspace() for char in base))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Enter an API base URL starting with http:// or https://, without credentials or query parameters.")
    if not key:
        raise ValueError("Enter your API key.")
    if not model:
        raise ValueError("Enter the model name supported by your API.")
    return Engine("direct", f"Personal API · {model}", key, model, base, "")


def redact(message, *secrets):
    text = str(message)
    for secret in (config.AI_API_KEY, config.GROQ_API_KEY, config.MISTRAL_API_KEY, *secrets):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


async def probe(engine):
    if not engine.key and not engine.gateway:
        return False, "API key is not configured."
    try:
        result = await asyncio.to_thread(
            test_ai_connection, engine.key, engine.model, engine.base, engine.gateway,
        )
        return bool(result[0]), redact(result[1], engine.key)
    except Exception as exc:
        return False, redact(exc, engine.key)


def apply_engine(engine, *, default_model=None):
    config.AI_API_KEY = engine.key
    config.AI_API_BASE = engine.base
    config.AI_GATEWAY_URL = engine.gateway
    config.AI_GATEWAY_MODEL = engine.model if engine.gateway and engine.model else ""
    config.AI_MODEL = engine.model or default_model or config.AI_MODEL
