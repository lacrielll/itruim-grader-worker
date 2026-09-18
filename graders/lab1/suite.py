from __future__ import annotations

from typing import Any

from grader_worker.grading_dsl import case, check


def build_checks(all_cases: dict[str, list[Any]]):
    definitions = []
    for function_name, inputs in all_cases.items():
        def verify(context, input_value, *, _name=function_name):
            return context.verify(_name, input_value)

        verify.__name__ = f"test_{function_name}"
        for index, input_value in reversed(list(enumerate(inputs, start=1))):
            verify = case(id=f"case-{index}", input_value=input_value)(verify)
        verify = check(
            id=f"function:{function_name}",
            title=function_name,
            kind="unit",
            severity="critical",
            points=1,
            section="Python" if function_name in {
                "count_vowels", "has_unique_characters", "multiplicative_persistence", "prime_factorization",
            } else "NumPy",
        )(verify)
        definitions.append(verify.__grader_check__)
    return definitions
