"""The three events app-proxy is required to emit (design §7「关键日志 / 指标」).

After an incident there is nothing else to read: the proxy keeps no request
store, and the platform's own audit trail records state *actions*, not visitor
traffic. So the events below are the operational surface of this process, and
they are emitted through named functions rather than ad-hoc ``logger.info``
calls for one reason — **a field that a call site forgot is a field nobody
notices is missing until they need it**. Each emitter takes its fields as
required keyword arguments, so an incomplete call fails at the call site
instead of producing a plausible-looking log line with a hole in it.

Three shapes, three audiences:

* :func:`log_request` — one line per forwarded or refused request. INFO. This
  is the line that answers "did the visitor reach the app, and how long did it
  take".
* :func:`log_header_strip` — WARNING, and the **only** production observable of
  AC-32: a client that sends platform identity headers is either a
  misconfigured integration or somebody probing the injection contract. It is a
  warning so it can be alerted on; an unusual rate here is the signal.
* :func:`log_fallback` — WARNING. Which fallback page was rendered, so the
  distribution over kinds can be watched (a rise in ``recovering`` is the
  runtime layer struggling; a rise in ``not_found`` is usually a scanner).

The three names above are **reserved for these emitters**. Diagnostic lines that
happen to be about a request (an upstream retry, a handshake refusal) use their
own names — a line carrying an event name but no ``fields`` would read as a
structured event with a hole in it, which is precisely what this module exists
to prevent.

The fields travel on the :class:`logging.LogRecord` as ``event`` and ``fields``
(a dict), so a JSON handler can serialise them verbatim while the plain-text
message stays readable in ``journalctl``. ``EVENT_FIELDS`` is the declared
contract, and ``tests/test_observability.py`` checks the emitters against it —
add a field there and the emitter must grow it too.
"""

from __future__ import annotations

import logging
from typing import Any

EVENT_REQUEST = "app_proxy.request"
EVENT_HEADER_STRIP = "app_proxy.header_strip"
EVENT_FALLBACK = "app_proxy.fallback"

#: event → the fields every emission of it must carry. Extra fields are allowed
#: (``protocol``, ``generation`` …); a missing one is a defect.
EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    EVENT_REQUEST: (
        "request_id",
        "slug",
        "user_id",
        "decision",
        "reason",
        "cache_hit",
        "upstream_status",
        "latency_ms",
    ),
    EVENT_HEADER_STRIP: ("request_id", "slug", "stripped"),
    EVENT_FALLBACK: ("request_id", "slug", "kind", "reason"),
}


def _render(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def emit(logger: logging.Logger, level: int, event: str, fields: dict[str, Any]) -> None:
    """Write one structured event. Kept public so tests can drive it directly.

    ``stacklevel=3`` so the record points at the caller of the emitter rather
    than at this module — two frames up is where the interesting code is.
    """
    message = " ".join([event, *(f"{name}={_render(value)}" for name, value in fields.items())])
    logger.log(level, message, extra={"event": event, "fields": fields}, stacklevel=3)


def log_request(
    logger: logging.Logger,
    *,
    request_id: str,
    slug: str,
    user_id: str | None,
    decision: str,
    reason: str,
    cache_hit: bool,
    upstream_status: int | None,
    latency_ms: float,
    level: int = logging.INFO,
    **extra: Any,
) -> None:
    """One request, one line (§7).

    ``upstream_status`` is ``None`` for everything the proxy answered itself —
    a refusal, a fallback page — which is exactly how "the app never saw this
    request" is told apart from "the app answered 500".
    """
    emit(
        logger,
        level,
        EVENT_REQUEST,
        {
            "request_id": request_id,
            "slug": slug,
            "user_id": user_id,
            "decision": decision,
            "reason": reason,
            "cache_hit": cache_hit,
            "upstream_status": upstream_status,
            "latency_ms": latency_ms,
            **extra,
        },
    )


def log_header_strip(logger: logging.Logger, *, request_id: str, slug: str, stripped: list[str]) -> None:
    """AC-32's production observable. WARNING on purpose — see the module docstring."""
    emit(
        logger,
        logging.WARNING,
        EVENT_HEADER_STRIP,
        {"request_id": request_id, "slug": slug, "stripped": ",".join(stripped)},
    )


def log_fallback(logger: logging.Logger, *, request_id: str, slug: str, kind: str, reason: str, **extra: Any) -> None:
    """Which fallback page was rendered, and why (§7: 兜底页类型分布)."""
    emit(
        logger,
        logging.WARNING,
        EVENT_FALLBACK,
        {"request_id": request_id, "slug": slug, "kind": kind, "reason": reason, **extra},
    )
