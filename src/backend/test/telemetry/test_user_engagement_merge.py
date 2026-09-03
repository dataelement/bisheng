"""F058 follow-up — merging mid_user_increment / mid_active_user /
mid_user_daily_participation_fact into one shared ES index.

Covers the two correctness-critical pieces of this merge:
- the incremental-sync watermark query must stay scoped to one source's own records
  when several mid-tables share a physical index (otherwise a higher-frequency sibling
  starves the daily sync of a lower-frequency one — see base.py::_watermark_filter);
- each source tags its documents with a `metric_source` discriminator and a
  source-prefixed `_id`, so records from different sources never collide or get
  conflated when aggregating.
"""

from unittest.mock import MagicMock

from bisheng.telemetry.domain.mid_table.base import BaseMidTable
from bisheng.telemetry.domain.mid_table.daily_participation import DailyParticipationRecord
from bisheng.telemetry.domain.mid_table.derived_events import MidActiveUserJob
from bisheng.telemetry.domain.mid_table.user_engagement_shared import (
    METRIC_SOURCE_ACTIVE_USER,
    METRIC_SOURCE_INCREMENT,
    METRIC_SOURCE_PARTICIPATION,
    USER_ENGAGEMENT_ES_INDEX,
)
from bisheng.telemetry.domain.mid_table.user_increment import UserIncrement, UserIncrementRecord


def _fake_search_response(timestamp):
    return {"hits": {"hits": [{"_source": {"timestamp": timestamp}}]}}


class _NoFilterMidTable(BaseMidTable):
    """A mid-table with no _watermark_filter set — must behave exactly like before
    this change (no scoping filter added to the watermark query)."""

    _index_name: str = "some_other_shared_index"


class _ScopedMidTable(BaseMidTable):
    _index_name: str = USER_ENGAGEMENT_ES_INDEX
    _watermark_filter = {"term": {"metric_source": "some_source"}}


def test_watermark_query_has_no_filter_when_watermark_filter_unset():
    table = _NoFilterMidTable(ensure_sync_index=False)
    table._es_client_sync = MagicMock()
    table._es_client_sync.search.return_value = _fake_search_response(1000)

    result = table.get_latest_record_time_sync()

    assert result == 1000
    body = table._es_client_sync.search.call_args.kwargs["body"]
    assert "query" not in body


def test_watermark_query_scoped_to_source_when_watermark_filter_set():
    table = _ScopedMidTable(ensure_sync_index=False)
    table._es_client_sync = MagicMock()
    table._es_client_sync.search.return_value = _fake_search_response(2000)

    result = table.get_latest_record_time_sync()

    assert result == 2000
    body = table._es_client_sync.search.call_args.kwargs["body"]
    assert body["query"] == {"bool": {"filter": [{"term": {"metric_source": "some_source"}}]}}


def test_user_increment_shares_the_merged_index():
    table = UserIncrement(ensure_sync_index=False)
    assert table._index_name == USER_ENGAGEMENT_ES_INDEX


def test_user_increment_watermark_filter_scoped_to_its_own_source():
    """Regression guard: without this filter, a higher-frequency sibling sharing the
    index (e.g. daily participation, synced every 5 minutes) would make the watermark
    always look like "just now", silently starving the daily user-increment sync."""
    table = UserIncrement(ensure_sync_index=False)
    assert table._watermark_filter == {"term": {"metric_source": METRIC_SOURCE_INCREMENT}}


def test_user_increment_record_tags_its_own_metric_source():
    record = UserIncrementRecord(user_id=1, user_name="u1", timestamp=123)
    assert record.metric_source == METRIC_SOURCE_INCREMENT


def test_mid_active_user_job_writes_to_the_merged_index():
    assert MidActiveUserJob.index_name == USER_ENGAGEMENT_ES_INDEX


def test_mid_active_user_job_transform_tags_metric_source_and_prefixes_id():
    job = MidActiveUserJob(es_client=MagicMock())
    hit = {
        "_id": "raw-hit-id",
        "_source": {
            "timestamp": 1700000000,
            "user_context": {"user_id": 42, "user_name": "张三"},
        },
    }

    action = job._transform_hit_to_action(hit, date_key="2026-08-31")

    assert action["_index"] == USER_ENGAGEMENT_ES_INDEX
    assert action["_id"] == "active_42_2026-08-31"
    assert action["_source"]["metric_source"] == METRIC_SOURCE_ACTIVE_USER
    assert action["_source"]["user_id"] == 42


def test_mid_active_user_job_transform_prefixes_fallback_id_when_no_date_key():
    job = MidActiveUserJob(es_client=MagicMock())
    hit = {"_id": "raw-hit-id", "_source": {"user_context": {}}}

    action = job._transform_hit_to_action(hit, date_key=None)

    assert action["_id"] == "active_raw-hit-id"


def test_daily_participation_record_tags_its_own_metric_source():
    record = DailyParticipationRecord(
        user_id=1,
        user_name="u1",
        timestamp=123,
        local_date="2026-08-31",
        projection_updated_at=123,
    )
    assert record.metric_source == METRIC_SOURCE_PARTICIPATION
