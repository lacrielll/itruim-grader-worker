from __future__ import annotations

import unittest

from grader_worker.runtime_profiles import RuntimeLimits, RuntimeProfile, RuntimeRegistry
from grader_worker.stages import CommandStage, LinearPipelineRunner, PipelineDefinition, StageResult, StageStatus


class FakeExecutor:
    def __init__(self, outcomes):
        self.outcomes = {key: list(value) for key, value in outcomes.items()}
        self.calls = []

    def execute(self, stage, runtime, context):
        self.calls.append((stage.id, runtime.name))
        status = self.outcomes[stage.id].pop(0)
        return StageResult(stage.id, status, status.value)


def registry():
    return RuntimeRegistry({
        "python": RuntimeProfile("python", "grader-python:v1", allowed_commands=frozenset({"python"}), limits=RuntimeLimits(timeout_seconds=60)),
        "cpp": RuntimeProfile("cpp", "grader-cpp:v1", allowed_commands=frozenset({"g++"}), limits=RuntimeLimits(memory_mb=512, timeout_seconds=60)),
    })


class LinearPipelineTests(unittest.TestCase):
    def test_each_stage_selects_its_own_runtime(self):
        executor = FakeExecutor({"compile": [StageStatus.PASSED], "test": [StageStatus.PASSED]})
        pipeline = PipelineDefinition("cpp-lab", (
            CommandStage("compile", "Компиляция", "cpp", command=("g++", "main.cpp")),
            CommandStage("test", "Тесты", "python", command=("python", "tests.py")),
        ))
        result = LinearPipelineRunner(registry(), executor).run(pipeline, "/submission")
        self.assertEqual(executor.calls, [("compile", "cpp"), ("test", "python")])
        self.assertEqual([item.status for item in result.results], [StageStatus.PASSED, StageStatus.PASSED])

    def test_failure_stops_and_marks_remaining_stages_skipped(self):
        executor = FakeExecutor({"compile": [StageStatus.FAILED], "test": [StageStatus.PASSED]})
        pipeline = PipelineDefinition("cpp-lab", (
            CommandStage("compile", "Компиляция", "cpp", command=("g++", "main.cpp")),
            CommandStage("test", "Тесты", "python", command=("python", "tests.py")),
        ))
        result = LinearPipelineRunner(registry(), executor).run(pipeline, "/submission")
        self.assertEqual([item.status for item in result.results], [StageStatus.FAILED, StageStatus.SKIPPED])
        self.assertEqual(executor.calls, [("compile", "cpp")])

    def test_infrastructure_failure_is_retried_only_as_configured(self):
        executor = FakeExecutor({"test": [StageStatus.INFRA_ERROR, StageStatus.PASSED]})
        pipeline = PipelineDefinition("retry", (
            CommandStage("test", "Тесты", "python", command=("python", "tests.py"), retry_on_infra_error=1),
        ))
        result = LinearPipelineRunner(registry(), executor).run(pipeline, "/submission")
        self.assertEqual(result.results[0].status, StageStatus.PASSED)
        self.assertEqual(len(executor.calls), 2)

    def test_stage_cannot_raise_runtime_limits(self):
        pipeline = PipelineDefinition("unsafe", (
            CommandStage("test", "Тесты", "python", limits=RuntimeLimits(memory_mb=1024), command=("python", "tests.py")),
        ))
        with self.assertRaises(ValueError):
            pipeline.validate(registry())

    def test_arbitrary_command_is_rejected(self):
        pipeline = PipelineDefinition("unsafe", (
            CommandStage("shell", "Shell", "python", command=("bash", "-c", "anything")),
        ))
        with self.assertRaises(ValueError):
            pipeline.validate(registry())


if __name__ == "__main__":
    unittest.main()
