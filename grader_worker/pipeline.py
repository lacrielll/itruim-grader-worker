from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable


ACHIEVEMENT_ID = re.compile(r"^(common|course/[a-z0-9][a-z0-9-]*|run/[a-z0-9][a-z0-9-]*|assignment/[a-z0-9][a-z0-9-]*|custom/[a-z0-9][a-z0-9-]*)/[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class PipelineEvent:
    id: str
    type: str
    payload: dict[str, Any]
    evidence_ids: tuple[str, ...] = ()
    causation_id: str | None = None


@dataclass(frozen=True)
class AchievementNomination:
    achievement_id: str
    evidence_ids: tuple[str, ...]
    reason_code: str
    source: str

    def __post_init__(self) -> None:
        if not ACHIEVEMENT_ID.fullmatch(self.achievement_id):
            raise ValueError(f"invalid achievement namespace: {self.achievement_id}")
        if not self.evidence_ids:
            raise ValueError("achievement nomination requires evidence")


@dataclass
class PipelineActions:
    evidence: list[dict[str, Any]] = field(default_factory=list)
    nominations: list[AchievementNomination] = field(default_factory=list)
    progress: list[dict[str, Any]] = field(default_factory=list)

    def merge(self, other: "PipelineActions") -> None:
        self.evidence.extend(other.evidence)
        self.nominations.extend(other.nominations)
        self.progress.extend(other.progress)

    def api_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence,
            "achievement_triggers": [asdict(item) for item in self.nominations],
            "achievement_progress": self.progress,
        }


class AchievementAPI:
    def __init__(self, *, source: str, allowed: set[str], existing_evidence: set[str]):
        self.source = source
        self.allowed = allowed
        self.existing_evidence = existing_evidence
        self.actions = PipelineActions()

    def nominate(self, achievement_id: str, *, evidence_ids: Iterable[str], reason_code: str) -> None:
        evidence = tuple(dict.fromkeys(evidence_ids))
        if achievement_id not in self.allowed:
            raise ValueError(f"achievement is not allowlisted: {achievement_id}")
        unknown = set(evidence) - self.existing_evidence
        if unknown:
            raise ValueError(f"unknown achievement evidence: {sorted(unknown)}")
        self.actions.nominations.append(AchievementNomination(achievement_id, evidence, reason_code, self.source))

    def progress(self, achievement_id: str, *, key: str, evidence_ids: Iterable[str]) -> None:
        if achievement_id not in self.allowed:
            raise ValueError(f"achievement is not allowlisted: {achievement_id}")
        evidence = tuple(dict.fromkeys(evidence_ids))
        unknown = set(evidence) - self.existing_evidence
        if unknown:
            raise ValueError(f"unknown achievement evidence: {sorted(unknown)}")
        self.actions.progress.append({"achievement_id": achievement_id, "key": key, "evidence_ids": list(evidence), "source": self.source})


def on(event_type: str, *, title: str = "", emits: Iterable[str] = ()):
    def decorate(function: Callable[..., PipelineActions | None]):
        setattr(function, "__pipeline_handler__", {"event_type": event_type, "title": title, "emits": tuple(emits)})
        return function
    return decorate


class EventPipeline:
    max_handlers = 100
    max_actions_per_event = 100

    def __init__(self, handler_object: Any, *, allowed_achievements: Iterable[str]):
        self.allowed = set(allowed_achievements)
        invalid = sorted(item for item in self.allowed if not ACHIEVEMENT_ID.fullmatch(item))
        if invalid:
            raise ValueError(f"invalid achievement namespaces: {invalid}")
        handlers = []
        for name in dir(handler_object):
            method = getattr(handler_object, name)
            metadata = getattr(method, "__pipeline_handler__", None)
            if metadata:
                if not set(metadata["emits"]).issubset(self.allowed):
                    raise ValueError(f"handler {name} emits a non-allowlisted achievement")
                handlers.append((method, metadata))
        if len(handlers) > self.max_handlers:
            raise ValueError("pipeline has too many handlers")
        self.handlers = handlers

    def dispatch(self, event: PipelineEvent, state: dict[str, Any]) -> PipelineActions:
        aggregate = PipelineActions()
        evidence_ids = set(state.get("evidence_ids", ())) | set(event.evidence_ids)
        for method, metadata in self.handlers:
            if metadata["event_type"] != event.type:
                continue
            api = AchievementAPI(source=f"pipeline:{method.__name__}", allowed=self.allowed, existing_evidence=evidence_ids)
            returned = method(event, state, api)
            aggregate.merge(api.actions)
            if returned is not None:
                if not isinstance(returned, PipelineActions):
                    raise TypeError("pipeline handler must return PipelineActions or None")
                aggregate.merge(returned)
        action_count = len(aggregate.evidence) + len(aggregate.nominations) + len(aggregate.progress)
        if action_count > self.max_actions_per_event:
            raise ValueError("pipeline emitted too many actions")
        unique: dict[tuple[str, tuple[str, ...], str], AchievementNomination] = {}
        for item in aggregate.nominations:
            unique[(item.achievement_id, item.evidence_ids, item.reason_code)] = item
        aggregate.nominations = list(unique.values())
        return aggregate
