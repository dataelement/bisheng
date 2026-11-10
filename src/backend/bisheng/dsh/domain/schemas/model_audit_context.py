"""Negotiated, untrusted metadata; never part of model inputs."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from bisheng.dsh.domain.schemas.model_audit_sources import normalize_message_sources

AUDIT_FIELDS = ("conversation_id", "request_kind", "session_origin", "parent_conversation_id", "message_sources")
REQUEST_KINDS = frozenset({"chat", "compaction", "session-title"})
MAX_CONTEXT_BYTES = 4096


@dataclass(frozen=True, slots=True)
class AuditContext:
    conversation_id: str | None = None
    request_kind: str | None = None
    invalid: bool = False
    session_origin: str | None = None
    parent_conversation_id: str | None = None
    message_sources: dict | None = field(default=None, repr=False)
    message_sources_status: str = "NOT_PROVIDED"


def valid_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        return False
    try:
        value.encode("utf8")
        return True
    except UnicodeError:
        return False


def parse_audit_context(raw, advertised_fields: Iterable[str] = AUDIT_FIELDS, *, message_count=None) -> AuditContext:
    if raw is None:
        return AuditContext()
    if not isinstance(raw, dict):
        return AuditContext(invalid=True)
    fields = set(advertised_fields) & set(AUDIT_FIELDS)
    clean, invalid = {}, False
    for key in ("conversation_id", "request_kind", "session_origin", "parent_conversation_id"):
        if key not in fields or key not in raw:
            continue
        value = raw[key]
        valid = (
            valid_id(value)
            if key.endswith("id")
            else isinstance(value, str) and value in (REQUEST_KINDS if key == "request_kind" else {"main", "subagent"})
        )
        if valid:
            clean[key] = value
        else:
            invalid = True
    if "parent_conversation_id" in clean and (
        not clean.get("conversation_id")
        or clean.get("session_origin") != "subagent"
        or clean["parent_conversation_id"] == clean["conversation_id"]
    ):
        clean.pop("parent_conversation_id")
        invalid = True
    sources, status = None, "NOT_PROVIDED"
    if "message_sources" in fields and "message_sources" in raw:
        sources, status = normalize_message_sources(raw["message_sources"], message_count)
        invalid |= status in {"INVALID", "PARTIAL"}
    return AuditContext(**clean, invalid=invalid, message_sources=sources, message_sources_status=status)
