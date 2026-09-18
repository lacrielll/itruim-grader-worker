from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable


def _function(snapshot: Path, selected: dict[str, tuple[Path, int]], name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    location = selected.get(name)
    if not location:
        return None
    tree = ast.parse((snapshot / location[0]).read_text(encoding="utf-8"))
    return next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name), None)


def _calls(node: ast.AST, *names: str) -> bool:
    wanted = set(names)
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        called = child.func.id if isinstance(child.func, ast.Name) else child.func.attr if isinstance(child.func, ast.Attribute) else ""
        if called in wanted:
            return True
    return False


def _nomination(identifier: str, functions: Iterable[str], reason: str) -> dict:
    return {
        "achievement_id": identifier,
        "evidence_ids": [f"check:function:{name}" for name in functions],
        "reason_code": reason,
        "source": "grader:ast",
    }


def detect(snapshot: Path, selected: dict[str, tuple[Path, int]]) -> list[dict]:
    nominations: list[dict] = []

    unique = _function(snapshot, selected, "has_unique_characters")
    if unique and _calls(unique, "set", "frozenset"):
        loops = sum(isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.comprehension)) for node in ast.walk(unique))
        if loops <= 1:
            nominations.append(_nomination("assignment/lab-1/unexpected-set", ["has_unique_characters"], "set_without_nested_scan"))

    factorization = _function(snapshot, selected, "prime_factorization")
    if factorization:
        rendered = ast.unparse(factorization)
        sqrt_bound = _calls(factorization, "sqrt", "isqrt") or "** 0.5" in rendered or "** .5" in rendered
        multiplied_bound = bool(re.search(r"\b([A-Za-z_]\w*)\s*\*\s*\1\s*<=", rendered))
        if sqrt_bound or multiplied_bound:
            nominations.append(_nomination("assignment/lab-1/work-smarter", ["prime_factorization"], "sqrt_factorization_bound"))

    recursive = _function(snapshot, selected, "magic") or _function(snapshot, selected, "multiplicative_persistence")
    if recursive and _calls(recursive, recursive.name):
        nominations.append(_nomination("assignment/lab-1/understand-recursion", ["multiplicative_persistence"], "direct_recursion"))

    sum_prod = _function(snapshot, selected, "sum_prod")
    if sum_prod and _calls(sum_prod, "einsum"):
        nominations.append(_nomination("assignment/lab-1/einstein", ["sum_prod"], "uses_einsum"))

    return nominations
