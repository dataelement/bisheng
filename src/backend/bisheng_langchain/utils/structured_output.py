"""Bounded data parsing for untrusted provider/model output, never Python execution."""

import ast
import json
import math
import re
from typing import Any

MAX_OUTPUT_BYTES = 1_048_576
MAX_OUTPUT_NODES = 10_000
MAX_OUTPUT_DEPTH = 32


class StructuredOutputError(ValueError):
    """Redacted invalid-output error; never includes provider or prompt content."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StructuredOutputError("Structured output contains duplicate properties")
        result[key] = value
    return result


def _reject_constant(value):
    raise StructuredOutputError("Structured output contains a non-finite number")


def _text_size(value):
    if len(value) > MAX_OUTPUT_BYTES:
        raise StructuredOutputError("Structured output exceeds size limit")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise StructuredOutputError("Structured output requires valid UTF-8 text") from None
    if size > MAX_OUTPUT_BYTES:
        raise StructuredOutputError("Structured output exceeds size limit")
    return size


def _validate_data(value):
    pending = [(value, 0)]
    count = 0
    size = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > MAX_OUTPUT_NODES or depth > MAX_OUTPUT_DEPTH:
            raise StructuredOutputError("Structured output exceeds complexity limit")
        if type(item) is dict:  # noqa: E721  # exact type, bool must not pass as int
            if len(item) * 2 + count > MAX_OUTPUT_NODES:
                raise StructuredOutputError("Structured output exceeds complexity limit")
            if any(type(key) is not str for key in item):  # noqa: E721  # exact type, bool must not pass as int
                raise StructuredOutputError("Structured output requires text property names")
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:  # noqa: E721  # exact type, bool must not pass as int
            if len(item) + count > MAX_OUTPUT_NODES:
                raise StructuredOutputError("Structured output exceeds complexity limit")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:  # noqa: E721  # exact type, bool must not pass as int
            size += _text_size(item)
        elif item is None or type(item) is bool:  # noqa: E721  # exact type, bool must not pass as int
            continue
        elif type(item) is int:  # noqa: E721  # exact type, bool must not pass as int
            if item.bit_length() > 4096:
                raise StructuredOutputError("Structured output number exceeds limit")
        elif type(item) is float:  # noqa: E721  # exact type, bool must not pass as int
            if not math.isfinite(item):
                raise StructuredOutputError("Structured output requires finite numbers")
        else:
            raise StructuredOutputError("Structured output contains an unsupported type")
        if size > MAX_OUTPUT_BYTES:
            raise StructuredOutputError("Structured output exceeds size limit")
    return value


def parse_data(value: Any, *, python_literals: bool = False):
    """Read JSON or, explicitly opted-in, legacy list/dict literal reprs.

    Compatibility is data-only: no names, calls, attributes, operators,
    comprehensions, tuple/set/bytes values or duplicate properties are accepted.
    The AST is only parsed/inspected; it is never compiled or executed.
    """
    if not isinstance(value, str):
        return _validate_data(value)
    _text_size(value)
    try:
        parsed = json.loads(value, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except json.JSONDecodeError:
        if not python_literals:
            raise StructuredOutputError("Structured output is not valid JSON") from None
        try:
            tree = ast.parse(value.strip(), mode="eval")
            pending = [(tree, 0)]
            count = 0
            while pending:
                node, depth = pending.pop()
                count += 1
                if count > MAX_OUTPUT_NODES or depth > MAX_OUTPUT_DEPTH:
                    raise ValueError("literal complexity")
                if not isinstance(node, ast.Expression | ast.List | ast.Dict | ast.Constant | ast.Load):
                    raise ValueError("not a data literal")
                if isinstance(node, ast.Dict):
                    if any(not isinstance(key, ast.Constant) or type(key.value) is not str for key in node.keys):  # noqa: E721  # exact type, bool must not pass as int
                        raise ValueError("invalid property names")
                    keys = [key.value for key in node.keys]
                    if len(keys) != len(set(keys)):
                        raise ValueError("duplicate property names")
                pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
            parsed = ast.literal_eval(tree)
        except (SyntaxError, ValueError, TypeError, RecursionError):
            raise StructuredOutputError("Structured output is not a valid data literal") from None
    except (ValueError, RecursionError):
        raise StructuredOutputError("Structured output is not valid bounded JSON") from None
    return _validate_data(parsed)


def parse_score(value: Any) -> float:
    """Parse the QA rubric's decimal score in [0, 10], not an expression."""
    if type(value) is not str or len(value) > 32:  # noqa: E721  # exact type, bool must not pass as int
        raise StructuredOutputError("QA score must be a decimal number between 0 and 10")
    text = value.strip()
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", text):
        raise StructuredOutputError("QA score must be a decimal number between 0 and 10")
    score = float(text)
    if not math.isfinite(score) or not 0 <= score <= 10:
        raise StructuredOutputError("QA score must be a decimal number between 0 and 10")
    return score
