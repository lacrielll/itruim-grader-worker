from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from .policy import load_python_policy, scan_python_tree
from .repository import RepositoryFailure, validate_snapshot


def precheck(assignment: str, submission: Path, root: Path) -> dict[str, Any]:
    template_path = root / "graders" / assignment / "assignment-template.json"
    if not template_path.is_file():
        return {"ok": False, "errors": [{"code": "ASSIGNMENT_UNKNOWN", "message": f"Неизвестная лабораторная: {assignment}"}], "warnings": []}
    template = json.loads(template_path.read_text(encoding="utf-8"))
    errors: list[dict[str, str]] = []
    try:
        stats = validate_snapshot(submission)
    except RepositoryFailure as error:
        errors.append({"code": error.code, "message": str(error)})
        stats = {"files": 0, "bytes": 0}
    policy_path = root / "graders" / assignment / "python-policy.json"
    try:
        policy = load_python_policy(policy_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"ok": False, "assignment": assignment, "stats": {"files": 0, "bytes": 0}, "errors": [{"code": "POLICY_INVALID", "message": str(error)}], "warnings": []}
    for finding in scan_python_tree(submission, policy):
        errors.append({"code": finding.code, "message": f"{finding.source_path}:{finding.source_line}", "path": finding.source_path})
    contract = template.get("grader_contract", {})
    for required in contract.get("required_files", []):
        if not (submission / required).is_file():
            errors.append({"code": "CONTRACT_FILE_MISSING", "message": f"Не найден обязательный файл {required}", "path": required})
    symbols: set[str] = set()
    for path in submission.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeError):
            continue
        symbols.update(node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    for function in contract.get("functions", []):
        if function.get("name") not in symbols:
            errors.append({"code": "CONTRACT_SYMBOL_MISSING", "message": f"Не найдена функция {function.get('name')}"})
    return {"ok": not errors, "assignment": assignment, "stats": stats, "errors": errors, "warnings": [], "note": "Precheck проверяет структуру и policy этой лабораторной, но не запускает скрытые тесты."}
