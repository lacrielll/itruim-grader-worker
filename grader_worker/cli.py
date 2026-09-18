from __future__ import annotations

import argparse
import os
import sys
import json
from pathlib import Path

from .api import GraderApi
from .sandbox import docker_ready
from .worker import Worker
from .llm_config import configured_providers
from .local_uploads import serve
from .precheck import precheck
from .selftests import run_selftests
from .sandbox import SandboxPolicy
from .execution_plans import load_execution_plan
from .runtime_profiles import default_runtime_registry
from .datasets import DatasetRegistry


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path): return
    with open(path, encoding="utf-8") as source:
        for raw in source:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key.isidentifier(): os.environ.setdefault(key, value.strip("'\""))


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="grader-worker")
    parser.add_argument("command", choices=["doctor", "run", "serve-uploads", "precheck", "selftest", "plan", "dataset-ingest"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--assignment", default="lab1")
    parser.add_argument("--path")
    parser.add_argument("--dataset-id")
    parser.add_argument("--dataset-version")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.command == "dataset-ingest":
        if not args.path or not args.dataset_id or not args.dataset_version:
            raise SystemExit("--path, --dataset-id and --dataset-version are required")
        dataset_root = Path(os.environ.get("GRADER_DATASET_ROOT", ".worker-state/datasets")).resolve()
        descriptor = DatasetRegistry(dataset_root).ingest(
            args.dataset_id, args.dataset_version, Path(args.path).resolve()
        )
        print(json.dumps(vars(descriptor), ensure_ascii=False, indent=2))
        return
    if args.command == "precheck":
        if not args.path:
            raise SystemExit("--path is required")
        result = precheck(args.assignment, Path(args.path).resolve(), root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    if args.command == "serve-uploads":
        serve(args.host, args.port)
        return
    api_url = os.environ.get("GRADER_API_URL", "http://localhost:5173")
    token = os.environ.get("GRADER_TOKEN", "")
    image = os.environ.get("GRADER_CPU_IMAGE", "itruim-grader-cpu:cpu-v1")
    runtime = os.environ.get("GRADER_OCI_RUNTIME", "runsc-ptrace")
    if args.command == "plan":
        definition = load_execution_plan(args.assignment)
        registry = default_runtime_registry(image, runtime)
        definition.validate(registry)
        print(json.dumps({
            "id": definition.id,
            "total_timeout_seconds": definition.total_timeout_seconds,
            "stages": [
                {
                    "id": stage.id,
                    "title": stage.title,
                    "runtime": stage.runtime,
                    "limits": vars(stage.limits or registry.require(stage.runtime).limits),
                    "stop_on_failure": stage.stop_on_failure,
                    "retry_on_infra_error": stage.retry_on_infra_error,
                    "datasets": [vars(dataset) for dataset in stage.datasets],
                }
                for stage in definition.stages
            ],
        }, ensure_ascii=False, indent=2))
        return
    environment = docker_ready(image, runtime)
    environment["llm_capacity_available"] = bool(configured_providers())
    print(f"Sandbox ready: {environment}")
    if args.command == "doctor":
        if token:
            GraderApi(api_url, token).readiness(True, environment)
            print("Backend credential and readiness accepted")
        return
    if args.command == "selftest":
        result = run_selftests(args.assignment, root, SandboxPolicy(image=image, runtime=runtime))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    if not token:
        raise SystemExit("GRADER_TOKEN is required")
    Worker(GraderApi(api_url, token), image=image, runtime=runtime).run(once=args.once)


if __name__ == "__main__":
    main()
