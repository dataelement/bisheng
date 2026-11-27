"""Closed, transport-free credential reference shapes for queued business work."""

import re

WEB_REFERENCE_FIELDS = frozenset({"kind", "user_id", "tenant_id", "token_version", "expires_at"})
PLATFORM_REFERENCE_FIELDS = WEB_REFERENCE_FIELDS | {"session_id", "session_version"}


def valid_browser_reference_shape(reference):
    if not isinstance(reference, dict):
        return False
    if reference.get("kind") == "web_session":
        return set(reference) == WEB_REFERENCE_FIELDS
    return (
        reference.get("kind") == "platform_session"
        and set(reference) == PLATFORM_REFERENCE_FIELDS
        and isinstance(reference.get("session_id"), str)
        and re.fullmatch(r"[a-f0-9]{32}", reference["session_id"]) is not None
        and type(reference.get("session_version")) is int
        and reference["session_version"] >= 1
    )
