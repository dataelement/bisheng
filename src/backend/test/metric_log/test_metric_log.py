"""Unit tests for the structured metric-log helper (F042 T002).

Covers ``emit_metric`` formatting/escaping/gating and the ``DbQueryHistogram``
bucket classification + windowed flush. Contract: design.md §6.1.

These are pure units — no DB/engine/minio. The DB-event / storage / model / E+
wiring is covered by the per-domain integration tests (T004/T006/T008/T010).
"""

from contextlib import contextmanager

import pytest
from loguru import logger

from bisheng.common.services.metric_log import DbQueryHistogram, emit_metric, sql_op
from bisheng.core.config.settings import MetricLogConf


@contextmanager
def capture_metric_logs():
    """Capture emitted log messages (message body only) for assertions."""
    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m).rstrip("\n")), level="INFO", format="{message}")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


def _line_for(messages: list[str], domain: str) -> str | None:
    prefix = f"BS_METRIC domain={domain}"
    for m in messages:
        # exact domain-token boundary: avoid db_query matching db_query_agg
        if m == prefix or m.startswith(prefix + " "):
            return m
    return None


# ---------------------------------------------------------------------------
# emit_metric — formatting
# ---------------------------------------------------------------------------


def test_emit_metric_basic_line():
    with capture_metric_logs() as messages:
        emit_metric("db_query", op="SELECT", elapsed_ms=253.1, status="ok")
    line = _line_for(messages, "db_query")
    assert line is not None
    assert line == "BS_METRIC domain=db_query op=SELECT elapsed_ms=253.1 status=ok"


def test_emit_metric_omits_none_fields():
    with capture_metric_logs() as messages:
        emit_metric("obj_storage", op="get", result="ok", http_status=200, err_code=None, elapsed_ms=45.2)
    line = _line_for(messages, "obj_storage")
    assert line is not None
    assert "err_code" not in line
    assert "result=ok" in line and "http_status=200" in line


def test_emit_metric_bool_rendered_as_int():
    with capture_metric_logs() as messages:
        emit_metric("model_invoke", is_stream=True, status="success")
        emit_metric("model_invoke", is_stream=False, status="failed")
    lines = [m for m in messages if "BS_METRIC domain=model_invoke" in m]
    assert any("is_stream=1" in m for m in lines)
    assert any("is_stream=0" in m for m in lines)


def test_emit_metric_float_rounded_not_scientific():
    with capture_metric_logs() as messages:
        emit_metric("model_invoke", ttft_ms=340.0, total_ms=5200.456789)
    line = _line_for(messages, "model_invoke")
    assert "ttft_ms=340.0" in line
    # rounded to 3 decimals, no scientific notation
    assert "total_ms=5200.457" in line
    assert "e" not in line.split("total_ms=")[1].split(" ")[0].lower()


def test_emit_metric_escapes_values_with_spaces_or_quotes():
    with capture_metric_logs() as messages:
        emit_metric("eplus_notify", action='knowledge join "x"', result="ok")
    line = _line_for(messages, "eplus_notify")
    assert line is not None
    # value with space/quote must be wrapped so the line stays logfmt-parseable
    assert 'action="knowledge join \\"x\\""' in line
    # result stays bare (no special chars)
    assert "result=ok" in line


def test_emit_metric_marker_and_domain_first():
    with capture_metric_logs() as messages:
        emit_metric("db_pool", checked_out=37, capacity=120)
    line = _line_for(messages, "db_pool")
    assert line.startswith("BS_METRIC domain=db_pool ")


# ---------------------------------------------------------------------------
# emit_metric — gating (global + per-domain switches)
# ---------------------------------------------------------------------------


def _patch_conf(monkeypatch, conf: MetricLogConf):
    # Patch the settings object that metric_log reads (real or premocked).
    from bisheng.common.services import config_service

    monkeypatch.setattr(config_service.settings, "metric_log", conf, raising=False)


def test_emit_metric_disabled_globally(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(enabled=False))
    with capture_metric_logs() as messages:
        emit_metric("db_query", op="SELECT", elapsed_ms=10.0)
    assert _line_for(messages, "db_query") is None


