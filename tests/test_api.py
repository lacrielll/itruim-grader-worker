import json
import unittest
from unittest.mock import patch

from grader_worker.api import GraderApi, USER_AGENT


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps({"ok": True}).encode()


class GraderApiTests(unittest.TestCase):
    def test_sends_explicit_worker_user_agent(self):
        with patch("urllib.request.urlopen", return_value=_Response()) as urlopen:
            result = GraderApi("https://example.test", "secret").readiness(True, {})

        request = urlopen.call_args.args[0]
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")


if __name__ == "__main__":
    unittest.main()
