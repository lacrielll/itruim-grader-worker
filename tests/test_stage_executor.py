from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grader_worker.runtime_profiles import RuntimeProfile
from grader_worker.stage_executor import DockerStageExecutor
from grader_worker.stages import CommandStage, PipelineContext, StageStatus
from grader_worker.datasets import DatasetMount, DatasetRegistry
from grader_worker.sandbox import SandboxInfrastructureFailure, docker_ready


class DockerStageExecutorTests(unittest.TestCase):
    def test_builds_hardened_networkless_container_command(self):
        with tempfile.TemporaryDirectory() as temp, patch("grader_worker.stage_executor.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, b"ok", b"")
            stage = CommandStage("compile", "Компиляция", "cpp", command=("g++", "main.cpp"))
            runtime = RuntimeProfile("cpp", "grader-cpp:v1", allowed_commands=frozenset({"g++"}))
            result = DockerStageExecutor().execute(stage, runtime, PipelineContext(temp))
            command = run.call_args.args[0]
            self.assertEqual(result.status, StageStatus.PASSED)
            self.assertIn("none", command)
            self.assertIn("--read-only", command)
            self.assertIn("no-new-privileges", command)
            self.assertIn("ALL", command)
            self.assertIn(f"{Path(temp).resolve()}:/submission:ro", command)
            self.assertEqual(command[command.index("--entrypoint") + 1], "g++")

    def test_nonzero_exit_is_student_failure_not_infrastructure_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch("grader_worker.stage_executor.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 2, b"", b"compile error")
            stage = CommandStage("compile", "Компиляция", "cpp", command=("g++", "main.cpp"))
            runtime = RuntimeProfile("cpp", "grader-cpp:v1", allowed_commands=frozenset({"g++"}))
            result = DockerStageExecutor().execute(stage, runtime, PipelineContext(temp))
            self.assertEqual(result.status, StageStatus.FAILED)
            self.assertEqual(result.diagnostics[0]["code"], "COMMAND_FAILED")


class DockerDatasetIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            docker_ready("itruim-grader-cpu:cpu-v1", "runsc-ptrace")
        except SandboxInfrastructureFailure as error:
            raise unittest.SkipTest(str(error)) from error

    def test_dataset_is_readable_but_not_writable_and_exposes_no_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "rows.txt").write_text("safe-data", encoding="utf-8")
            registry = DatasetRegistry(root / "registry")
            descriptor = registry.ingest("course/test", "1", source)
            stage = CommandStage(
                "dataset", "Dataset isolation", "python-cpu",
                datasets=(DatasetMount("train", "course/test", "1", descriptor.digest),),
                command=(
                    "python", "-c",
                    "from pathlib import Path; p=Path('/datasets/train/rows.txt'); "
                    "assert p.read_text() == 'safe-data'; "
                    "exec(\"try:\\n p.write_text('changed')\\n raise AssertionError('write succeeded')\\nexcept OSError:\\n pass\"); "
                    "assert not Path('/datasets/train/../registry').exists()",
                ),
            )
            runtime = RuntimeProfile(
                "python-cpu", "itruim-grader-cpu:cpu-v1", executor="runsc-ptrace",
                allowed_commands=frozenset({"python"}),
            )
            result = DockerStageExecutor(datasets=registry).execute(stage, runtime, PipelineContext(str(root)))
            self.assertEqual(result.status, StageStatus.PASSED, result)


if __name__ == "__main__":
    unittest.main()
