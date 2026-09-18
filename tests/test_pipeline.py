import unittest

from grader_worker.pipeline import EventPipeline, PipelineEvent, on


class ExamplePipeline:
    @on("runtime.limit_exceeded", emits=["assignment/lab-1/memory-comeback"])
    def memory(self, event, state, achievements):
        achievements.nominate("assignment/lab-1/memory-comeback", evidence_ids=event.evidence_ids, reason_code="memory_recovered")


class PipelineTests(unittest.TestCase):
    def test_pipeline_nominates_only_allowlisted_achievement_with_evidence(self):
        pipeline = EventPipeline(ExamplePipeline(), allowed_achievements=["assignment/lab-1/memory-comeback"])
        result = pipeline.dispatch(PipelineEvent("event-1", "runtime.limit_exceeded", {}, ("ev-memory",)), {"evidence_ids": []})
        self.assertEqual(result.nominations[0].achievement_id, "assignment/lab-1/memory-comeback")

    def test_unknown_evidence_is_rejected(self):
        pipeline = EventPipeline(ExamplePipeline(), allowed_achievements=["assignment/lab-1/memory-comeback"])
        with self.assertRaises(ValueError):
            pipeline.dispatch(PipelineEvent("event-1", "runtime.limit_exceeded", {}), {"evidence_ids": []})

    def test_invalid_namespace_is_rejected(self):
        class Bad:
            @on("check.completed", emits=["whatever/badge"])
            def event(self, event, state, achievements):
                pass
        with self.assertRaises(ValueError):
            EventPipeline(Bad(), allowed_achievements=["whatever/badge"])


if __name__ == "__main__":
    unittest.main()
