from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


class RuntimeProfileError(ValueError):
    """Raised when an execution plan requests an unknown or unsafe runtime."""


@dataclass(frozen=True)
class RuntimeLimits:
    cpu: float = 1.0
    memory_mb: int = 256
    timeout_seconds: int = 30
    pids: int = 64
    writable_mb: int = 32

    def __post_init__(self) -> None:
        if not 0 < self.cpu <= 16:
            raise RuntimeProfileError("cpu must be between 0 and 16")
        if not 32 <= self.memory_mb <= 65_536:
            raise RuntimeProfileError("memory_mb must be between 32 and 65536")
        if not 1 <= self.timeout_seconds <= 3_600:
            raise RuntimeProfileError("timeout_seconds must be between 1 and 3600")
        if not 1 <= self.pids <= 4_096:
            raise RuntimeProfileError("pids must be between 1 and 4096")
        if not 1 <= self.writable_mb <= 10_240:
            raise RuntimeProfileError("writable_mb must be between 1 and 10240")

    def no_weaker_than(self, ceiling: "RuntimeLimits") -> bool:
        return (
            self.cpu <= ceiling.cpu
            and self.memory_mb <= ceiling.memory_mb
            and self.timeout_seconds <= ceiling.timeout_seconds
            and self.pids <= ceiling.pids
            and self.writable_mb <= ceiling.writable_mb
        )


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    image: str
    executor: str = "runsc-ptrace"
    entrypoint: tuple[str, ...] = ()
    allowed_commands: frozenset[str] = field(default_factory=frozenset)
    limits: RuntimeLimits = field(default_factory=RuntimeLimits)
    network: str = "none"

    def __post_init__(self) -> None:
        if not self.name or not self.image:
            raise RuntimeProfileError("runtime name and image are required")
        if "@sha256:" not in self.image and ":" not in self.image:
            raise RuntimeProfileError("runtime image must be explicitly tagged or pinned by digest")
        if self.network != "none":
            raise RuntimeProfileError("student runtime profiles cannot enable external network")


class RuntimeRegistry:
    def __init__(self, profiles: Mapping[str, RuntimeProfile] | None = None):
        self._profiles = dict(profiles or {})

    def register(self, profile: RuntimeProfile) -> None:
        if profile.name in self._profiles:
            raise RuntimeProfileError(f"runtime already registered: {profile.name}")
        self._profiles[profile.name] = profile

    def require(self, name: str) -> RuntimeProfile:
        try:
            return self._profiles[name]
        except KeyError as error:
            raise RuntimeProfileError(f"runtime is not registered: {name}") from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))


def default_runtime_registry(cpu_image: str = "itruim-grader-cpu:cpu-v1", executor: str = "runsc-ptrace") -> RuntimeRegistry:
    return RuntimeRegistry({
        "python-cpu": RuntimeProfile(
            name="python-cpu",
            image=cpu_image,
            executor=executor,
            allowed_commands=frozenset({"python", "python3"}),
            limits=RuntimeLimits(cpu=1, memory_mb=512, timeout_seconds=120, pids=64, writable_mb=64),
        ),
    })
