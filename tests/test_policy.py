from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from grader_worker.policy import load_python_policy, scan_python_tree


class PolicyTests(unittest.TestCase):
    def test_allows_lab_subset(self):
        with TemporaryDirectory() as directory:
            Path(directory, "solution.py").write_text("import matplotlib.pyplot as plt\nimport pytest\nimport numpy as np\nfrom grader_contracts import Inputs\ndef f(x):\n return np.asarray(x)\n")
            policy = load_python_policy(Path(__file__).parents[1] / "graders" / "lab1" / "python-policy.json")
            self.assertEqual(scan_python_tree(Path(directory), policy), [])

    def test_default_policy_does_not_inherit_another_lab_import_allowlist(self):
        with TemporaryDirectory() as directory:
            Path(directory, "solution.py").write_text("import pandas as pd\n")
            self.assertEqual(scan_python_tree(Path(directory)), [])

    def test_reports_dangerous_capabilities_with_locations(self):
        with TemporaryDirectory() as directory:
            Path(directory, "solution.py").write_text("import os\neval('1 + 1')\n")
            policy = load_python_policy(Path(__file__).parents[1] / "graders" / "lab1" / "python-policy.json")
            findings = scan_python_tree(Path(directory), policy)
            self.assertEqual([item.code for item in findings], ["IMPORT_NOT_ALLOWED", "CALL_NOT_ALLOWED"])
            self.assertEqual([item.source_line for item in findings], [1, 2])


if __name__ == "__main__":
    unittest.main()
