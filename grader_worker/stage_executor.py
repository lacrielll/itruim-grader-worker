from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from .runtime_profiles import RuntimeProfile
from .stages import CommandStage, PipelineContext, Stage, StageResult, StageStatus
from .datasets import DatasetError, DatasetRegistry


class DockerStageExecutor:
    """Execute one untrusted command in one fresh gVisor container.

    This first universal executor deliberately supports no writable cross-stage
    workspace. A compiler and its tests may be one stage until typed artifact
    transport is introduced; silently sharing an untrusted directory would make
    later trusted stages unsafe.
    """

    def __init__(self, *, output_bytes: int = 256_000, datasets: DatasetRegistry | None = None):
        self.output_bytes = output_bytes
        self.datasets = datasets

    def execute(self, stage: Stage, runtime: RuntimeProfile, context: PipelineContext) -> StageResult:
        if not isinstance(stage, CommandStage):
            return StageResult(stage.id, StageStatus.INFRA_ERROR, "Исполнитель не поддерживает тип этапа")
        limits = stage.limits or runtime.limits
        container_name = f"itruim-stage-{uuid.uuid4().hex}"
        submission = Path(context.submission_path).resolve()
        command = [
            "docker", "run", "--rm", "--runtime", runtime.executor, "--name", container_name,
            "--init", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", f"{limits.memory_mb}m",
            "--memory-swap", f"{limits.memory_mb}m", "--cpus", str(limits.cpu),
            "--tmpfs", f"/tmp:rw,noexec,nosuid,size={limits.writable_mb}m",
            "--tmpfs", f"/workspace:rw,nosuid,size={limits.writable_mb}m",
            "-v", f"{submission}:/submission:ro", "--workdir", "/submission",
        ]
        try:
            for dataset in stage.datasets:
                if self.datasets is None:
                    raise DatasetError("dataset registry is not configured on this worker")
                descriptor, source = self.datasets.resolve(dataset)
                command.extend([
                    "--mount",
                    f"type=bind,src={source},dst=/datasets/{dataset.alias},readonly,bind-propagation=rprivate",
                    "--label", f"itruim.dataset.{dataset.alias}={descriptor.digest}",
                ])
        except DatasetError as error:
            return StageResult(
                stage.id, StageStatus.INFRA_ERROR, "Датасет этапа недоступен",
                diagnostics=({"code": "DATASET_UNAVAILABLE", "message": str(error)},),
            )
        command.extend(["--entrypoint", stage.command[0]])
        if runtime.executor != "runsc-ptrace":
            command.extend(["--pids-limit", str(limits.pids)])
        command.append(runtime.image)
        command.extend(stage.command[1:])
        try:
            completed = subprocess.run(command, capture_output=True, timeout=limits.timeout_seconds + 10)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "--force", container_name], capture_output=True, timeout=15)
            return StageResult(
                stage.id, StageStatus.FAILED, "Превышен лимит времени этапа",
                diagnostics=({"code": "STAGE_TIME_LIMIT", "message": f"Лимит: {limits.timeout_seconds} с"},),
                metrics={"timeout_seconds": limits.timeout_seconds},
            )
        except (OSError, subprocess.SubprocessError) as error:
            return StageResult(
                stage.id, StageStatus.INFRA_ERROR, "Контейнерный runtime недоступен",
                diagnostics=({"code": "STAGE_RUNTIME_UNAVAILABLE", "error_type": type(error).__name__},),
            )
        stdout = completed.stdout[-self.output_bytes:].decode(errors="replace")
        stderr = completed.stderr[-self.output_bytes:].decode(errors="replace")
        if completed.returncode in stage.success_codes:
            return StageResult(
                stage.id, StageStatus.PASSED, "Этап успешно завершён",
                evidence=({"type": "command_result", "exit_code": completed.returncode},),
                metrics={"exit_code": completed.returncode, "stdout_bytes": len(completed.stdout), "stderr_bytes": len(completed.stderr)},
            )
        return StageResult(
            stage.id, StageStatus.FAILED, "Команда завершилась с ошибкой",
            diagnostics=({
                "code": "COMMAND_FAILED", "exit_code": completed.returncode,
                "stdout": stdout, "stderr": stderr,
            },),
            metrics={"exit_code": completed.returncode, "stdout_bytes": len(completed.stdout), "stderr_bytes": len(completed.stderr)},
        )