def test_emit_metric_disabled_for_one_domain_only(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(db=False))
    with capture_metric_logs() as messages:
        emit_metric("db_query", op="SELECT", elapsed_ms=10.0)
        emit_metric("obj_storage", op="put", result="ok")
    assert _line_for(messages, "db_query") is None
    assert _line_for(messages, "obj_storage") is not None


def test_emit_metric_db_domains_share_the_db_switch(monkeypatch):
    _patch_conf(monkeypatch, MetricLogConf(db=False))
    with capture_metric_logs() as messages:
        emit_metric("db_query", op="SELECT")
        emit_metric("db_query_agg", count=10)
        emit_metric("db_pool", checked_out=1)
    assert messages == []


# ---------------------------------------------------------------------------
# emit_metric — best-effort: never raises
# ---------------------------------------------------------------------------


def test_emit_metric_never_raises_on_bad_value():
    class Boom:
        def __str__(self):
            raise ValueError("cannot stringify")

        __repr__ = __str__

    # Must not propagate the formatting error to the caller.
    emit_metric("db_query", op=Boom())  # no assertion needed: absence of raise is the test


# ---------------------------------------------------------------------------
# DbQueryHistogram — bucket classification + windowed flush
# ---------------------------------------------------------------------------


def test_histogram_cumulative_buckets_and_count():
    hist = DbQueryHistogram()
    t0 = 1000.0
    hist.record(3.0, t0)  # <= 5
    hist.record(7.0, t0)  # <= 10, not <= 5
    hist.record(5.0, t0)  # boundary: <= 5
    hist.record(300.0, t0)  # <= 500
    hist.record(2000.0, t0)  # > 1000 -> +inf only

    res = hist.maybe_flush(t0 + 10, window_s=10)
    assert res is not None
    assert res["count"] == 5
    assert res["sum_ms"] == pytest.approx(3 + 7 + 5 + 300 + 2000)
    # cumulative (le_) semantics: each bucket includes all smaller ones
    assert res["le_5"] == 2
    assert res["le_10"] == 3
    assert res["le_25"] == 3
    assert res["le_50"] == 3
    assert res["le_100"] == 3
    assert res["le_250"] == 3
    assert res["le_500"] == 4
    assert res["le_1000"] == 4
    assert res["le_inf"] == 5  # == count
    assert res["window_s"] == pytest.approx(10, abs=0.01)


def test_histogram_no_flush_before_window_elapses():
    hist = DbQueryHistogram()
    t0 = 500.0
    hist.record(12.0, t0)
    assert hist.maybe_flush(t0 + 5, window_s=10) is None


def test_histogram_empty_window_does_not_flush():
    hist = DbQueryHistogram()
    assert hist.maybe_flush(9999.0, window_s=10) is None


def test_histogram_resets_after_flush():
    hist = DbQueryHistogram()
    t0 = 0.0
    hist.record(4.0, t0)
    first = hist.maybe_flush(t0 + 10, window_s=10)
    assert first["count"] == 1
    # window resets; a new record starts a fresh window
    hist.record(4.0, t0 + 11)
    second = hist.maybe_flush(t0 + 30, window_s=10)
    assert second["count"] == 1
    assert second["le_5"] == 1
    # no lingering counts from the first window
    assert second["le_inf"] == 1


# ---------------------------------------------------------------------------
# sql_op — leading keyword only, never the statement body (design §5 坑 11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stmt,expected",
    [
        ("SELECT * FROM t WHERE pwd = 'secret'", "SELECT"),
        ("  select 1", "SELECT"),
        ("INSERT INTO t VALUES (1)", "INSERT"),
        ("UPDATE t SET a=1", "UPDATE"),
        ("DELETE FROM t", "DELETE"),
        ("WITH cte AS (...) SELECT ...", "OTHER"),
        ("", "OTHER"),
    ],
)
def test_sql_op_extracts_leading_keyword(stmt, expected):
    assert sql_op(stmt) == expected
