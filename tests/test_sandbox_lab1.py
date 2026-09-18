from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from grader_worker.sandbox import SandboxInfrastructureFailure, SandboxPolicy, docker_ready, run_sandbox


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "graders" / "lab1" / "contracts"


class Lab1SandboxTests(unittest.TestCase):
    image = "itruim-grader-cpu:cpu-v1"

    @classmethod
    def setUpClass(cls):
        try:
            docker_ready(cls.image, "runsc-ptrace")
        except SandboxInfrastructureFailure as error:
            raise unittest.SkipTest(str(error)) from error

    def snapshot(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        root.chmod(0o755)
        shutil.copytree(CONTRACTS / "grader_contracts", root / "grader_contracts")
        return temporary, root

    def grade(self, root: Path):
        return run_sandbox(root, ROOT, CONTRACTS, "lab1", SandboxPolicy(image=self.image, ram_mb=256, wall_time_sec=30))

    def test_reference_implementation_passes_all_functions(self):
        temporary, root = self.snapshot()
        try:
            shutil.copy2(ROOT / "graders" / "lab1" / "reference.py", root / "student_solution.py")
            result = self.grade(root)
            self.assertEqual(result["deterministic_gate"], "passed", result)
            self.assertEqual(result["score"]["earned"], 100)
            self.assertEqual(len(result["checks"]), 6)
            self.assertIn({
                "achievement_id": "assignment/lab-1/all-functions",
                "evidence_ids": [f"check:function:{name}" for name in (
                    "count_vowels", "has_unique_characters", "multiplicative_persistence", "prime_factorization", "sum_prod", "binarize",
                )],
                "reason_code": "all_required_functions_passed",
                "source": "pipeline:all_functions",
            }, result["achievement_triggers"])
        finally:
            temporary.cleanup()

    def test_reports_all_missing_symbols(self):
        temporary, root = self.snapshot()
        try:
            (root / "student_solution.py").write_text(
                "from grader_contracts.python_basics import TextInput\n"
                "def count_vowels(data: TextInput) -> int:\n    return 0\n",
                encoding="utf-8",
            )
            result = self.grade(root)
            self.assertEqual(result["outcome"], "contract_failed")
            missing = [item for item in result["public_diagnostics"] if item["code"] == "CONTRACT_SYMBOL_MISSING"]
            self.assertEqual(len(missing), 5)
        finally:
            temporary.cleanup()

    def test_rejects_modified_contract(self):
        temporary, root = self.snapshot()
        try:
            with (root / "grader_contracts" / "python_basics.py").open("a", encoding="utf-8") as file:
                file.write("\n# changed\n")
            (root / "solution.py").write_text("", encoding="utf-8")
            result = self.grade(root)
            codes = {item["code"] for item in result["public_diagnostics"]}
            self.assertIn("CONTRACT_TAMPERED", codes)
        finally:
            temporary.cleanup()

    def test_static_policy_rejects_private_file_probe(self):
        temporary, root = self.snapshot()
        try:
            source = (ROOT / "graders" / "lab1" / "reference.py").read_text(encoding="utf-8")
            source = source.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\ntry:\n    open('/private/graders/lab1/reference.py').read()\n    PRIVATE_LEAK = True\nexcept (OSError, PermissionError):\n    PRIVATE_LEAK = False\n",
            ).replace(
                'def count_vowels(data: TextInput) -> int:\n    return sum(character.lower() in "aeiou" for character in data.value)',
                'def count_vowels(data: TextInput) -> int:\n    if PRIVATE_LEAK:\n        return -999\n    return sum(character.lower() in "aeiou" for character in data.value)',
            )
            (root / "student_solution.py").write_text(source, encoding="utf-8")
            result = self.grade(root)
            self.assertEqual(result["outcome"], "static_policy_failed", result)
            events = result["private_diagnostics"][0]["security_events"]
            self.assertTrue(any(event["code"] == "CALL_NOT_ALLOWED" for event in events))
        finally:
            temporary.cleanup()

    def test_os_permissions_block_private_grader_even_via_allowed_numpy_api(self):
        temporary, root = self.snapshot()
        try:
            source = (ROOT / "graders" / "lab1" / "reference.py").read_text(encoding="utf-8")
            source = source.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\ntry:\n    np.loadtxt('/private/graders/lab1/reference.py')\n    PRIVATE_LEAK = True\nexcept BaseException:\n    PRIVATE_LEAK = False\n",
            ).replace(
                'def count_vowels(data: TextInput) -> int:\n    return sum(character.lower() in "aeiou" for character in data.value)',
                'def count_vowels(data: TextInput) -> int:\n    if PRIVATE_LEAK:\n        return -999\n    return sum(character.lower() in "aeiou" for character in data.value)',
            )
            (root / "student_solution.py").write_text(source, encoding="utf-8")
            result = self.grade(root)
            self.assertEqual(result["deterministic_gate"], "passed", result)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
