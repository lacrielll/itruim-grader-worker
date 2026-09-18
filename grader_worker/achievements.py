from __future__ import annotations

from typing import Any


def resolve_achievement_triggers(result: dict[str, Any], definitions: list[dict[str, Any]], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Validate grader nominations and add declarative runtime nominations.

    The platform remains the award authority. Old assignment versions with no
    definitions intentionally receive no nominations.
    """
    allowed = {item["id"]: item for item in definitions}
    context = context or {}
    resolved: list[dict[str, Any]] = []
    for trigger in result.get("achievement_triggers", []):
        definition = allowed.get(trigger.get("achievement_id"))
        source = str(trigger.get("source", "")).split(":", 1)[0]
        if definition and source in definition.get("allowed_sources", []):
            resolved.append(trigger)
    events = result.get("resource_events", [])
    for definition in definitions:
        if "runtime" not in definition.get("allowed_sources", []):
            continue
        trigger = definition.get("trigger", {})
        if trigger.get("source") not in {None, "runtime"}:
            continue
        outcome_matches = not trigger.get("outcome") or trigger["outcome"] == result.get("outcome")
        matched_indexes = [index for index, event in enumerate(events) if not trigger.get("event_kind") or event.get("kind") == trigger["event_kind"]]
        if outcome_matches and (matched_indexes or (trigger.get("outcome") and not trigger.get("event_kind"))):
            evidence_ids = [f"runtime:event:{index}" for index in matched_indexes] or [f"runtime:outcome:{result.get('outcome')}"]
            resolved.append({
                "achievement_id": definition["id"], "evidence_ids": evidence_ids,
                "reason_code": trigger.get("reason_code", "runtime_trigger_matched"), "source": "runtime",
            })
    if result.get("deterministic_gate") == "passed" and int(context.get("attempt_number", 0)) == 1:
        for definition in definitions:
            trigger = definition.get("trigger", {})
            if "grader" in definition.get("allowed_sources", []) and trigger.get("event") == "first_submission_passed":
                passed_ids = [str(item.get("id")) for item in result.get("checks", []) if item.get("passed") is True or item.get("status") in {"passed", "ok"}]
                if passed_ids:
                    resolved.append({
                        "achievement_id": definition["id"], "evidence_ids": passed_ids,
                        "reason_code": trigger.get("reason_code", "first_submission_all_tests_passed"),
                        "source": "grader:first-submission",
                    })
    unique = {}
    for item in resolved:
        key = (item["achievement_id"], item["source"], item["reason_code"], tuple(item["evidence_ids"]))
        unique[key] = item
    return list(unique.values())
