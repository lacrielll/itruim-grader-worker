from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MatrixVectorBatchInput:
    matrices: Any
    vectors: Any


@dataclass(frozen=True)
class BinarizeInput:
    matrix: Any
    threshold: float = 0.5
