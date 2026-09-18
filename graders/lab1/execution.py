from grader_worker.stages import LegacyGraderStage, PipelineDefinition


# Lab 1 keeps its proven private harness while participating in the universal
# execution-plan model. The next assignments can use CommandStage or additional
# typed stages without changing the platform job lifecycle.
PIPELINE = PipelineDefinition(
    id="lab1",
    total_timeout_seconds=90,
    stages=(
        LegacyGraderStage(
            id="deterministic-tests",
            title="Автоматические тесты",
            runtime="python-cpu",
            assignment="lab1",
            retry_on_infra_error=1,
        ),
    ),
)
