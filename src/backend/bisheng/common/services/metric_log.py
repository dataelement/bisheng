"""Structured metric logging (F042).

Emit ``BS_METRIC domain=... key=value`` log lines that the external monitoring
layer (ELK / Loki / ES) parses into metrics. This module ONLY formats and emits
lines; ALL aggregation (P95, QPS, success-rate) happens in the log pipeline —
see ``features/v2.6.0/042-metric-log-observability/design.md`` §6.1 for the
contract and §3 for the rationale.

Design constraints (design §5):
- **Zero-blocking, never breaks the business flow.** ``emit_metric`` wraps
  everything in a guarded try/except — a best-effort telemetry swallow that logs
  (never silent) the failure and returns (backend CLAUDE.md error-handling).
- **No SQL text / bind params ever logged** (§2, §5 坑 11): ``sql_op`` returns
  only the leading keyword; the statement body is never retained.
- **Per-process module singletons** for counters (§5 坑 7): ``db_histogram``.
- **No dependency on request/tenant ContextVar** — this runs inside Celery /
  Linsight workers too.

Time is always passed in by the caller (``now``); this module never reads a
clock itself, which keeps the histogram/pool windows deterministic and testable.
"""

import bisect
import threading

from loguru import logger

MARKER = "BS_METRIC"

# domain -> MetricLogConf attribute that gates it (design §6.1)
_DOMAIN_SWITCH = {
    "db_query": "db",
    "db_query_agg": "db",
    "db_pool": "db",
    "obj_storage": "obj_storage",
    "model_invoke": "model_invoke",
    "eplus_notify": "eplus",
}

# Characters that make a bare logfmt value ambiguous; such values are quoted.
_SPECIAL_CHARS = set(' "=\n\t|')


def _get_conf():
    """Return the ``MetricLogConf`` (or None if unavailable at very early boot)."""
    try:
        from bisheng.common.services.config_service import settings

        return getattr(settings, "metric_log", None)
    except Exception:
        return None


def _domain_enabled(conf, domain: str) -> bool:
    if conf is None:
        return True  # fail-open before config is loaded
    if not getattr(conf, "enabled", True):
        return False
    attr = _DOMAIN_SWITCH.get(domain)
    if attr is None:
        return True  # unknown/new domain: allow by default
    return bool(getattr(conf, attr, True))


def _fmt_value(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return str(round(v, 3))
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if s == "" or any(c in _SPECIAL_CHARS for c in s):
        s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\t", " ")
        return f'"{s}"'
    return s


def emit_metric(domain: str, **fields) -> None:
    """Emit one ``BS_METRIC`` line for ``domain``. Best-effort: never raises.

    ``None`` field values are omitted. Booleans render as ``1``/``0``, floats are
    rounded to 3 decimals, strings with spaces/quotes are quoted-and-escaped.
    """
    try:
        conf = _get_conf()
        if not _domain_enabled(conf, domain):
            return
        parts = [MARKER, f"domain={domain}"]
        for key, value in fields.items():
            if value is None:
                continue
            parts.append(f"{key}={_fmt_value(value)}")
        logger.info(" ".join(parts))
    except Exception as exc:
        # Best-effort telemetry: the metric must never break the caller's flow.
        # Not a silent swallow — we log the failure at debug so it is traceable.
        logger.debug("emit_metric failed domain={}: {!r}", domain, exc)


# ---------------------------------------------------------------------------
# DB query latency histogram (design §3 决策 3)
# ---------------------------------------------------------------------------

# Bucket upper bounds in ms; emitted cumulatively as le_<bound> (+ le_inf).
# Cumulative counts are additive across processes/windows, so the monitoring
# layer sums them and runs histogram_quantile for a true global P95.
_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000)


