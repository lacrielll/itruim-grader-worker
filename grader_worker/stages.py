from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, Sequence

from .runtime_profiles import RuntimeLimits, RuntimeProfile, RuntimeRegistry
from .datasets import DatasetMount


class StageStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    INFRA_ERROR = "infra_error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StageResult:
    stage_id: str
    status: StageStatus
    summary: str
    evidence: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()
    metrics: dict[str, int | float | str | bool] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    achievement_triggers: tuple[dict[str, Any], ...] = ()


@dataclass
class PipelineContext:
    submission_path: str
    results: list[StageResult] = field(default_factory=list)

    @property
    def has_critical_failure(self) -> bool:
        return any(result.status == StageStatus.FAILED for result in self.results)

    def result(self, stage_id: str) -> StageResult | None:
        return next((item for item in self.results if item.stage_id == stage_id), None)


class StageExecutor(Protocol):
    def execute(self, stage: "Stage", runtime: RuntimeProfile, context: PipelineContext) -> StageResult: ...


@dataclass(frozen=True)
class Stage:
    id: str
    title: str
    runtime: str
    limits: RuntimeLimits | None = None
    stop_on_failure: bool = True
    continue_on_warning: bool = True
    retry_on_infra_error: int = 0
    run_if_no_critical: bool = True
    datasets: tuple[DatasetMount, ...] = ()

    def validate(self, registry: RuntimeRegistry) -> RuntimeProfile:
        if not self.id or not self.id.replace("-", "_").isidentifier():
            raise ValueError(f"invalid stage id: {self.id!r}")
        if not 0 <= self.retry_on_infra_error <= 3:
            raise ValueError("retry_on_infra_error must be between 0 and 3")
        aliases = [dataset.alias for dataset in self.datasets]
        if len(aliases) != len(set(aliases)):
            raise ValueError(f"stage {self.id} has duplicate dataset mount aliases")
        profile = registry.require(self.runtime)
        if self.limits is not None and not self.limits.no_weaker_than(profile.limits):
            raise ValueError(f"stage {self.id} attempts to exceed runtime ceiling {profile.name}")
        return profile


@dataclass(frozen=True)
class CommandStage(Stage):
    command: tuple[str, ...] = ()
    success_codes: frozenset[int] = frozenset({0})

    def validate(self, registry: RuntimeRegistry) -> RuntimeProfile:
        profile = super().validate(registry)
        if not self.command:
            raise ValueError(f"stage {self.id} command is empty")
        executable = self.command[0].rsplit("/", 1)[-1]
        if executable not in profile.allowed_commands:
            raise ValueError(f"command {executable!r} is not allowed by runtime {profile.name}")
        return profile


@dataclass(frozen=True)
class LegacyGraderStage(Stage):
    assignment: str = ""


@dataclass(frozen=True)
class PipelineDefinition:
    id: str
    stages: tuple[Stage, ...]
    total_timeout_seconds: int = 300

    def validate(self, registry: RuntimeRegistry) -> None:
        if not self.stages:
            raise ValueError("pipeline must contain at least one stage")
        ids = [stage.id for stage in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("stage ids must be unique")
        if not 1 <= self.total_timeout_seconds <= 7200:
            raise ValueError("total pipeline timeout must be between 1 and 7200 seconds")
        for stage in self.stages:
            stage.validate(registry)


class LinearPipelineRunner:
    def __init__(self, registry: RuntimeRegistry, executor: StageExecutor):
        self.registry = registry
        self.executor = executor

    def run(self, definition: PipelineDefinition, submission_path: str) -> PipelineContext:
        definition.validate(self.registry)
        context = PipelineContext(submission_path=submission_path)
        halted = False
        for stage in definition.stages:
            if halted or (stage.run_if_no_critical and context.has_critical_failure):
                context.results.append(StageResult(stage.id, StageStatus.SKIPPED, "Этап пропущен из-за предыдущей критической ошибки"))
                continue
            runtime = stage.validate(self.registry)
            attempts = stage.retry_on_infra_error + 1
            result: StageResult | None = None
            for _ in range(attempts):
                result = self.executor.execute(stage, runtime, context)
                if result.status != StageStatus.INFRA_ERROR:
                    break
            assert result is not None
            if result.stage_id != stage.id:
                raise ValueError("stage executor returned a result for another stage")
            context.results.append(result)
            if result.status == StageStatus.FAILED and stage.stop_on_failure:
                halted = True
            if result.status == StageStatus.WARNING and not stage.continue_on_warning:
                halted = True
            if result.status == StageStatus.INFRA_ERROR:
                halted = True
        return context


def aggregate_stage_results(results: Sequence[StageResult]) -> dict[str, Any]:
    deterministic_failed = any(item.status == StageStatus.FAILED for item in results)
    infra_failed = any(item.status == StageStatus.INFRA_ERROR for item in results)
    return {
        "schema_version": 2,
        "outcome": "infrastructure_failed" if infra_failed else ("checks_failed" if deterministic_failed else "passed"),
        "deterministic_gate": "failed" if deterministic_failed or infra_failed else "passed",
        "llm_eligible": not deterministic_failed and not infra_failed,
        "stages": [
            {
                "id": item.stage_id,
                "status": item.status,
                "summary": item.summary,
                "evidence": list(item.evidence),
                "diagnostics": list(item.diagnostics),
                "metrics": item.metrics,
                "artifacts": list(item.artifacts),
            }
            for item in results
        ],
        "evidence": [evidence for item in results for evidence in item.evidence],
        "achievement_triggers": [trigger for item in results for trigger in item.achievement_triggers],
    }
