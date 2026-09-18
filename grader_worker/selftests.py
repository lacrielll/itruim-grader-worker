from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from .sandbox import SandboxPolicy, run_sandbox


def run_selftests(assignment: str, root: Path, policy: SandboxPolicy,
                  runner: Callable[..., dict[str, Any]] = run_sandbox) -> dict[str, Any]:
    grader_dir = root / "graders" / assignment
    manifest = json.loads((grader_dir / "selftests.json").read_text(encoding="utf-8"))
    results = []
    for case in manifest.get("cases", []):
        with tempfile.TemporaryDirectory(prefix="grader-selftest-") as temporary:
            snapshot = Path(temporary) / "snapshot"
            snapshot.mkdir()
            shutil.copytree(grader_dir / "contracts" / "grader_contracts", snapshot / "grader_contracts")
            source = grader_dir / case["solution"]
            if source.is_file():
                shutil.copy2(source, snapshot / "student_solution.py")
            result = runner(snapshot, root, grader_dir / "contracts", assignment, policy)
            failures = []
            if case.get("expected_gate") != result.get("deterministic_gate"):
                failures.append(f"gate={result.get('deterministic_gate')!r}")
            expected_code = case.get("expected_diagnostic")
            codes = {item.get("code") for item in result.get("public_diagnostics", [])}
            if expected_code and expected_code not in codes:
                failures.append(f"diagnostic {expected_code} отсутствует")
            results.append({"id": case["id"], "ok": not failures, "failures": failures})
    return {"ok": bool(results) and all(item["ok"] for item in results), "assignment": assignment, "cases": results}
