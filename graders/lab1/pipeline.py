from __future__ import annotations

from grader_worker.pipeline import on


class Lab1Pipeline:
    @on("submission.finalized", title="Все функции прошли проверку", emits=["assignment/lab-1/all-functions"])
    def all_functions(self, event, state, achievements):
        checks = state.get("checks", [])
        if checks and all(item.get("status") == "passed" for item in checks):
            achievements.nominate(
                "assignment/lab-1/all-functions",
                evidence_ids=[f"check:{item['id']}" for item in checks],
                reason_code="all_required_functions_passed",
            )
