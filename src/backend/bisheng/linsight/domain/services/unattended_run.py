"""Runs submitted through the Open API (F073) execute unattended.

Nobody is online to answer a clarification, so such a run gets no ``ask_user``
tool and no "clarify first" step (prompt and tool change together — see
``linsight/AGENTS.md`` prompt ⟺ tool lockstep), and it fails fast when a
selected skill is gone instead of silently running without it. Workbench runs
carry no ``api_meta`` and keep their behaviour.
"""

from __future__ import annotations

OPEN_API_CHANNEL = "open_api_v2"


def _api_meta(session_model) -> dict:
    meta = getattr(session_model, "api_meta", None)
    return meta if isinstance(meta, dict) else {}


def is_unattended_run(session_model) -> bool:
    return _api_meta(session_model).get("channel") == OPEN_API_CHANNEL


def caller_instructions(session_model) -> str | None:
    """Business-context instructions the Open API caller layered on top."""

    if not is_unattended_run(session_model):
        return None
    value = _api_meta(session_model).get("instructions")
    if not isinstance(value, str):
        return None
    return value.strip() or None


__all__ = ["OPEN_API_CHANNEL", "caller_instructions", "is_unattended_run"]
