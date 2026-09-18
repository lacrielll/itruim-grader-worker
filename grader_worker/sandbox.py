from __future__ import annotations

import json
import os
import shutil
import uuid
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SandboxInfrastructureFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxPolicy:
    image: str = "itruim-grader-cpu:cpu-v1"
    cpu_threads: int = 1
    ram_mb: int = 512
    wall_time_sec: int = 60
    pids: int = 64
    output_bytes: int = 1_000_000
    runtime: str = "runsc-ptrace"


def docker_ready(image: str, runtime: str = "runsc-ptrace") -> dict[str, str]:
    version = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=10)
    if version.returncode:
        raise SandboxInfrastructureFailure("Docker daemon недоступен")
    inspect = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], capture_output=True, text=True, timeout=10)
    if inspect.returncode:
        raise SandboxInfrastructureFailure(f"Sandbox image отсутствует: {image}")
    runtimes = subprocess.run(["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True, timeout=10)
    if runtimes.returncode or f'"{runtime}"' not in runtimes.stdout:
        raise SandboxInfrastructureFailure(f"Обязательный sandbox runtime {runtime} не зарегистрирован в Docker")
    probe_command = [
        "docker", "run", "--rm", "--runtime", runtime, "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--memory", "128m", "--cpus", "0.25",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--entrypoint", "python", image, "-c", "print('ready')",
    ]
    if runtime != "runsc-ptrace":
        probe_command[probe_command.index("--memory"):probe_command.index("--memory")] = ["--pids-limit", "16"]
    probe = subprocess.run(probe_command, capture_output=True, text=True, timeout=20)
    if probe.returncode or probe.stdout.strip() != "ready":
        raise SandboxInfrastructureFailure(f"Sandbox self-test failed: {probe.stderr[-500:]}")
    return {"runtime": f"docker-{version.stdout.strip()}-{runtime}", "cpu_image": inspect.stdout.strip() or image,
            "pid_limit": "rlimit-nproc" if runtime == "runsc-ptrace" else "docker-cgroup"}


def run_sandbox(snapshot: Path, grader_root: Path, contract_root: Path, assignment: str, policy: SandboxPolicy) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="itruim-job-") as temp, tempfile.TemporaryDirectory(prefix="itruim-runtime-") as runtime_temp, tempfile.TemporaryDirectory(prefix="itruim-private-") as private_temp:
        output_dir = Path(temp)
        # gVisor's user mapping needs write permission on this short-lived bind.
        # A bounded result channel will replace it in the hardened executor.
        os.chmod(output_dir, 0o733)
        runtime_dir = Path(runtime_temp)
        private_dir = Path(private_temp)
        runtime_dir.chmod(0o755)
        shutil.copy2(grader_root / "sandbox_entry.py", runtime_dir / "sandbox_entry.py")
        shutil.copy2(grader_root / "student_executor.py", runtime_dir / "student_executor.py")
        (runtime_dir / "grader_worker").mkdir()
        shutil.copy2(grader_root / "grader_worker" / "__init__.py", runtime_dir / "grader_worker" / "__init__.py")
        shutil.copy2(grader_root / "grader_worker" / "models.py", runtime_dir / "grader_worker" / "models.py")
        shutil.copy2(grader_root / "grader_worker" / "policy.py", runtime_dir / "grader_worker" / "policy.py")
        shutil.copy2(grader_root / "grader_worker" / "grading_dsl.py", runtime_dir / "grader_worker" / "grading_dsl.py")
        shutil.copy2(grader_root / "grader_worker" / "pipeline.py", runtime_dir / "grader_worker" / "pipeline.py")
        shutil.copytree(grader_root / "graders", private_dir / "graders")
        for directory in [private_dir, *[path for path in private_dir.rglob("*") if path.is_dir()]]:
            directory.chmod(0o700)
        for path in [path for path in private_dir.rglob("*") if path.is_file()]:
            path.chmod(0o600)
        container_name = f"itruim-grader-{uuid.uuid4().hex}"
        command = [
            "docker", "run", "--rm", "--runtime", policy.runtime, "--name", container_name, "--init", "--network", "none", "--read-only", "--cap-drop", "ALL",
            # gVisor's user mapping requires DAC_OVERRIDE for the trusted root
            # harness to read the private bind mount. Linux clears effective
            # capabilities when that harness demotes the student to uid 10001.
            "--cap-add", "DAC_OVERRIDE", "--cap-add", "SETUID", "--cap-add", "SETGID",
            "--security-opt", "no-new-privileges", "--pids-limit", str(policy.pids), "--memory", f"{policy.ram_mb}m",
            "--memory-swap", f"{policy.ram_mb}m", "--cpus", str(policy.cpu_threads),
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--tmpfs", "/home/grader:rw,noexec,nosuid,size=16m",
            "-v", f"{snapshot.resolve()}:/submission:ro", "-v", f"{runtime_dir.resolve()}:/grader:ro", "-v", f"{private_dir.resolve()}:/private:ro",
            "-v", f"{contract_root.resolve()}:/canonical:ro", "-v", f"{output_dir.resolve()}:/output:rw",
            policy.image, "--assignment", assignment, "--output", "/output/result.json",
        ]
        if policy.runtime == "runsc-ptrace":
            index = command.index("--pids-limit")
            del command[index:index + 2]
        try:
            process = subprocess.run(command, capture_output=True, timeout=policy.wall_time_sec + 10)
        except subprocess.TimeoutExpired as error:
            raise SandboxInfrastructureFailure("Container runtime не завершил sandbox после deadline") from error
        finally:
            subprocess.run(["docker", "rm", "--force", container_name], capture_output=True, timeout=15)
        result_path = output_dir / "result.json"
        if result_path.exists():
            return json.loads(result_path.read_text(encoding="utf-8"))
        stderr = process.stderr[-policy.output_bytes:].decode(errors="replace")
        if process.returncode in (137, 143):
            return {"schema_version": 1, "outcome": "resource_limit_exceeded", "score": {"earned": 0, "maximum": 100}, "checks": [], "metrics": {}, "resource_events": [{"kind": "memory_or_termination"}], "achievement_triggers": [], "deterministic_gate": "failed", "llm_eligible": False, "public_summary": "Выполнение превысило лимит памяти или было остановлено", "public_diagnostics": [{"code": "MEMORY_LIMIT_EXCEEDED", "title": "Превышен лимит ресурсов", "message": f"Процесс остановлен sandbox. Лимит RAM: {policy.ram_mb} МБ.", "stage": "resource"}], "private_diagnostics": [{"stderr": stderr}], "evidence": {}}
        raise SandboxInfrastructureFailure(f"Sandbox did not produce result (exit {process.returncode}): {stderr[-1000:]}")
