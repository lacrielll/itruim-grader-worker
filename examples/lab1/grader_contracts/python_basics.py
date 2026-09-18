from dataclasses import dataclass


@dataclass(frozen=True)
class TextInput:
    value: str


@dataclass(frozen=True)
class PositiveIntegerInput:
    value: int
