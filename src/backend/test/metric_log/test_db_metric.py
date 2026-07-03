"""DB metric wiring tests (F042 T004).

Covers ``record_db_query`` (slow-line + histogram + agg flush + pool gauge +
error path), the SQLAlchemy cursor-event installation on a real SQLite engine,
the pool-saturation gauge, and the pool wait-timeout branch. Contract: design §6.1.
"""

import time
from contextlib import contextmanager

import pytest
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.pool import QueuePool

from bisheng.common.services import metric_log as ml
from bisheng.common.services.metric_log import (
    DbQueryHistogram,
    maybe_emit_pool_gauge,
    record_db_query,
)
from bisheng.core.config.settings import MetricLogConf
from bisheng.core.database.connection import (
    _emit_pool_wait_timeout_if_needed,
    _install_db_metric_events,
)


@contextmanager
def capture_metric_logs():
    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m).rstrip("\n")), level="INFO", format="{message}")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


def _line_for(messages, domain):
    prefix = f"BS_METRIC domain={domain}"
    for m in messages:
        # exact domain-token boundary: avoid db_query matching db_query_agg
        if m == prefix or m.startswith(prefix + " "):
            return m
    return None


def _patch_conf(monkeypatch, conf):
    from bisheng.common.services import config_service

    monkeypatch.setattr(config_service.settings, "metric_log", conf, raising=False)


@pytest.fixture(autouse=True)
def _reset_db_metric_state():
    """Isolate the per-process histogram + pool sampler singletons between tests."""
    ml.db_histogram = DbQueryHistogram()
    ml._pool_sampler = ml._PoolSampler()
    yield


# ---------------------------------------------------------------------------
# record_db_query
# ---------------------------------------------------------------------------


def test_record_db_query_slow_emits_detail_line(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(db_slow_query_ms=100, db_agg_window_s=0))
    with capture_metric_logs() as messages:
        record_db_query("sync", None, "SELECT * FROM t WHERE pwd='x'", 253.0, now=1.0, status="ok")
    line = _line_for(messages, "db_query")
    assert line is not None
    assert "op=SELECT" in line and "elapsed_ms=253.0" in line and "status=ok" in line
    # never leaks the statement body / bind params (design §5 坑 11)
    assert "pwd" not in line and "FROM" not in line


def test_record_db_query_fast_no_detail_but_counts_in_histogram(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(db_slow_query_ms=100, db_agg_window_s=0))
    with capture_metric_logs() as messages:
        # below threshold -> no db_query detail, but recorded + flushed (window=0)
        record_db_query("sync", None, "SELECT 1", 12.0, now=5.0, status="ok")
    assert _line_for(messages, "db_query") is None
    agg = _line_for(messages, "db_query_agg")
    assert agg is not None and "count=1" in agg and "le_25=1" in agg


def test_record_db_query_error_emits_error_no_agg(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(db_slow_query_ms=100, db_agg_window_s=0))
    with capture_metric_logs() as messages:
        record_db_query("sync", None, "INSERT INTO t VALUES(1)", 5.0, now=1.0, status="error")
    dbq = _line_for(messages, "db_query")
    assert dbq is not None and "status=error" in dbq and "op=INSERT" in dbq
    # a failed query must not pollute the latency histogram
    assert _line_for(messages, "db_query_agg") is None


def test_record_db_query_disabled_emits_nothing(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(db=False))
    with capture_metric_logs() as messages:
        record_db_query("sync", None, "SELECT 1", 999.0, now=1.0, status="ok")
    assert messages == []


# ---------------------------------------------------------------------------
# Cursor-event installation on a real SQLite engine
# ---------------------------------------------------------------------------


def test_install_events_emits_metrics_on_real_queries(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(db_slow_query_ms=0, db_agg_window_s=0))
    engine = create_engine("sqlite://")
    _install_db_metric_events(engine, "sync")
    with capture_metric_logs() as messages:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    # slow threshold 0 -> every query yields a detail line with op parsed
    detail = _line_for(messages, "db_query")
    assert detail is not None and "op=SELECT" in detail
    # window 0 -> aggregate flushes immediately
    assert _line_for(messages, "db_query_agg") is not None


# ---------------------------------------------------------------------------
# Pool saturation gauge
# ---------------------------------------------------------------------------


def test_pool_gauge_reports_checked_out(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(db_agg_window_s=0))
    engine = create_engine("sqlite://", poolclass=QueuePool, pool_size=5, max_overflow=2)
    with capture_metric_logs() as messages:
        with engine.connect():  # one connection checked out
            maybe_emit_pool_gauge(time.monotonic(), [("sync", engine.pool)], window_s=0)
    line = _line_for(messages, "db_pool")
    assert line is not None
    assert "engine=sync" in line and "checked_out=1" in line and "size=5" in line
    assert "at_capacity=0" in line


# ---------------------------------------------------------------------------
# Pool wait-timeout branch (session context exhaustion)
# ---------------------------------------------------------------------------


def test_pool_wait_timeout_emitted_only_for_timeout():
    with capture_metric_logs() as messages:
        _emit_pool_wait_timeout_if_needed("async", SQLAlchemyTimeoutError("QueuePool limit"))
    line = _line_for(messages, "db_pool")
    assert line is not None and "result=wait_timeout" in line and "engine=async" in line

    with capture_metric_logs() as other:
        _emit_pool_wait_timeout_if_needed("async", ValueError("unrelated"))
    assert _line_for(other, "db_pool") is None
