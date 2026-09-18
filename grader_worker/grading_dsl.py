from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


SEVERITIES = {"critical", "warning", "info"}
KINDS = {"contract", "static", "unit", "property", "integration", "e2e", "performance", "security", "artifact"}


class CheckFailure(AssertionError):
    def __init__(self, message: str, *, code: str = "CHECK_FAILED", public: bool = True):
        super().__init__(message)
        self.code = code
        self.public = public


class Require:
    @staticmethod
    def equal(actual: Any, expected: Any, message: str | None = None) -> None:
        if actual != expected:
            raise CheckFailure(message or f"Ожидалось {expected!r}, получено {actual!r}")

    @staticmethod
    def true(value: Any, message: str = "Условие не выполнено") -> None:
        if not value:
            raise CheckFailure(message)

    @staticmethod
    def finite(value: Any, message: str = "Получено нечисловое или бесконечное значение") -> None:
        import math
        try:
            valid = math.isfinite(float(value))
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise CheckFailure(message)

    @staticmethod
    def less(actual: Any, boundary: Any, message: str | None = None) -> None:
        if not actual < boundary:
            raise CheckFailure(message or f"Ожидалось значение меньше {boundary!r}, получено {actual!r}")


require = Require()


@dataclass(frozen=True)
class Case:
    values: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class AchievementCandidate:
    achievement_id: str
    when: str = "passed"
    reason_code: str | None = None


@dataclass(frozen=True)
class CheckDefinition:
    id: str
    title: str
    kind: str
    severity: str
    points: float
    function: Callable[..., Any]
    cases: tuple[Case, ...] = ()
    achievements: tuple[AchievementCandidate, ...] = ()
    section: str | None = None


def case(*, id: str | None = None, **values: Any):
    def decorate(function: Callable[..., Any]):
        items = list(getattr(function, "__grader_cases__", ()))
        items.insert(0, Case(values, id))
        setattr(function, "__grader_cases__", tuple(items))
        return function
    return decorate


def achievement(achievement_id: str, *, when: str = "passed", reason_code: str | None = None) -> AchievementCandidate:
    if when not in {"passed", "failed"}:
        raise ValueError("achievement when must be passed or failed")
    return AchievementCandidate(achievement_id, when, reason_code)


def check(*, id: str, title: str, kind: str = "unit", severity: str = "critical", points: float = 0,
          achievements: Iterable[AchievementCandidate] = (), section: str | None = None):
    if kind not in KINDS:
        raise ValueError(f"unsupported check kind: {kind}")
    if severity not in SEVERITIES:
        raise ValueError(f"unsupported check severity: {severity}")
    if points < 0:
        raise ValueError("check points cannot be negative")

    def decorate(function: Callable[..., Any]):
        definition = CheckDefinition(id, title, kind, severity, float(points), function,
                                     tuple(getattr(function, "__grader_cases__", ())), tuple(achievements), section)
        setattr(function, "__grader_check__", definition)
        return function
    return decorate


def collect_checks(namespace: Any) -> list[CheckDefinition]:
    values = namespace.values() if isinstance(namespace, dict) else vars(namespace).values()
    definitions = [getattr(value, "__grader_check__") for value in values if hasattr(value, "__grader_check__")]
    ids = [item.id for item in definitions]
    if len(ids) != len(set(ids)):
        raise ValueError("check IDs must be unique")
    return definitions


@dataclass
class CheckExecution:
    definition: CheckDefinition
    status: str
    cases_passed: int
    cases_total: int
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def api_dict(self) -> dict[str, Any]:
        return {
            "id": self.definition.id,
            "name": self.definition.title,
            "category": self.definition.kind,
            "severity": self.definition.severity,
            "section": self.definition.section,
            "status": self.status,
            "passed": self.status == "passed",
            "cases_passed": self.cases_passed,
            "cases_total": self.cases_total,
            "points": {"earned": self.definition.points if self.status == "passed" else 0, "maximum": self.definition.points},
        }


def run_checks(definitions: Iterable[CheckDefinition], context: Any) -> list[CheckExecution]:
    results: list[CheckExecution] = []
    for definition in definitions:
        cases = definition.cases or (Case({}),)
        passed = 0
        diagnostics: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        for index, item in enumerate(cases, start=1):
            try:
                returned = definition.function(context, **item.values)
                if isinstance(returned, dict):
                    evidence.append(returned)
                elif isinstance(returned, list):
                    evidence.extend(value for value in returned if isinstance(value, dict))
                passed += 1
            except CheckFailure as error:
                diagnostics.append({"code": error.code, "message": str(error) if error.public else "Проверка не пройдена", "case": item.id or str(index)})
                break
            except BaseException as error:
                diagnostics.append({"code": "CHECK_EXCEPTION", "message": "Проверка завершилась внутренней ошибкой", "case": item.id or str(index), "error_type": type(error).__name__})
                break
        results.append(CheckExecution(definition, "passed" if passed == len(cases) else "failed", passed, len(cases), diagnostics, evidence))
    return results


def achievement_nominations(executions: Iterable[CheckExecution]) -> list[dict[str, Any]]:
    nominations = []
    for execution in executions:
        for candidate in execution.definition.achievements:
            if candidate.when != execution.status:
                continue
            nominations.append({
                "achievement_id": candidate.achievement_id,
                "evidence_ids": [f"check:{execution.definition.id}"],
                "reason_code": candidate.reason_code or f"check_{execution.status}",
                "source": f"grader:{execution.definition.id}",
            })
    return nominations
