import json
import unittest

from grader_worker.llm_config import ProviderConfig
from grader_worker.llm_providers import complete_with_fallback


class ProviderFallbackTests(unittest.TestCase):
    def test_accepts_cloudflare_openai_compatible_response_shape(self):
        provider = ProviderConfig("cloudflare", "https://api.cloudflare.com/client/v4", "token", "@cf/model", "account")
        def transport(request, timeout):
            return 200, {}, json.dumps({
                "result": {
                    "choices": [{"message": {"content": '{"schema_version":1}'}}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2},
                }
            }).encode()
        result, attempts = complete_with_fallback([provider], [{"role": "user", "content": "x"}], lambda x: x, transport=transport)
        self.assertEqual(result.value["schema_version"], 1)
        self.assertEqual(result.input_tokens, 4)
        self.assertEqual(attempts[0]["outcome"], "success")

    def test_falls_back_after_quota(self):
        providers = [ProviderConfig("groq", "https://groq", "a", "m1"), ProviderConfig("openrouter", "https://router", "b", "m2")]
        calls = []
        def transport(request, timeout):
            calls.append(request.full_url)
            if "groq" in request.full_url: return 429, {}, b"{}"
            return 200, {}, json.dumps({"choices": [{"message": {"content": '{"schema_version":1}'}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}).encode()
        result, attempts = complete_with_fallback(providers, [{"role": "user", "content": "x"}], lambda x: x, transport=transport)
        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(len(attempts), 2)

    def test_repairs_invalid_json_once_before_fallback(self):
        provider = ProviderConfig("groq", "https://groq", "a", "m")
        count = 0
        requests = []
        def transport(request, timeout):
            nonlocal count; count += 1; requests.append(json.loads(request.data))
            content = "not-json" if count == 1 else '{"schema_version":1}'
            return 200, {}, json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        result, _ = complete_with_fallback([provider], [{"role": "user", "content": "x"}], lambda x: x, transport=transport)
        self.assertEqual(result.value["schema_version"], 1)
        self.assertEqual(count, 2)
        self.assertIn("previous output did not satisfy", requests[1]["messages"][-1]["content"])
