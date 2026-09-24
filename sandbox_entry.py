from __future__ import annotations

import argparse
import json
import os
import traceback
import importlib
import re
from pathlib import Path
from grader_worker.policy import findings_as_events, load_python_policy, scan_python_tree


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    try:
        policy = load_python_policy(Path("/private/graders") / args.assignment / "python-policy.json")
        findings = scan_python_tree(Path("/submission"), policy)
        if findings:
            result = {
                "schema_version": 1, "outcome": "static_policy_failed", "score": {"earned": 0, "maximum": 100},
                "checks": [], "metrics": {}, "resource_events": [], "achievement_triggers": [], "deterministic_gate": "failed",
                "llm_eligible": False, "public_summary": "Исходный код не прошёл проверку разрешённых возможностей Python",
                "public_diagnostics": [{"code": "CODE_POLICY_VIOLATION", "title": "Недопустимая конструкция", "message": "Удалите запрещённые импорты или операции и отправьте новый commit.", "stage": "import"}],
                "private_diagnostics": [{"security_events": findings_as_events(findings)}], "evidence": {"policy_findings": len(findings)},
            }
        else:
            result = None
        if result is not None:
            temporary = output.with_suffix(".tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, output)
            return
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", args.assignment):
            raise RuntimeError(f"Unknown assignment grader: {args.assignment}")
        module = importlib.import_module(f"graders.{args.assignment}.grader")
        grade = module.grade
        result = grade(Path("/submission"))
    except BaseException as error:
        result = {
            "schema_version": 1, "outcome": "grader_internal_error", "score": {"earned": 0, "maximum": 100},
            "checks": [], "metrics": {}, "resource_events": [], "achievement_triggers": [], "deterministic_gate": "failed",
            "llm_eligible": False, "public_summary": "Внутренняя ошибка автоматической проверки",
            "public_diagnostics": [], "private_diagnostics": [{"error": type(error).__name__, "traceback": traceback.format_exc()[-12000:]}], "evidence": {},
        }
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, output)


if __name__ == "__main__":
    main()
