from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ApiFailure(RuntimeError):
    pass


class GraderApi:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, lease: str | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if lease:
            headers["X-Grader-Lease"] = lease
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            payload = error.read().decode(errors="replace")
            raise ApiFailure(f"{method} {path}: HTTP {error.code}: {payload[:1000]}") from error

    def readiness(self, ready: bool, environment: dict[str, Any]) -> Any:
        return self.request("POST", "/api/grader/readiness", {"ready": ready, "capabilities": ["CPU"], "environment": environment})

    def candidates(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/grader/jobs/candidates")["items"]

    def claim(self, job_id: int, lease_seconds: int = 120) -> dict[str, Any]:
        return self.request("POST", f"/api/grader/jobs/{job_id}/claim", {"lease_seconds": lease_seconds})

    def heartbeat(self, job_id: int, lease: str, lease_seconds: int = 120) -> Any:
        return self.request("POST", f"/api/grader/jobs/{job_id}/heartbeat", {"lease_seconds": lease_seconds}, lease)

    def progress(self, job_id: int, lease: str, stage: str, message: str) -> Any:
        return self.request("POST", f"/api/grader/jobs/{job_id}/progress", {"stage": stage, "message": message}, lease)

    def result(self, job_id: int, lease: str, result: dict[str, Any]) -> Any:
        return self.request("POST", f"/api/grader/jobs/{job_id}/result", result, lease)

    def security_events(self, job_id: int, lease: str, events: list[dict[str, Any]]) -> Any:
        return self.request("POST", f"/api/grader/jobs/{job_id}/security-events", {"events": events}, lease)

    def llm_initial(self, job_id: int, lease: str, payload: dict[str, Any]) -> Any:
        return self.request("POST", f"/api/grader/jobs/{job_id}/llm-initial", payload, lease)

    def llm_review_candidates(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/grader/llm-reviews/candidates")["items"]

    def claim_llm_review(self, session_id: str, lease_seconds: int = 120) -> dict[str, Any]:
        return self.request("POST", f"/api/grader/llm-reviews/{session_id}/claim", {"lease_seconds": lease_seconds})

    def llm_review_result(self, session_id: str, lease: str, payload: dict[str, Any]) -> Any:
        return self.request("POST", f"/api/grader/llm-reviews/{session_id}/result", payload, lease)

    def infra_failure(self, job_id: int, lease: str, code: str) -> Any:
        return self.request("POST", f"/api/grader/jobs/{job_id}/infra-failure", {"code": code}, lease)
