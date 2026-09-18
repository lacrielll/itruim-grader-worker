from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from grader_worker.policy import scan_python_tree


class PolicyTests(unittest.TestCase):
    def test_allows_lab_subset(self):
        with TemporaryDirectory() as directory:
            Path(directory, "solution.py").write_text("import numpy as np\nfrom grader_contracts import Inputs\ndef f(x):\n return np.asarray(x)\n")
            self.assertEqual(scan_python_tree(Path(directory)), [])

    def test_reports_dangerous_capabilities_with_locations(self):
        with TemporaryDirectory() as directory:
            Path(directory, "solution.py").write_text("import os\neval('1 + 1')\n")
            findings = scan_python_tree(Path(directory))
            self.assertEqual([item.code for item in findings], ["IMPORT_NOT_ALLOWED", "CALL_NOT_ALLOWED"])
            self.assertEqual([item.source_line for item in findings], [1, 2])


if __name__ == "__main__":
    unittest.main()
