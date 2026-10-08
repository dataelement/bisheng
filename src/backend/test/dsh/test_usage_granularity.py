"""Explicit resolution for the weekly heatmap preserves the full tenant scope."""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from bisheng.dsh.domain.repositories.admin_queries import DshAdminQueryRepository
from bisheng.dsh.domain.services.profile import profile_scope
from test.dsh.test_usage_time_summary import overview_db  # noqa: F401


def test_department_weekly_summary_returns_actual_hour_buckets(overview_db):  # noqa: F811
    start = datetime(2026, 9, 8, 16, tzinfo=UTC)
    with Session(overview_db) as session, profile_scope(2):
        repository = DshAdminQueryRepository(session)
        result = repository.usage_overview(
            start_at=start,
            end_at=start + timedelta(days=7),
            after_user_id=0,
            limit=1,
            keyword="",
            department_ids=[10, 11],
            selected_department_id=10,
            include_summary=True,
            granularity="hour",
        )
        daily = repository.usage_time_summary(20, start_at=start, end_at=start + timedelta(days=7), granularity="day")
    assert result["summary"]["granularity"] == "hour"
    assert len(result["summary"]["points"]) == 168
    assert result["summary"]["totals"] == result["totals"]
    assert result["summary"]["points"][8]["total_tokens"] == 15
    assert result["summary"]["points"][9]["missing_usage_count"] == 0
    assert result["summary"]["points"][9]["total_tokens"] == 0
    assert daily["totals"]["total_tokens"] == 15
