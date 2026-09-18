from __future__ import annotations

import math
import numpy as np

from grader_contracts.numpy_tasks import BinarizeInput, MatrixVectorBatchInput
from grader_contracts.python_basics import PositiveIntegerInput, TextInput


def count_vowels(data: TextInput) -> int:
    return sum(character.lower() in "aeiou" for character in data.value)


def has_unique_characters(data: TextInput) -> bool:
    return len(set(data.value)) == len(data.value)


def multiplicative_persistence(data: PositiveIntegerInput) -> int:
    value, steps = data.value, 0
    while value >= 10:
        value = math.prod(int(character) for character in str(value))
        steps += 1
    return steps


def prime_factorization(data: PositiveIntegerInput) -> str:
    value, divisor, factors = data.value, 2, []
    while divisor * divisor <= value:
        power = 0
        while value % divisor == 0:
            value //= divisor
            power += 1
        if power:
            factors.append(f"({divisor}{'**' + str(power) if power > 1 else ''})")
        divisor += 1
    if value > 1:
        factors.append(f"({value})")
    return "".join(factors)


def sum_prod(data: MatrixVectorBatchInput) -> np.ndarray:
    return np.matmul(np.asarray(data.matrices), np.asarray(data.vectors)).sum(axis=0)


def binarize(data: BinarizeInput) -> np.ndarray:
    return (np.asarray(data.matrix) > data.threshold).astype(int)
