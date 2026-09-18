"""Заготовки задач на базовый Python."""

from grader_contracts.python_basics import PositiveIntegerInput, TextInput


def count_vowels(data: TextInput) -> int:
    text = data.value
    raise NotImplementedError  # TODO


def has_unique_characters(data: TextInput) -> bool:
    text = data.value
    raise NotImplementedError  # TODO


def multiplicative_persistence(data: PositiveIntegerInput) -> int:
    number = data.value
    raise NotImplementedError  # TODO


def prime_factorization(data: PositiveIntegerInput) -> str:
    number = data.value
    raise NotImplementedError  # TODO
