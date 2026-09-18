import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from grader_worker.precheck import precheck


class PrecheckTests(unittest.TestCase):
    def test_reports_missing_public_contract_parts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            grader = root / "graders" / "demo"
            grader.mkdir(parents=True)
            (grader / "assignment-template.json").write_text(json.dumps({"grader_contract": {"required_files": ["grader_contracts/types.py"], "functions": [{"name": "fit"}]}}))
            submission = root / "solution"
            submission.mkdir()
            result = precheck("demo", submission, root)
            self.assertFalse(result["ok"])
            self.assertEqual({item["code"] for item in result["errors"]}, {"CONTRACT_FILE_MISSING", "CONTRACT_SYMBOL_MISSING"})

    def test_accepts_matching_structure_and_symbol(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            grader = root / "graders" / "demo"
            grader.mkdir(parents=True)
            (grader / "assignment-template.json").write_text(json.dumps({"grader_contract": {"required_files": ["grader_contracts/types.py"], "functions": [{"name": "fit"}]}}))
            submission = root / "solution"
            (submission / "grader_contracts").mkdir(parents=True)
            (submission / "grader_contracts" / "types.py").write_text("class Input: pass\n")
            (submission / "solution.py").write_text("def fit(data):\n    return data\n")
            self.assertTrue(precheck("demo", submission, root)["ok"])
