from __future__ import annotations

import time
import threading
from pathlib import Path

from .api import ApiFailure, GraderApi
from .models import Diagnostic, GradeResult
from .repository import RepositoryFailure, checkout_exact, is_transient_repository_failure, temporary_snapshot, validate_snapshot
from .local_uploads import copy_local_upload
from .sandbox import SandboxInfrastructureFailure, SandboxPolicy, docker_ready, run_sandbox
from .llm_review import run_followup_review, run_initial_review
from .llm_assessment import run_assessment
from .llm_config import configured_providers
from .llm_providers import ProviderFailure
from .llm_quota import CapacityUnavailable
from .achievements import resolve_achievement_triggers


ROOT = Path(__file__).resolve().parents[1]
INSTALLED_GRADERS = {
    path.name for path in (ROOT / "graders").iterdir()
    if path.is_dir() and not path.name.startswith("_") and (path / "grader.py").is_file() and (path / "contracts").is_dir()
}


class Worker:
    def __init__(self, api: GraderApi, image: str = "itruim-grader-cpu:cpu-v1", runtime: str = "runsc-ptrace", poll_seconds: float = 3.0):
        self.api = api
        self.image = image
        self.runtime = runtime
        self.poll_seconds = poll_seconds

    def run(self, once: bool = False) -> None:
        environment = docker_ready(self.image, self.runtime)
        environment["llm_capacity_available"] = bool(configured_providers())
        self.api.readiness(True, environment)
        while True:
            candidates = self.api.candidates()
            if not candidates:
                reviews = self.api.llm_review_candidates()
                if reviews:
                    try:
                        review = self.api.claim_llm_review(str(reviews[0]["id"]), lease_seconds=300)
                    except ApiFailure:
                        if once:
                            return
                        continue
                    self.process_llm_review(review)
                    if once:
                        return
                    continue
                if once:
                    return
                time.sleep(self.poll_seconds)
                continue
            candidate = next((item for item in candidates if item.get("grader_path") in INSTALLED_GRADERS), None)
            if candidate is None:
                if once:
                    return
                time.sleep(self.poll_seconds)
                continue
            try:
                job = self.api.claim(int(candidate["job_id"]))
            except ApiFailure:
                if once:
                    return
                continue
            self.process(job)
            if once:
                return

    def process_llm_review(self, review: dict) -> None:
        temporary, snapshot = temporary_snapshot()
        try:
            if review["repo_url"].startswith("local-upload://"):
                copy_local_upload(review["repo_url"].removeprefix("local-upload://"), review["commit_sha"], snapshot)
            else:
                checkout_exact(review["repo_url"], review["commit_sha"], snapshot)
            validate_snapshot(snapshot)
            payload = run_followup_review(snapshot, review)
            if payload["result"].get("next_action") == "finalize":
                payload["assessment"] = run_assessment(review["rubric_definition"], review["deterministic_result"], payload["result"], review["submission_id"])
            self.api.llm_review_result(review["review_session_id"], review["lease_token"], payload)
        except (ProviderFailure, CapacityUnavailable):
            environment = docker_ready(self.image, self.runtime)
            environment["llm_capacity_available"] = False
            self.api.readiness(False, environment)
        except RepositoryFailure:
            # The original deterministic pass already pinned this commit. A later
            # fetch failure is transient; leave the review lease to expire safely.
            return
        finally:
            temporary.cleanup()

    def process(self, job: dict) -> None:
        job_id = int(job["job_id"])
        lease = job["lease_token"]
        temporary, snapshot = temporary_snapshot()
        stop_heartbeat = threading.Event()
        lease_lost = threading.Event()

        def keep_lease() -> None:
            while not stop_heartbeat.wait(30):
                try:
                    self.api.heartbeat(job_id, lease)
                except ApiFailure:
                    lease_lost.set()
                    return

        heartbeat = threading.Thread(target=keep_lease, name=f"grader-heartbeat-{job_id}", daemon=True)
        heartbeat.start()
        try:
            self.api.progress(job_id, lease, "repository", "Репозиторий и commit проверяются")
            if job["repo_url"].startswith("local-upload://"):
                copy_local_upload(job["repo_url"].removeprefix("local-upload://"), job["commit_sha"], snapshot)
            else:
                checkout_exact(job["repo_url"], job["commit_sha"], snapshot)
            snapshot_evidence = validate_snapshot(snapshot)
            self.api.progress(job_id, lease, "contracts", "Проверяется структура контрактов и функций")
            resources = job["resource_policy"]
            policy = SandboxPolicy(image=self.image, cpu_threads=resources["cpu_threads"], ram_mb=resources["ram_mb"], wall_time_sec=resources["wall_time_sec"], pids=resources["pids"], runtime=self.runtime)
            self.api.progress(job_id, lease, "tests", "Выполняются автоматические тесты")
            assignment = job["grader_path"]
            if assignment not in INSTALLED_GRADERS:
                raise SandboxInfrastructureFailure("Private grader отсутствует на worker")
            result = run_sandbox(snapshot, ROOT, ROOT / "graders" / assignment / "contracts", assignment, policy)
            result["achievement_triggers"] = resolve_achievement_triggers(
                result, job.get("achievement_definitions", []), {"attempt_number": job.get("attempt_number")}
            )
            result.setdefault("evidence", {})["repository_snapshot"] = snapshot_evidence
            security_events = []
            for diagnostic in result.get("private_diagnostics", []):
                security_events.extend(diagnostic.get("security_events", []))
            if security_events:
                self.api.security_events(job_id, lease, security_events[:200])
            llm_payload = run_initial_review(snapshot, job, result)
            if llm_payload is None and result.get("deterministic_gate") == "passed":
                reviewer_result = {"schema_version": 1, "review_stage": "final", "evidence": [], "criteria": [], "next_action": "finalize", "student_feedback": {"summary": "Code review отключён настройками", "strengths": [], "improvements": []}}
                llm_payload = {"deterministic_gate": "passed", "result": reviewer_result, "provider": "platform", "model": "reviewer-disabled", "input_hash": "0" * 64, "prompt_version": "reviewer-disabled-v1", "attempts": []}
            if llm_payload is not None:
                if llm_payload["result"].get("next_action") == "finalize":
                    llm_payload["assessment"] = run_assessment(job["rubric_definition"], result, llm_payload["result"], job["submission_id"])
                self.api.llm_initial(job_id, lease, llm_payload)
            if lease_lost.is_set():
                return
            self.api.progress(job_id, lease, "tests", "Результат проверки сохраняется")
            self.api.result(job_id, lease, result)
        except RepositoryFailure as error:
            if is_transient_repository_failure(error):
                self.api.infra_failure(job_id, lease, "REPOSITORY_NETWORK_UNAVAILABLE")
                return
            result = GradeResult("repository_failed", "failed", str(error), [Diagnostic(error.code, "Не удалось проверить репозиторий", str(error), "repository")])
            self.api.result(job_id, lease, result.api_dict())
        except (ProviderFailure, CapacityUnavailable):
            environment = docker_ready(self.image, self.runtime)
            environment["llm_capacity_available"] = False
            self.api.readiness(False, environment)
            self.api.infra_failure(job_id, lease, "LLM_CAPACITY_UNAVAILABLE")
        except SandboxInfrastructureFailure:
            self.api.infra_failure(job_id, lease, "SANDBOX_RUNTIME_UNAVAILABLE")
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=2)
            temporary.cleanup()
