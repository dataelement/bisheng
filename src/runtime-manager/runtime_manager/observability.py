"""The four events runtime-manager is required to emit (F054 design §7).

This process is the only thing in the deployment that knows why an app is (or
is not) running, and it keeps no history — the desired-state file holds the
present, not the past. These four events *are* the record:

* :func:`intent_span` → ``rtm.intent``. One line per write intent, with the
  outcome and how long it took. "The button did nothing" is answered here
  before anyone looks at a container.
* :func:`log_reconcile` → ``rtm.reconcile``. What each pass saw and what it
  did. A pass that keeps acting on the same app every 15 s is a crash loop the
  daemon's own backoff is hiding.
* :func:`log_rebuild` → ``rtm.rebuild``. The unhealthy-but-alive fix. Rare by
  design: **a rising frequency means the application itself is unhealthy**, not
  that the platform is flapping, and that distinction is the whole reason this
  event is separate from ``rtm.reconcile``.
* :func:`log_admission_reject` → ``rtm.admission_reject``, **carrying the same
  capacity snapshot the admission response returns**. AC-65 shows an owner why
  their app is 「待上线（资源不足）」 and an operator reconciles capacity from
  the log; both must read the identical numbers, so both read one payload.

Field sets are declared in :data:`EVENT_FIELDS` and filled by emitters whose
arguments are required keyword arguments — a call site that forgets one fails
there rather than shipping a log line with a hole in it. The payload rides on
the :class:`logging.LogRecord` as ``event`` / ``fields`` so a JSON handler can
serialise it while ``journalctl`` still shows a readable line.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)

EVENT_INTENT = "rtm.intent"
EVENT_RECONCILE = "rtm.reconcile"
EVENT_REBUILD = "rtm.rebuild"
EVENT_ADMISSION_REJECT = "rtm.admission_reject"

#: event → the fields every emission must carry. Extra fields are welcome.
EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    EVENT_INTENT: ("kind", "app_id", "result", "latency_ms"),
    EVENT_RECONCILE: ("desired", "actual", "actions"),
    EVENT_REBUILD: ("app_id", "container", "generation", "reason"),
    EVENT_ADMISSION_REJECT: ("purpose", "reason", "required_mb", "required_cpu", "snapshot"),
}

#: ``result`` value of an intent that neither succeeded nor raised a manager
#: error — an unexpected exception on its way to a 500.
RESULT_ERROR = "error"


def _render(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, dict):
        return "{" + " ".join(f"{k}={_render(v)}" for k, v in value.items()) + "}"
    return str(value)


def emit(level: int, event: str, fields: dict[str, Any]) -> None:
    message = " ".join([event, *(f"{name}={_render(value)}" for name, value in fields.items())])
    logger.log(level, message, extra={"event": event, "fields": fields}, stacklevel=3)


@dataclass
class IntentSpan:
    """The mutable half of :func:`intent_span`: the handler sets ``result``."""

    kind: str
    app_id: str | None
    result: str = "ok"


@contextmanager
def intent_span(kind: str, app_id: str | None):
    """Time one write intent and log its outcome, however it ends.

    A failure is *also* an outcome worth a line, so the event is emitted from a
    ``finally``: the exception propagates untouched (FastAPI still turns a
    :class:`~fastapi.HTTPException` into the manager's error envelope) and the
    log records which machine code the caller got. That is the difference
    between "the deploy was refused for capacity" and "the deploy crashed",
    which is otherwise only visible in the caller's own logs.
    """
    span = IntentSpan(kind=kind, app_id=app_id)
    started = time.monotonic()
    try:
        yield span
    except HTTPException as exc:
        detail = exc.detail
        span.result = str(detail.get("code")) if isinstance(detail, dict) else RESULT_ERROR
        raise
    except Exception:
        span.result = RESULT_ERROR
        raise
    finally:
        emit(
            logging.WARNING if span.result != "ok" else logging.INFO,
            EVENT_INTENT,
            {
                "kind": span.kind,
                "app_id": span.app_id,
                "result": span.result,
                "latency_ms": (time.monotonic() - started) * 1000,
            },
        )


def log_reconcile(*, desired: int, actual: int, actions: dict[str, int], **extra: Any) -> None:
    """One line per pass. INFO when the pass acted, DEBUG when it found nothing.

    A silent pass every 15 s would drown the journal and make the interesting
    passes unfindable; dropping it entirely would remove the evidence that the
    loop is alive at all. DEBUG keeps both.
    """
    acted = any(actions.values())
    emit(
        logging.INFO if acted else logging.DEBUG,
        EVENT_RECONCILE,
        {"desired": desired, "actual": actual, "actions": actions, **extra},
    )


def log_rebuild(*, app_id: str, container: str, generation: int, reason: str, **extra: Any) -> None:
    """The unhealthy-but-alive recreate — see the module docstring on frequency."""
    emit(
        logging.WARNING,
        EVENT_REBUILD,
        {"app_id": app_id, "container": container, "generation": generation, "reason": reason, **extra},
    )


def log_admission_reject(
    *,
    purpose: str,
    reason: str,
    required_mb: int,
    required_cpu: float,
    snapshot: dict[str, Any],
    **extra: Any,
) -> None:
    """A capacity refusal, with the numbers it was made from (AC-65 / AC-23)."""
    emit(
        logging.INFO,
        EVENT_ADMISSION_REJECT,
        {
            "purpose": purpose,
            "reason": reason,
            "required_mb": required_mb,
            "required_cpu": required_cpu,
            "snapshot": snapshot,
            **extra,
        },
    )
