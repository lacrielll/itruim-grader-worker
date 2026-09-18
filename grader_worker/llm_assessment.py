from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .llm_config import configured_providers
from .llm_providers import complete_with_fallback
from .llm_sanitize import build_assessment_messages, sanitize_grader_evidence
from .llm_schema import Criterion, validate_assessment
from .llm_quota import QuotaLedger

PROMPT_VERSION = "platform-assessment-v1"


def normalized_evidence(result: dict, review: dict) -> list[dict]:
    safe = sanitize_grader_evidence(result)
    items = [{"id": check["id"], "source": "grader", "severity": "positive" if check["status"] in {"passed", "ok"} else check.get("severity", "warning"),
              "category": check["category"], "summary": check["public_summary"], "confidence": "deterministic"} for check in safe["checks"]]
    for item in review.get("evidence", []):
        items.append({key: item.get(key) for key in ("id", "source", "severity", "category", "criterion_id", "summary", "facts", "confidence") if item.get(key) is not None})
    return items


def run_assessment(rubric_data: dict, deterministic_result: dict, reviewer_result: dict, submission_id: str) -> dict:
    providers = configured_providers()
    if not providers:
        raise RuntimeError("no LLM providers configured")
    rubric = [Criterion(item["id"], item["min_score"], item["max_score"], item.get("score_step", 1)) for item in rubric_data.get("criteria", [])]
    evidence = normalized_evidence(deterministic_result, reviewer_result)
    contract = {"schema_version": 1, "criteria": [{"criterion_id": "every rubric ID", "proposed_score": 0, "evidence_ids": ["known evidence ID"], "rationale": "short rationale", "confidence": "high|medium|low"}], "total_score": 0, "blocking_evidence_ids": [], "recommendation": "accept|revise|manual_defense|reject", "teacher_summary": "short Russian summary"}
    messages = build_assessment_messages(rubric=rubric_data, evidence=evidence, reviewer_summary={"answer_quality": reviewer_result.get("answer_quality"), "student_feedback": reviewer_result.get("student_feedback")})
    messages[-1]["content"] += "\nOUTPUT_CONTRACT:\n" + json.dumps(contract, ensure_ascii=False)
    input_hash = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    reservation = f"{submission_id}:assessment"
    ledger = QuotaLedger(Path(os.getenv("LLM_QUOTA_DB", ".worker-state/llm-quota.db")))
    ledger.reserve(reservation, int(os.getenv("LLM_ASSESSMENT_RESERVED_TOKENS", "12000")), int(os.getenv("LLM_LOCAL_DAILY_TOKEN_BUDGET", "200000")))
    try:
        completion, attempts = complete_with_fallback(providers, messages, lambda value: validate_assessment(value, rubric, {item["id"] for item in evidence}), int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4000")), int(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "120")))
        report = {severity: [{"id": item["id"], "summary": item.get("summary", ""), "category": item.get("category", "other")} for item in evidence if item.get("severity") == severity] for severity in ("critical", "warning", "positive")}
        completion.value["evidence_report"] = report
        ledger.finish(reservation, True)
        return {"result": completion.value, "provider": completion.provider, "model": completion.model, "input_hash": input_hash, "prompt_version": PROMPT_VERSION, "attempts": attempts}
    except BaseException:
        ledger.finish(reservation, False)
        raise
