from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import resource
import subprocess
import sys
import uuid
import signal
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from grader_worker.models import Diagnostic, GradeResult
from grader_worker.grading_dsl import CheckFailure, run_checks
from grader_worker.pipeline import EventPipeline, PipelineEvent
from grader_contracts.numpy_tasks import BinarizeInput, MatrixVectorBatchInput
from grader_contracts.python_basics import PositiveIntegerInput, TextInput
from . import reference
from .pipeline import Lab1Pipeline
from .suite import build_checks
from .static_achievements import detect as detect_static_achievements


CONTRACT_ROOT = Path("/canonical/grader_contracts")
CONTRACT_FILES = ("__init__.py", "python_basics.py", "numpy_tasks.py")
FUNCTIONS: dict[str, tuple[type, Any]] = {
    "count_vowels": (TextInput, int), "has_unique_characters": (TextInput, bool),
    "multiplicative_persistence": (PositiveIntegerInput, int), "prime_factorization": (PositiveIntegerInput, str),
    "sum_prod": (MatrixVectorBatchInput, np.ndarray), "binarize": (BinarizeInput, np.ndarray),
}


def diagnostic(code: str, title: str, message: str, stage: str, **details: str) -> Diagnostic:
    return Diagnostic(code, title, message, stage, **details)


def verify_contract_files(snapshot: Path) -> list[Diagnostic]:
    problems = []
    submitted_root = snapshot / "grader_contracts"
    if not submitted_root.is_dir():
        return [diagnostic("CONTRACT_DIRECTORY_MISSING", "Не найдена директория контрактов", "Добавьте директорию grader_contracts из starter repository.", "contract", location="grader_contracts")]
    missing = [f"grader_contracts/{name}" for name in CONTRACT_FILES if not (submitted_root / name).is_file()]
    if missing:
        problems.append(diagnostic("CONTRACT_FILE_MISSING", "Не найдены обязательные файлы контрактов", "\n".join(missing), "contract", hint="Восстановите файлы из starter repository без изменений."))
    for name in CONTRACT_FILES:
        submitted = submitted_root / name
        canonical = CONTRACT_ROOT / name
        if submitted.is_file() and hashlib.sha256(submitted.read_bytes()).digest() != hashlib.sha256(canonical.read_bytes()).digest():
            problems.append(diagnostic("CONTRACT_TAMPERED", "Файл контракта изменён", f"Содержимое grader_contracts/{name} не совпадает с опубликованным контрактом.", "contract", location=f"grader_contracts/{name}", hint="Восстановите файл из starter repository."))
    return problems


def discover(snapshot: Path) -> tuple[dict[str, tuple[Path, int]], list[Diagnostic]]:
    found: dict[str, list[tuple[Path, int]]] = {name: [] for name in FUNCTIONS}
    diagnostics: list[Diagnostic] = []
    for path in snapshot.rglob("*.py"):
        relative = path.relative_to(snapshot)
        if "grader_contracts" in relative.parts or any(part.startswith(".") for part in relative.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        except (SyntaxError, UnicodeDecodeError) as error:
            diagnostics.append(diagnostic("IMPORT_FAILED", "Python-файл не удалось разобрать", str(error), "import", location=str(relative)))
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in found:
                found[node.name].append((relative, node.lineno))
    selected: dict[str, tuple[Path, int]] = {}
    for name, locations in found.items():
        if not locations:
            diagnostics.append(diagnostic("CONTRACT_SYMBOL_MISSING", "Не найдена обязательная функция", f"Grader не нашёл функцию {name} ни в одном Python-модуле.", "contract", expected=f"def {name}(...)", hint="Реализуйте функцию с указанным именем в обычном .py файле."))
        elif len(locations) > 1:
            rendered = ", ".join(f"{path}:{line}" for path, line in locations)
            diagnostics.append(diagnostic("CONTRACT_SYMBOL_AMBIGUOUS", "Найдено несколько функций с одним именем", f"Функция {name} объявлена несколько раз: {rendered}", "contract", hint="Оставьте одно верхнеуровневое определение функции."))
        else:
            selected[name] = locations[0]
    return selected, diagnostics


def cases() -> dict[str, list[Any]]:
    return {
        "count_vowels": [TextInput("hello"), TextInput("AEIOUxyz"), TextInput(""), TextInput("bcdfg"), TextInput("AbRaCaDaBrA"), TextInput("a" * 100_000 + "z" * 100_000)],
        "has_unique_characters": [TextInput("abc"), TextInput("hello"), TextInput(""), TextInput("a"), TextInput("абвгд"), TextInput("".join(chr(0x1000 + i) for i in range(20_000)))],
        "multiplicative_persistence": [PositiveIntegerInput(4), PositiveIntegerInput(39), PositiveIntegerInput(999), PositiveIntegerInput(277777788888899)],
        "prime_factorization": [PositiveIntegerInput(2), PositiveIntegerInput(12), PositiveIntegerInput(86240), PositiveIntegerInput(2**20), PositiveIntegerInput(1_000_000_007)],
        "sum_prod": [MatrixVectorBatchInput(np.arange(18).reshape(2, 3, 3), np.arange(6).reshape(2, 3, 1)), MatrixVectorBatchInput(np.ones((40, 30, 30)), np.ones((40, 30, 1)))],
        "binarize": [BinarizeInput(np.array([[0.5, 0.6], [-1, 2.0]]), 0.5), BinarizeInput(np.array([0, 2, 3]), 2), BinarizeInput(np.linspace(-2, 2, 100_000), 0.125)],
    }


def normalize(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: normalize(item) for key, item in asdict(value).items()}
    if isinstance(value, np.ndarray):
        return value
    return value


def wire_encode(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: wire_encode(item) for key, item in asdict(value).items()}
    if isinstance(value, np.ndarray):
        return {"__ndarray__": value.tolist(), "dtype": str(value.dtype)}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: wire_encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire_encode(item) for item in value]
    return value


