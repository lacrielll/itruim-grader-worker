from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path

ALLOWED_IMPORT_ROOTS = {"__future__", "collections", "dataclasses", "functools", "grader_contracts", "itertools", "math", "numpy", "statistics", "typing"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open", "input", "breakpoint"}
FORBIDDEN_ATTRIBUTES = {"system", "popen", "spawn", "fork", "connect", "request", "urlopen"}

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

def scan_python_tree(root: Path) -> list[PolicyFinding]:
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
                    if alias.name.split(".", 1)[0] not in ALLOWED_IMPORT_ROOTS:
                        findings.append(_finding("IMPORT_NOT_ALLOWED", relative, node, import_name=alias.name))
            elif isinstance(node, ast.ImportFrom):
                root_name = (node.module or "").split(".", 1)[0]
                if node.level or root_name not in ALLOWED_IMPORT_ROOTS:
                    findings.append(_finding("IMPORT_NOT_ALLOWED", relative, node, import_name=("." * node.level) + (node.module or "")))
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                    findings.append(_finding("CALL_NOT_ALLOWED", relative, node, call=node.func.id))
                elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRIBUTES:
                    findings.append(_finding("CALL_NOT_ALLOWED", relative, node, call=node.func.attr))
            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                findings.append(_finding("DUNDER_ACCESS_NOT_ALLOWED", relative, node, attribute=node.attr))
    return findings

def findings_as_events(findings: list[PolicyFinding]) -> list[dict]:
    return [asdict(finding) for finding in findings]
