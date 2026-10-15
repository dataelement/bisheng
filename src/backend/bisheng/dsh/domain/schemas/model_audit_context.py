"""Negotiated, untrusted correlation metadata; never part of model inputs."""

import json
from collections.abc import Iterable
from dataclasses import dataclass

AUDIT_FIELDS = ("conversation_id", "request_kind")
REQUEST_KINDS = frozenset({"chat", "compaction", "session-title"})
MAX_CONTEXT_BYTES = 4096


@dataclass(frozen=True, slots=True)
class AuditContext:
    conversation_id: str | None = None
    request_kind: str | None = None
    invalid: bool = False


def _within_budget(raw: dict) -> bool:
    # Preflight string/container size before iterencode can allocate a giant token.
    pending = [raw]
    nodes = 0
    while pending:
        item = pending.pop()
        nodes += 1
        if nodes > MAX_CONTEXT_BYTES:
            return False
        if isinstance(item, str) and len(item) > MAX_CONTEXT_BYTES:
            return False
        if isinstance(item, dict):
            if len(item) > MAX_CONTEXT_BYTES:
                return False
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            if len(item) > MAX_CONTEXT_BYTES:
                return False
            pending.extend(item)
    size = 0
    for token in json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False).iterencode(raw):
        size += len(token.encode("utf-8"))
        if size > MAX_CONTEXT_BYTES:
            return False
    return True


def parse_audit_context(raw, advertised_fields: Iterable[str] = AUDIT_FIELDS) -> AuditContext:
    if raw is None:
        return AuditContext()
    if not isinstance(raw, dict):
        return AuditContext(invalid=True)
    try:
        if not _within_budget(raw):
            return AuditContext(invalid=True)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        # Invalid optional metadata cannot reject otherwise valid model business data.
        return AuditContext(invalid=True)
    fields = set(advertised_fields) & set(AUDIT_FIELDS)
    conversation_id = raw.get("conversation_id") if "conversation_id" in fields else None
    request_kind = raw.get("request_kind") if "request_kind" in fields else None
    bad_id = (
        "conversation_id" in fields
        and "conversation_id" in raw
        and (not isinstance(conversation_id, str) or not 1 <= len(conversation_id) <= 256)
    )
    bad_kind = (
        "request_kind" in fields
        and "request_kind" in raw
        and (not isinstance(request_kind, str) or request_kind not in REQUEST_KINDS)
    )
    return AuditContext(
        conversation_id=None if bad_id else conversation_id,
        request_kind=None if bad_kind else request_kind,
        invalid=bad_id or bad_kind,
    )
