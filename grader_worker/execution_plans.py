from __future__ import annotations

import importlib
import re

from .stages import PipelineDefinition


ASSIGNMENT_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def load_execution_plan(assignment: str) -> PipelineDefinition:
    if not ASSIGNMENT_ID.fullmatch(assignment):
        raise ValueError("invalid assignment id")
    module = importlib.import_module(f"graders.{assignment}.execution")
    definition = getattr(module, "PIPELINE", None)
    if not isinstance(definition, PipelineDefinition):
        raise TypeError(f"graders.{assignment}.execution.PIPELINE must be PipelineDefinition")
    return definition
