from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class LlmOutputInvalid(ValueError):
    pass


@dataclass(frozen=True)
class Criterion:
    id: str
    min_score: float
    max_score: float
    score_step: float = 1


def _fail(message: str) -> None:
    raise LlmOutputInvalid(message)


def validate_review(value: Any, rubric: list[Criterion], available_evidence: set[str], answer_number: int = 0,
                    allowed_achievements: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        _fail("unsupported schema_version")
    stage = value.get("review_stage")
    if stage not in {"initial", "answer_evaluation", "final"}:
        _fail("invalid review_stage")
    if stage == "answer_evaluation":
        if value.get("answer_number") != answer_number or answer_number not in {1, 2}:
            _fail("invalid answer_number")
        allowed = {"sufficient", "partially_sufficient", "insufficient", "contradictory", "off_topic", "suspected_non_understanding"}
        if value.get("answer_quality", {}).get("status") not in allowed:
            _fail("invalid answer quality")
    reviewer_evidence = value.get("evidence", [])
    if not isinstance(reviewer_evidence, list) or len(reviewer_evidence) > 50:
        _fail("invalid reviewer evidence")
    for item in reviewer_evidence:
        if not isinstance(item, dict) or item.get("severity") not in {"warning", "positive"}:
            _fail("reviewer evidence may only be warning or positive")
        if not isinstance(item.get("id"), str) or not item["id"].startswith("reviewer:"):
            _fail("invalid reviewer evidence id")
    available_evidence = available_evidence | {item["id"] for item in reviewer_evidence}
    criteria = value.get("criteria", [])
    expected = {item.id: item for item in rubric}
    seen: set[str] = set()
    for item in criteria:
        identifier = item.get("criterion_id")
        if identifier not in expected or identifier in seen:
            _fail("unknown or duplicate criterion")
        seen.add(identifier)
        score = item.get("score")
        if score is not None:
            criterion = expected[identifier]
            if not criterion.min_score <= score <= criterion.max_score:
                _fail("criterion score outside range")
            steps = (score - criterion.min_score) / criterion.score_step
            if abs(steps - round(steps)) > 1e-8:
                _fail("criterion score violates score_step")
        if not set(item.get("evidence_ids", [])).issubset(available_evidence):
            _fail("unknown evidence reference")
    action = value.get("next_action")
    if action not in {"ask_student", "ask_student_again", "finalize"}:
        _fail("invalid next_action")
    if action == "ask_student_again" and answer_number != 1:
        _fail("a second question is allowed only after answer one")
    if answer_number == 2 and action != "finalize":
        _fail("third question is forbidden")
    if action.startswith("ask_student"):
        question = value.get("clarification", {}).get("question", "")
        if not isinstance(question, str) or not 10 <= len(question) <= 2000:
            _fail("invalid clarification question")
    allowed_achievements = allowed_achievements or set()
    for nomination in value.get("achievement_nominations", []):
        if nomination.get("achievement_id") not in allowed_achievements:
            _fail("unknown achievement nomination")
        if nomination.get("confidence") not in {"low", "medium", "high"}:
            _fail("invalid achievement confidence")
        evidence_ids = nomination.get("evidence_ids", [])
        if not evidence_ids or not set(evidence_ids).issubset(available_evidence):
            _fail("unknown achievement evidence")
    return value


def validate_assessment(value: Any, rubric: list[Criterion], available_evidence: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        _fail("unsupported assessment schema")
    if value.get("recommendation") not in {"accept", "revise", "manual_defense", "reject"}:
        _fail("invalid assessment recommendation")
    expected = {item.id: item for item in rubric}
    seen: set[str] = set()
    total = 0.0
    for item in value.get("criteria", []):
        identifier = item.get("criterion_id")
        if identifier not in expected or identifier in seen:
            _fail("unknown or duplicate assessment criterion")
        seen.add(identifier); score = item.get("proposed_score"); criterion = expected[identifier]
        if not isinstance(score, (int, float)) or not criterion.min_score <= score <= criterion.max_score:
            _fail("assessment score outside range")
        if abs((score - criterion.min_score) / criterion.score_step - round((score - criterion.min_score) / criterion.score_step)) > 1e-8:
            _fail("assessment score violates step")
        evidence_ids = item.get("evidence_ids", [])
        if not evidence_ids or not set(evidence_ids).issubset(available_evidence):
            _fail("assessment must cite known evidence")
        total += score
    if seen != set(expected):
        _fail("assessment must score every criterion")
    if abs(float(value.get("total_score", -1)) - total) > 1e-8:
        _fail("assessment total mismatch")
    return value


def assert_public_output_safe(value: Any, teacher_only_ids: set[str], canary: str) -> None:
    public = str({"clarification": value.get("clarification"), "student_feedback": value.get("student_feedback")})
    if canary and canary in public:
        _fail("private evidence canary leaked")
    if any(identifier in public for identifier in teacher_only_ids):
        _fail("teacher-only evidence leaked")
