import unittest

from grader_worker.achievements import resolve_achievement_triggers


class AchievementResolutionTests(unittest.TestCase):
    def test_old_assignment_without_definitions_drops_nomination(self):
        result = {"achievement_triggers": [{"achievement_id": "assignment/lab-1/all-functions", "source": "pipeline:x", "reason_code": "ok", "evidence_ids": ["check:x"]}], "resource_events": []}
        self.assertEqual(resolve_achievement_triggers(result, []), [])

    def test_runtime_event_can_nominate_configured_achievement(self):
        definitions = [{
            "id": "assignment/lab-1/memory-limit", "allowed_sources": ["runtime"],
            "trigger": {"source": "runtime", "event_kind": "memory_or_termination", "reason_code": "memory_limit"},
        }]
        result = {"outcome": "resource_limit_exceeded", "achievement_triggers": [], "resource_events": [{"kind": "memory_or_termination"}]}
        self.assertEqual(resolve_achievement_triggers(result, definitions)[0]["source"], "runtime")

    def test_first_success_only_nominates_on_first_assignment_submission(self):
        definitions = [{
            "id": "common/first-try", "allowed_sources": ["grader"],
            "trigger": {"event": "first_submission_passed"},
        }]
        result = {"deterministic_gate": "passed", "achievement_triggers": [], "resource_events": [], "checks": [{"id": "function:a", "passed": True}]}
        nomination = resolve_achievement_triggers(result, definitions, {"attempt_number": 1})
        self.assertEqual(nomination[0]["achievement_id"], "common/first-try")
        self.assertEqual(resolve_achievement_triggers(result, definitions, {"attempt_number": 2}), [])


if __name__ == "__main__":
    unittest.main()
