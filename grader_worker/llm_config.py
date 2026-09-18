from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str
    account_id: str = ""


def configured_providers() -> list[ProviderConfig]:
    providers = {
        "cloudflare": ProviderConfig("cloudflare", "https://api.cloudflare.com/client/v4", os.getenv("CLOUDFLARE_AI_API_TOKEN", ""), os.getenv("CLOUDFLARE_AI_MODEL", "@cf/zai-org/glm-4.7-flash"), os.getenv("CLOUDFLARE_ACCOUNT_ID", "")),
        "gemini": ProviderConfig("gemini", "https://generativelanguage.googleapis.com/v1beta", os.getenv("GEMINI_API_KEY", ""), os.getenv("GEMINI_MODEL", "gemini-3.8-flash")),
        "groq": ProviderConfig("groq", "https://api.groq.com/openai/v1", os.getenv("GROQ_API_KEY", ""), os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")),
        "openrouter": ProviderConfig("openrouter", "https://openrouter.ai/api/v1", os.getenv("OPENROUTER_API_KEY", ""), os.getenv("OPENROUTER_MODEL", "openrouter/free")),
    }
    order = os.getenv("LLM_PROVIDER_ORDER", "cloudflare,gemini,groq,openrouter").split(",")
    return [providers[name.strip()] for name in order if name.strip() in providers and providers[name.strip()].api_key and (name.strip() != "cloudflare" or providers[name.strip()].account_id)]
