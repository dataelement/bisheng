from typing import Any


def normalize_retrieval_question(value: Any) -> str:
    """Convert a workflow variable into a retrieval query string.

    Empty values produce an empty query so retrieval nodes can skip the
    embedding call. Non-empty values retain the historical behavior of being
    converted to strings before retrieval.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value if value.strip() else ""
    if isinstance(value, (list, tuple, set, frozenset, dict)) and not value:
        return ""
    return str(value)
