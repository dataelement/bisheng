"""The publish-failure five-tuple — AC-11's only shape.

``{stage, code, message, details, hints}``. ``code`` + ``stage`` + ``details``
are the machine-readable half (the CLI branches on them, a local agent fixes
the manifest from them); ``message`` + ``hints`` are the human half. It is one
structure rather than two because F053 AC-35 and F055 AC-11 are two views of
the same data, and the same dict lands in three places: the CLI poll response,
the publish face's approval-status block, and ``app_deployment.failure``.

Building it from the raised ``AppPublishError`` — instead of at each raise
site — is what keeps ``stage`` consistent: a service raises the error it knows
about (16223 "tier retired"), and the *pipeline* knows which stage it was in.
A service that does know its stage passes ``stage=`` as an error kwarg and it
wins.
"""

from __future__ import annotations

from typing import Any

from bisheng.common.errcode.base import BaseErrorCode


def failure_from_error(exc: BaseErrorCode, *, stage: str) -> dict[str, Any]:
    """Turn a raised publish error into the five-tuple.

    ``details`` is always a dict and ``hints`` always a list of strings, so a
    consumer never has to type-check before rendering. ``details`` is a dict
    (rather than the list of field errors it usually contains) because tier and
    runtime failures carry a flat ``{field, value, reason}`` while schema
    failures carry ``{errors: [...]}`` — one container, two payloads, no
    ``isinstance`` at the reading end.
    """
    kwargs = getattr(exc, "kwargs", None) or {}
    details = kwargs.get("details")
    hints = kwargs.get("hints")
    return {
        "stage": kwargs.get("stage") or stage,
        "code": int(getattr(exc, "code", 0) or 0),
        "message": str(getattr(exc, "message", "") or ""),
        "details": details if isinstance(details, dict) else ({"value": details} if details is not None else {}),
        "hints": [str(hint) for hint in hints] if isinstance(hints, (list, tuple)) else ([] if not hints else [str(hints)]),
    }
