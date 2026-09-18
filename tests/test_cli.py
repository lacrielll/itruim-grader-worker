import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from grader_worker.cli import load_dotenv


class DotenvTests(unittest.TestCase):
    def test_loads_without_overwriting_process_environment(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("LLM_TEST_ONE=value\nLLM_TEST_EXISTING=file\n")
            os.environ["LLM_TEST_EXISTING"] = "process"
            load_dotenv(str(path))
            self.assertEqual(os.environ["LLM_TEST_ONE"], "value")
            self.assertEqual(os.environ["LLM_TEST_EXISTING"], "process")
