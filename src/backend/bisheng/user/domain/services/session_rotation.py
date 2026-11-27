"""Transport-neutral refresh recovery rule shared with legacy DSH sessions."""

from datetime import timedelta


def recovery_window_open(*, now, used_at, grace_seconds):
    return grace_seconds > 0 and used_at is not None and now - used_at <= timedelta(seconds=grace_seconds)


def unspent_successor(*, now, used_at, grace_seconds, successor_state):
    return recovery_window_open(now=now, used_at=used_at, grace_seconds=grace_seconds) and successor_state == "ACTIVE"


def rotation_decision(*, session_state, session_expired, token_state, token_expired, generation, recoverable):
    """Pure transition decision; adapters own locks, persistence and token formats."""
    if session_state != "ACTIVE":
        return "session_revoked"
    if session_expired:
        return "session_expired"
    if token_state == "USED":
        return "recover" if recoverable else "revoke"
    if token_expired:
        return "session_expired"
    if token_state != "ACTIVE" or generation >= 9223372036854775807:
        return "invalid_refresh_token"
    return "rotate"
