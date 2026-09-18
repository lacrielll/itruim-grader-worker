from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Diagnostic:
    code: str
    title: str
    message: str
    stage: str
    location: str | None = None
    expected: str | None = None
    actual: str | None = None
    hint: str | None = None
    severity: str = "critical"

    def public_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class GradeResult:
    outcome: str
    deterministic_gate: str
    public_summary: str
    public_diagnostics: list[Diagnostic] = field(default_factory=list)
    private_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    score_earned: float = 0
    score_maximum: float = 100

    def api_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "outcome": self.outcome,
            "score": {"earned": self.score_earned, "maximum": self.score_maximum},
            "checks": self.checks,
            "metrics": {},
            "resource_events": [],
            "achievement_triggers": [],
            "deterministic_gate": self.deterministic_gate,
            "llm_eligible": self.deterministic_gate == "passed",
            "public_summary": self.public_summary,
            "public_diagnostics": [item.public_dict() for item in self.public_diagnostics],
            "private_diagnostics": self.private_diagnostics,
            "evidence": self.evidence,
        }
