from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EMPTY_NAMES = frozenset[str]()

@dataclass(frozen=True)
class PythonPolicy:
    allowed_import_roots: frozenset[str] | None = None
    forbidden_calls: frozenset[str] = EMPTY_NAMES
    forbidden_attributes: frozenset[str] = EMPTY_NAMES
    forbid_dunder_attributes: bool = False
    allow_relative_imports: bool = True

def load_python_policy(path: Path) -> PythonPolicy:
    if not path.is_file(): return PythonPolicy()
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict): raise ValueError("python-policy.json must be an object")
    unknown = set(raw) - {"allowed_import_roots", "forbidden_calls", "forbidden_attributes", "forbid_dunder_attributes", "allow_relative_imports"}
    if unknown: raise ValueError(f"unknown python-policy.json keys: {', '.join(sorted(unknown))}")
    imports = raw.get("allowed_import_roots")
    if imports is not None and (not isinstance(imports, list) or not all(isinstance(item, str) and item for item in imports)):
        raise ValueError("allowed_import_roots must be an array of non-empty strings")
    def strings(key: str) -> frozenset[str]:
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value): raise ValueError(f"{key} must be an array of non-empty strings")
        return frozenset(value)
    return PythonPolicy(
        frozenset(imports) if imports is not None else None,
        strings("forbidden_calls"), strings("forbidden_attributes"),
        bool(raw.get("forbid_dunder_attributes", False)),
        bool(raw.get("allow_relative_imports", True)),
    )

@dataclass(frozen=True)
class PolicyFinding:
    severity: str
    code: str
    stage: str
    source_path: str
    source_line: int
    details: dict[str, str]

def _finding(code: str, path: Path, node: ast.AST, **details: str) -> PolicyFinding:
    return PolicyFinding("critical", code, "static_policy", path.as_posix(), getattr(node, "lineno", 1), details)

def scan_python_tree(root: Path, policy: PythonPolicy | None = None) -> list[PolicyFinding]:
    policy = policy or PythonPolicy()
    findings: list[PolicyFinding] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative.as_posix())
        except (UnicodeError, SyntaxError) as error:
            findings.append(PolicyFinding("critical", "PYTHON_PARSE_FAILED", "static_policy", relative.as_posix(), getattr(error, "lineno", 1) or 1, {"error": type(error).__name__}))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if policy.allowed_import_roots is not None and alias.name.split(".", 1)[0] not in policy.allowed_import_roots:
                        findings.append(_finding("IMPORT_NOT_ALLOWED", relative, node, import_name=alias.name))
            elif isinstance(node, ast.ImportFrom):
                root_name = (node.module or "").split(".", 1)[0]
                if (node.level and not policy.allow_relative_imports) or (not node.level and policy.allowed_import_roots is not None and root_name not in policy.allowed_import_roots):
                    findings.append(_finding("IMPORT_NOT_ALLOWED", relative, node, import_name=("." * node.level) + (node.module or "")))
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in policy.forbidden_calls:
                    findings.append(_finding("CALL_NOT_ALLOWED", relative, node, call=node.func.id))
                elif isinstance(node.func, ast.Attribute) and node.func.attr in policy.forbidden_attributes:
                    findings.append(_finding("CALL_NOT_ALLOWED", relative, node, call=node.func.attr))
            elif policy.forbid_dunder_attributes and isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                findings.append(_finding("DUNDER_ACCESS_NOT_ALLOWED", relative, node, attribute=node.attr))
    return findings

def findings_as_events(findings: list[PolicyFinding]) -> list[dict]:
    return [asdict(finding) for finding in findings]
