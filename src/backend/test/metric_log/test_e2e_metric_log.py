"""End-to-end (real code path) integration test for F042 metric logging.

F042 exposes no HTTP endpoint and no UI (design §1 non-goal), so the standard
API/UI e2e harness (auth / UnifiedResponseModel / permission pairing) does not
apply. The meaningful e2e here is: drive the REAL integrated path — a real
``DatabaseConnectionManager`` engine with real cursor-event wiring, real
histogram, and the real ``settings.metric_log`` config — and assert the
``BS_METRIC`` lines actually flow, and that queries still return correct results.

Only SQLite stands in for the DB; none of the F042 code is mocked. The
storage / model / E+ real paths need external services (minio / LLM / E+ gateway)
and are covered at the method level by the domain unit tests.
"""

from contextlib import contextmanager

import pytest
from loguru import logger
from sqlalchemy import text

from bisheng.common.services import metric_log as ml
from bisheng.common.services.metric_log import DbQueryHistogram
from bisheng.core.config.settings import MetricLogConf
from bisheng.core.database.connection import DatabaseConnectionManager


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
        if m == prefix or m.startswith(prefix + " "):
            return m
    return None


@pytest.fixture(autouse=True)
def _reset_histogram():
    ml.db_histogram = DbQueryHistogram()
    ml._pool_sampler = ml._PoolSampler()
    yield


@pytest.fixture
def set_conf(monkeypatch):
    from bisheng.common.services import config_service

    def _set(**kw):
        monkeypatch.setattr(config_service.settings, "metric_log", MetricLogConf(**kw), raising=False)

    return _set


def test_e2e_real_db_path_emits_metrics(set_conf):
    """AC (design §1 ①): real engine + real cursor events emit db_query + db_query_agg,
    and the query still returns the correct result (埋点 is transparent)."""
    set_conf(db_slow_query_ms=0, db_agg_window_s=0)  # force detail + immediate flush
    mgr = DatabaseConnectionManager("sqlite://")

    with capture_metric_logs() as messages:
        with mgr.create_session() as session:
            rows = session.execute(text("SELECT 1")).all()

    # 1) query semantics unchanged
    assert rows == [(1,)]

    # 2) slow-query detail line with op parsed, no SQL body leaked
    detail = _line_for(messages, "db_query")
    assert detail is not None and "op=SELECT" in detail and "status=ok" in detail
    assert "SELECT 1" not in detail  # §5 坑 11: statement body never logged

    # 3) aggregate line: count (→QPS) + cumulative buckets (→P95)
    agg = _line_for(messages, "db_query_agg")
    assert agg is not None
    assert "count=" in agg and "le_inf=" in agg and "sum_ms=" in agg


def test_e2e_disabled_switch_is_transparent(set_conf):
    """Acceptance (tasks 开发模式): with MetricLogConf disabled, the real path emits
    ZERO BS_METRIC lines and behaves exactly as before the feature."""
    set_conf(enabled=False)
    mgr = DatabaseConnectionManager("sqlite://")

    with capture_metric_logs() as messages:
        with mgr.create_session() as session:
            rows = session.execute(text("SELECT 42")).all()

    assert rows == [(42,)]
    assert messages == []  # nothing emitted when disabled


def test_e2e_domain_switch_off_only_silences_that_domain(set_conf):
    """db=False silences DB metrics while other domains stay enabled."""
    set_conf(db=False)
    mgr = DatabaseConnectionManager("sqlite://")

    with capture_metric_logs() as messages:
        with mgr.create_session() as session:
            session.execute(text("SELECT 1")).all()

    assert _line_for(messages, "db_query") is None
    assert _line_for(messages, "db_query_agg") is None
