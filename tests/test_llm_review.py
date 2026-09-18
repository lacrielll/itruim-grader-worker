import tempfile
import unittest
from pathlib import Path

from grader_worker.llm_review import run_initial_review


class LlmReviewPipelineTests(unittest.TestCase):
    def test_disabled_pipeline_never_calls_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_initial_review(Path(directory), {
                "llm_pipeline": {"enabled": False, "preset": "deterministic_only", "max_rounds": 0},
            }, {"deterministic_gate": "passed"})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
