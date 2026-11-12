"""Actual external index acknowledgements, never a synthetic success flag."""

from collections.abc import Mapping

from bisheng.common.errcode.knowledge import KnowledgeFileFailedError


def require_es_write(response, *, action):
    body = getattr(response, "body", response)
    required = {"total", action, "noops", "version_conflicts", "timed_out", "failures"}
    if (
        not isinstance(body, Mapping)
        or not required.issubset(body)
        or body["timed_out"] is not False
        or body["failures"] != []
        or any(type(body[key]) is not int or body[key] < 0 for key in ("total", action, "noops", "version_conflicts"))
        or body["version_conflicts"]
        or body["total"] != body[action] + body["noops"]
    ):
        raise KnowledgeFileFailedError(exception="knowledge_index_partial_result")
    return body[action]


def require_milvus_write(response, *, attribute, expected=None):
    count = getattr(response, attribute, None)
    if type(count) is not int or count < 0 or (expected is not None and count != expected):
        raise KnowledgeFileFailedError(exception="knowledge_index_partial_result")
    return count