def wire_decode(value: Any) -> Any:
    if isinstance(value, dict) and "__ndarray__" in value:
        return np.asarray(value["__ndarray__"], dtype=value.get("dtype"))
    if isinstance(value, dict) and "__dataclass__" in value:
        return {key: wire_decode(item) for key, item in value["fields"].items()}
    if isinstance(value, dict):
        return {key: wire_decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [wire_decode(item) for item in value]
    return value


def execute_student(snapshot: Path, name: str, relative: Path, input_value: Any) -> dict[str, Any]:
    request_path = Path("/tmp") / f"request-{uuid.uuid4().hex}.json"
    result_path = Path("/tmp") / f"result-{uuid.uuid4().hex}.json"
    input_type = FUNCTIONS[name][0]
    expected_return = FUNCTIONS[name][1]
    return_types = expected_return if isinstance(expected_return, tuple) else (expected_return,)
    request = {
        "module": ".".join(relative.with_suffix("").parts), "function": name,
        "input_type": f"{input_type.__module__}.{input_type.__name__}",
        "return_types": [f"{item.__module__}.{item.__name__}" for item in return_types], "fields": wire_encode(input_value),
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    request_path.chmod(0o644)

    def demote() -> None:
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)

    environment = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": "/canonical:/submission:/grader", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    try:
        process = subprocess.Popen(
            [sys.executable, "/grader/student_executor.py", "--request", str(request_path), "--result", str(result_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, preexec_fn=demote, env=environment, start_new_session=True,
        )
        try:
            _, stderr_bytes = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            return {"ok": False, "phase": "runtime", "error_type": "TimeoutError", "message": "Функция превысила лимит времени отдельного теста"}
        if not result_path.exists():
            return {"ok": False, "phase": "runtime", "error_type": "StudentProcessFailed", "message": stderr_bytes.decode(errors="replace")[-1000:]}
        return json.loads(result_path.read_text(encoding="utf-8"))
    finally:
        for process_dir in Path("/proc").iterdir():
            if not process_dir.name.isdigit():
                continue
            try:
                status = (process_dir / "status").read_text()
                uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
                if int(uid_line.split()[1]) == 10001:
                    os.kill(int(process_dir.name), signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError, PermissionError, StopIteration, ValueError):
                pass
        request_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)


def assert_equivalent(actual: Any, expected: Any) -> None:
    actual, expected = normalize(actual), normalize(expected)
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise AssertionError(f"ожидались поля {list(expected)}, получено {type(actual).__name__}")
        for key in expected:
            assert_equivalent(actual[key], expected[key])
    elif isinstance(expected, np.ndarray):
        np.testing.assert_allclose(np.asarray(actual), expected, rtol=1e-6, atol=1e-8)
    elif isinstance(expected, float):
        if not math.isclose(float(actual), expected, rel_tol=1e-7, abs_tol=1e-9):
            raise AssertionError(f"ожидалось {expected}, получено {actual}")
    elif actual != expected:
        raise AssertionError(f"ожидалось {expected!r}, получено {actual!r}")


class Lab1Context:
    def __init__(self, snapshot: Path, selected: dict[str, tuple[Path, int]]):
        self.snapshot = snapshot
        self.selected = selected

    def verify(self, name: str, input_value: Any) -> dict[str, Any]:
        relative, line = self.selected[name]
        execution = execute_student(self.snapshot, name, relative, input_value)
        if not execution["ok"]:
            if execution.get("phase") == "signature":
                raise CheckFailure(f"{name}: {execution['message']}", code="CONTRACT_SIGNATURE_INVALID")
            if execution.get("error_type") == "TimeoutError":
                raise CheckFailure("Функция превысила лимит времени отдельного теста", code="TIME_LIMIT_EXCEEDED")
            raise CheckFailure(execution.get("message") or execution.get("error_type", "Ошибка выполнения"), code="RUNTIME_EXCEPTION")
        encoded_actual = execution["value"]
        actual = wire_decode(encoded_actual)
        expected = getattr(reference, name)(input_value)
        expected_type = FUNCTIONS[name][1]
        if isinstance(expected_type, type) and hasattr(expected_type, "__dataclass_fields__"):
            actual_type_ok = isinstance(encoded_actual, dict) and encoded_actual.get("__dataclass__") == f"{expected_type.__module__}.{expected_type.__name__}"
        else:
            actual_type_ok = isinstance(actual, expected_type)
        if not actual_type_ok:
            expected_name = " | ".join(item.__name__ for item in (expected_type if isinstance(expected_type, tuple) else (expected_type,)))
            raise CheckFailure(f"{name} вернула {type(actual).__name__}; ожидался {expected_name}", code="CONTRACT_RETURN_TYPE_INVALID")
        try:
            assert_equivalent(actual, expected)
        except AssertionError as error:
            raise CheckFailure(str(error), code="REFERENCE_MISMATCH") from error
        return {"type": "check_case", "function": name, "status": "passed", "location": f"{relative}:{line}"}


def grade(snapshot: Path) -> dict[str, Any]:
    diagnostics = verify_contract_files(snapshot)
    selected, discovery_diagnostics = discover(snapshot)
    diagnostics.extend(discovery_diagnostics)
    if diagnostics:
        return GradeResult("contract_failed", "failed", f"Контракт не пройден: найдено ошибок — {len(diagnostics)}", diagnostics).api_dict()
    all_cases = cases()
    executions = run_checks(build_checks(all_cases), Lab1Context(snapshot, selected))
    checks = [item.api_dict() for item in executions]
    failures = []
    for execution in executions:
        for item in execution.diagnostics:
            failures.append(diagnostic(item["code"], f"Тест функции {execution.definition.title} не пройден", item["message"],
                                       "resource" if item["code"] == "TIME_LIMIT_EXCEEDED" else "test",
                                       location=str(selected[execution.definition.title][0]), hint="Проверьте граничные случаи и соответствие контракту."))
    passed_checks = sum(check["passed"] for check in checks)
    score = round(100 * passed_checks / len(checks), 2)
    if failures:
        return GradeResult("tests_failed", "failed", f"Пройдено функций: {passed_checks} из {len(checks)}", failures, evidence={"function_checks": checks}, checks=checks, score_earned=score).api_dict()
    result = GradeResult("completed", "passed", f"Все {len(checks)} функций прошли автоматические тесты", evidence={"function_checks": checks}, checks=checks, score_earned=100).api_dict()
    evidence_ids = tuple(f"check:{item['id']}" for item in checks)
    actions = EventPipeline(Lab1Pipeline(), allowed_achievements=["assignment/lab-1/all-functions"]).dispatch(
        PipelineEvent("lab1-finalized", "submission.finalized", {"outcome": "passed"}, evidence_ids),
        {"checks": checks, "evidence_ids": list(evidence_ids)},
    )
    result["achievement_triggers"] = actions.api_dict()["achievement_triggers"]
    result["achievement_triggers"].extend(detect_static_achievements(snapshot, selected))
    return result