class DbQueryHistogram:
    """Per-process, windowed latency histogram for DB queries.

    ``record`` is O(log buckets) and thread-safe (cursor events fire on many
    threads). ``maybe_flush`` returns a dict ready to splat into
    ``emit_metric("db_query_agg", **res)`` once the window has elapsed, then
    resets. ``count / window_s`` gives QPS; the ``le_*`` buckets give P95.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._sum_ms = 0.0
        self._buckets = [0] * (len(_BUCKETS_MS) + 1)  # last slot = +inf
        self._window_start = None

    def record(self, elapsed_ms: float, now: float) -> None:
        with self._lock:
            if self._window_start is None:
                self._window_start = now
            self._count += 1
            self._sum_ms += elapsed_ms
            # bisect_left => "<= bound" semantics: elapsed==bound lands in that bucket.
            idx = bisect.bisect_left(_BUCKETS_MS, elapsed_ms)
            self._buckets[idx] += 1

    def maybe_flush(self, now: float, window_s: float):
        """Return the aggregate dict + reset if the window elapsed, else None."""
        with self._lock:
            if self._count == 0 or self._window_start is None:
                return None
            if now - self._window_start < window_s:
                return None
            result = {
                "window_s": round(now - self._window_start, 3),
                "count": self._count,
                "sum_ms": round(self._sum_ms, 3),
            }
            cum = 0
            for i, bound in enumerate(_BUCKETS_MS):
                cum += self._buckets[i]
                result[f"le_{bound}"] = cum
            cum += self._buckets[-1]
            result["le_inf"] = cum
            self._count = 0
            self._sum_ms = 0.0
            self._buckets = [0] * (len(_BUCKETS_MS) + 1)
            self._window_start = None
            return result


# Per-process singleton used by the DB cursor-event wiring (T005).
db_histogram = DbQueryHistogram()


# ---------------------------------------------------------------------------
# Connection-pool gauge (design §3 决策 6)
# ---------------------------------------------------------------------------


class _PoolSampler:
    """Time-gates pool sampling to at most once per window per process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_emit = None

    def due(self, now: float, window_s: float) -> bool:
        with self._lock:
            if self._last_emit is None or now - self._last_emit >= window_s:
                self._last_emit = now
                return True
            return False


_pool_sampler = _PoolSampler()


def _max_overflow() -> int:
    try:
        from bisheng.common.services.config_service import settings

        return int(settings.database_pool.max_overflow)
    except Exception:
        return 0


def maybe_emit_pool_gauge(now: float, pools, window_s: float) -> None:
    """Sample connection-pool saturation and emit ``db_pool`` (once per window).

    ``pools`` is an iterable of ``(engine_name, pool)``. Reads only the stable
    public QueuePool methods ``checkedout()/checkedin()/size()`` (design §5
    坑 10); for the async engine pass ``async_engine.sync_engine.pool`` (坑 9).
    Best-effort — a read failure on one pool never blocks the others or the caller.
    """
    if not _pool_sampler.due(now, window_s):
        return
    overflow = _max_overflow()
    for name, pool in pools:
        try:
            checked_out = pool.checkedout()
            idle = pool.checkedin()
            size = pool.size()
        except Exception as exc:
            logger.debug("db_pool gauge read failed engine={}: {!r}", name, exc)
            continue
        capacity = size + overflow
        emit_metric(
            "db_pool",
            engine=name,
            checked_out=checked_out,
            idle=idle,
            size=size,
            capacity=capacity,
            at_capacity=checked_out >= capacity,
        )


# ---------------------------------------------------------------------------
# SQL op extraction (design §5 坑 11 — leading keyword only, never the body)
# ---------------------------------------------------------------------------

_SQL_OPS = ("SELECT", "INSERT", "UPDATE", "DELETE")


def sql_op(statement: str) -> str:
    """Return the leading SQL keyword for the ``op`` label, else ``OTHER``.

    Only the first token is inspected; the statement body and bind params are
    never retained or logged.
    """
    if not statement:
        return "OTHER"
    head = statement.lstrip()[:16].upper()
    for op in _SQL_OPS:
        if head.startswith(op):
            return op
    return "OTHER"
