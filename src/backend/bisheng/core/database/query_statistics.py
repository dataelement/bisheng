"""Optional ContextVar SQL timings for maintenance runs, without bind data."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from hashlib import sha256
from time import monotonic

from sqlalchemy import event
from sqlalchemy.engine import Engine


@dataclass
class QueryStatistics:
    requests: int = 0
    seconds: float = 0.0
    slow: list = field(default_factory=list)
    external_requests: dict = field(default_factory=dict)
    limit_wait_seconds: float = 0.0

    def summary(self):
        return {
            "sql_requests": self.requests,
            "sql_seconds": round(self.seconds, 3),
            "slow_sql": self.slow,
            "external_requests": dict(self.external_requests),
            "rate_limit_wait_seconds": round(self.limit_wait_seconds, 3),
        }


_active = ContextVar("maintenance_query_statistics", default=None)


@event.listens_for(Engine, "before_cursor_execute")
def _before(conn, cursor, statement, parameters, context, executemany):
    if _active.get() is not None:
        context._maintenance_started = monotonic()


@event.listens_for(Engine, "after_cursor_execute")
def _after(conn, cursor, statement, parameters, context, executemany):
    stats = _active.get()
    started = getattr(context, "_maintenance_started", None)
    if stats is None or started is None:
        return
    elapsed = monotonic() - started
    stats.requests += 1
    stats.seconds += elapsed
    if elapsed >= 1 and len(stats.slow) < 100:
        stats.slow.append({"query_fingerprint": sha256(statement.encode()).hexdigest(), "seconds": round(elapsed, 3)})


@event.listens_for(Engine, "handle_error")
def _error(exception_context):
    context = exception_context.execution_context
    if context is not None and getattr(context, "_maintenance_started", None) is not None:
        _after(None, None, exception_context.statement or "", None, context, False)


@contextmanager
def query_statistics():
    stats = QueryStatistics()
    token = _active.set(stats)
    try:
        yield stats
    finally:
        _active.reset(token)


def record_external_request(kind, wait_seconds=0):
    stats = _active.get()
    if stats is not None:
        stats.external_requests[kind] = stats.external_requests.get(kind, 0) + 1
        stats.limit_wait_seconds += wait_seconds
