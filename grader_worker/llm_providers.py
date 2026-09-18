from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .llm_config import ProviderConfig


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, retryable: bool, message: str = ""):
        super().__init__(message or code)
        self.code, self.retryable = code, retryable


@dataclass(frozen=True)
class Completion:
    provider: str
    model: str
    value: dict[str, Any]
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


Transport = Callable[[urllib.request.Request, int], tuple[int, dict[str, str], bytes]]


def _transport(request: urllib.request.Request, timeout: int) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()
    except (TimeoutError, urllib.error.URLError) as error:
        raise ProviderFailure("NETWORK_TIMEOUT", True, str(error)) from error


def _content(config: ProviderConfig, messages: list[dict[str, str]], max_tokens: int, timeout: int, transport: Transport) -> Completion:
    started = time.monotonic()
    headers = {"Content-Type": "application/json"}
    if config.name == "cloudflare":
        url = f"{config.base_url}/accounts/{config.account_id}/ai/run/{config.model}"
        headers["Authorization"] = f"Bearer {config.api_key}"
        payload = {"messages": messages, "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
    elif config.name == "gemini":
        url = f"{config.base_url}/models/{config.model}:generateContent?key={config.api_key}"
        system = "\n".join(item["content"] for item in messages if item["role"] == "system")
        user = "\n".join(item["content"] for item in messages if item["role"] != "system")
        payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens, "temperature": 0}}
    else:
        url = f"{config.base_url}/chat/completions"
        headers["Authorization"] = f"Bearer {config.api_key}"
        payload = {"model": config.model, "messages": messages, "temperature": 0, "max_completion_tokens": max_tokens, "response_format": {"type": "json_object"}}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    status, response_headers, raw = transport(request, timeout)
    latency = round((time.monotonic() - started) * 1000)
    if status in {401, 403}:
        raise ProviderFailure("AUTH_FAILED", False)
    if status == 429:
        raise ProviderFailure("QUOTA_EXHAUSTED", True)
    if status >= 500:
        raise ProviderFailure("PROVIDER_UNAVAILABLE", True)
    if status >= 400:
        raise ProviderFailure("REQUEST_REJECTED", False, raw.decode(errors="replace")[:500])
    try:
        response = json.loads(raw)
        if config.name == "cloudflare":
            result = response["result"]
            text = result.get("response") or result["choices"][0]["message"]["content"]
            usage = response.get("result", {}).get("usage", {})
        elif config.name == "gemini":
            text = response["candidates"][0]["content"]["parts"][0]["text"]
            usage = response.get("usageMetadata", {})
        else:
            text = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {})
        value = json.loads(text) if isinstance(text, str) else text
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ProviderFailure("INVALID_OUTPUT", True, str(error)) from error
    return Completion(config.name, config.model, value,
        usage.get("prompt_tokens", usage.get("promptTokenCount")), usage.get("completion_tokens", usage.get("candidatesTokenCount")), latency)


def complete_with_fallback(providers: list[ProviderConfig], messages: list[dict[str, str]], validator: Callable[[dict], dict], max_tokens: int = 4000, timeout: int = 120, transport: Transport = _transport) -> tuple[Completion, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for config in providers:
        provider_messages = list(messages)
        for attempt in range(2):
            try:
                completion = _content(config, provider_messages, max_tokens, timeout, transport)
                try:
                    validator(completion.value)
                except Exception as error:
                    raise ProviderFailure("INVALID_OUTPUT", True, str(error)) from error
                attempts.append({"provider": config.name, "model": config.model, "outcome": "success", "latency_ms": completion.latency_ms, "input_tokens": completion.input_tokens, "output_tokens": completion.output_tokens})
                return completion, attempts
            except ProviderFailure as error:
                attempts.append({"provider": config.name, "model": config.model, "outcome": "failed", "error_code": error.code,
                                 "error_detail": str(error)[:300] if error.code == "INVALID_OUTPUT" else None})
                if error.code == "INVALID_OUTPUT" and attempt == 0:
                    provider_messages = provider_messages + [{
                        "role": "system",
                        "content": "Your previous output did not satisfy the required JSON contract. Return one non-null JSON object only, with every required field and only allowed enum values. Do not explain the correction.",
                    }]
                if error.code != "INVALID_OUTPUT" or attempt == 1:
                    if not error.retryable: break
                    break
    raise ProviderFailure("ALL_PROVIDERS_UNAVAILABLE", True, json.dumps(attempts))
