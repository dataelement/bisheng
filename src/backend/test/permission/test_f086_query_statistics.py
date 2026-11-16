"""AC-17: query timing is scoped to one run and never exposes bind values."""

from sqlalchemy import create_engine, text

from bisheng.core.database.query_statistics import query_statistics


def test_stats_do_not_leak_across_runs_and_capture_real_execution():
    engine = create_engine("sqlite://")
    with query_statistics() as stats:
        with engine.connect() as conn:
            conn.execute(text("select :private_value"), {"private_value": "do-not-record"})
        assert stats.summary()["sql_requests"] == 1
        assert "do-not-record" not in str(stats.summary())
    with query_statistics() as fresh:
        assert fresh.summary()["sql_requests"] == 0
