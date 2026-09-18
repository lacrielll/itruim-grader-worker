from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
import traceback
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints
import types

import numpy as np


def resolve(dotted: str) -> Any:
    module, _, name = dotted.rpartition(".")
    return getattr(importlib.import_module(module), name)


def return_annotation_matches(annotation: Any, expected: tuple[type, ...]) -> bool:
    if annotation is inspect.Parameter.empty:
        return False
    origin = get_origin(annotation)
    if origin in (types.UnionType, getattr(__import__("typing"), "Union")):
        return set(get_args(annotation)) == set(expected)
    if len(expected) != 1:
        return False
    wanted = expected[0]
    if wanted is list:
        return annotation is list or get_origin(annotation) is list
    if not isinstance(annotation, type):
        return False
    try:
        return issubclass(annotation, wanted)
    except TypeError:
        return annotation is wanted


def decode(value: Any) -> Any:
    if isinstance(value, dict) and "__ndarray__" in value:
        return np.asarray(value["__ndarray__"], dtype=value.get("dtype"))
    if isinstance(value, dict):
        return {key: decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode(item) for item in value]
    return value


def encode(value: Any) -> Any:
    if is_dataclass(value):
        return {"__dataclass__": f"{type(value).__module__}.{type(value).__name__}", "fields": encode(asdict(value))}
    if isinstance(value, np.ndarray):
        return {"__ndarray__": value.tolist(), "dtype": str(value.dtype), "shape": list(value.shape)}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"Unsupported result type: {type(value).__module__}.{type(value).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    result_path = Path(args.result)
    response: dict[str, Any]
    try:
        sys.path.insert(0, "/submission")
        module = importlib.import_module(request["module"])
        function = getattr(module, request["function"])
        input_type = resolve(request["input_type"])
        signature = inspect.signature(function)
        parameters = list(signature.parameters.values())
        if not parameters:
            raise TypeError("нет обязательного входного параметра")
        hints = get_type_hints(function)
        first = parameters[0]
        if hints.get(first.name) is not input_type:
            actual = hints.get(first.name, first.annotation)
            raise TypeError(f"первый параметр имеет тип {actual!r}, ожидался {request['input_type']}")
        required_extra = [p.name for p in parameters[1:] if p.default is inspect.Parameter.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
        if required_extra:
            raise TypeError(f"дополнительные параметры без default: {', '.join(required_extra)}")
        expected_returns = tuple(resolve(item) for item in request["return_types"])
        if not return_annotation_matches(hints.get("return", signature.return_annotation), expected_returns):
            raise TypeError(f"неверная аннотация возвращаемого типа; ожидалось {' | '.join(request['return_types'])}")
        try:
            input_value = input_type(**decode(request["fields"]))
            response = {"ok": True, "value": encode(function(input_value))}
        except BaseException as error:
            response = {"ok": False, "phase": "runtime", "error_type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()[-8000:]}
    except BaseException as error:
        response = {"ok": False, "phase": "signature", "error_type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()[-8000:]}
    result_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
