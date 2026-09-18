import unittest

from grader_worker.llm_schema import Criterion, LlmOutputInvalid, assert_public_output_safe, validate_assessment, validate_review


class LlmSchemaTests(unittest.TestCase):
    rubric = [Criterion("understanding", 0, 20, 1)]

    def test_accepts_one_followup_after_first_answer(self):
        value = {"schema_version": 1, "review_stage": "answer_evaluation", "answer_number": 1, "answer_quality": {"status": "insufficient"}, "criteria": [], "next_action": "ask_student_again", "clarification": {"question": "Объясните это на конкретном примере."}}
        self.assertEqual(validate_review(value, self.rubric, set(), 1), value)

    def test_forbids_third_question(self):
        value = {"schema_version": 1, "review_stage": "answer_evaluation", "answer_number": 2, "answer_quality": {"status": "insufficient"}, "criteria": [], "next_action": "ask_student", "clarification": {"question": "Задайте ещё один подробный вопрос."}}
        with self.assertRaises(LlmOutputInvalid):
            validate_review(value, self.rubric, set(), 2)

    def test_rejects_score_and_evidence_outside_contract(self):
        value = {"schema_version": 1, "review_stage": "final", "criteria": [{"criterion_id": "understanding", "score": 21, "evidence_ids": ["unknown"]}], "next_action": "finalize"}
        with self.assertRaises(LlmOutputInvalid):
            validate_review(value, self.rubric, {"known"})

    def test_detects_private_canary_leak(self):
        with self.assertRaises(LlmOutputInvalid):
            assert_public_output_safe({"clarification": {"question": "PRIVATE-CANARY-1"}}, set(), "PRIVATE-CANARY-1")

    def test_achievement_nomination_requires_allowlist_and_known_evidence(self):
        value = {"schema_version": 1, "review_stage": "final", "criteria": [], "next_action": "finalize", "achievement_nominations": [{
            "achievement_id": "assignment/lab-1/explainer", "confidence": "high", "evidence_ids": ["student_answer:1"], "rationale": "Конкретный ответ",
        }]}
        self.assertEqual(validate_review(value, self.rubric, {"student_answer:1"}, 1, {"assignment/lab-1/explainer"}), value)
        with self.assertRaises(LlmOutputInvalid):
            validate_review(value, self.rubric, {"student_answer:1"}, 1, set())

    def test_assessment_scores_every_criterion_from_known_evidence(self):
        value = {"schema_version": 1, "criteria": [{"criterion_id": "understanding", "proposed_score": 18, "evidence_ids": ["grader:test"]}], "total_score": 18, "recommendation": "accept", "blocking_evidence_ids": [], "teacher_summary": "ok"}
        self.assertEqual(validate_assessment(value, self.rubric, {"grader:test"}), value)
        with self.assertRaises(LlmOutputInvalid):
            validate_assessment({**value, "criteria": [{**value["criteria"][0], "evidence_ids": ["invented"]}]}, self.rubric, {"grader:test"})

    def test_reviewer_cannot_emit_critical_evidence(self):
        value = {"schema_version": 1, "review_stage": "final", "evidence": [{"id": "reviewer:x", "severity": "critical"}], "criteria": [], "next_action": "finalize"}
        with self.assertRaises(LlmOutputInvalid):
            validate_review(value, self.rubric, set())


if __name__ == "__main__":
    unittest.main()
