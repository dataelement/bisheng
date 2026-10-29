"""Bounded, unambiguous JSON values for external tool contracts."""

import json
import math


def check_tree(value, *, max_depth=32, max_nodes=10000):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > max_depth or nodes > max_nodes:
            raise ValueError("JSON complexity limit")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Non-finite number")


def strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = item
        return result

    def invalid_constant(_value):
        raise ValueError("Non-finite number")

    result = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
    check_tree(result)
    return result
