"""东八区时钟与 Alembic 列定义。"""

from datetime import datetime, timezone

from bisheng.common.utils.beijing_time import dump_qa_datetimes, now_beijing, to_beijing_iso
from bisheng.core.database.alembic.versions.v2_6_0_f091_qa_expert_beijing_datetime import (
    down_revision,
    revision,
)


def test_now_beijing_is_naive_and_near_plus_eight() -> None:
    naive = now_beijing()
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    assert naive.tzinfo is None
    delta_hours = (naive - utc).total_seconds() / 3600
    assert 7.5 <= delta_hours <= 8.5


def test_to_beijing_iso_labels_naive_as_plus_eight() -> None:
    assert to_beijing_iso(datetime(2026, 8, 18, 11, 0, 0)) == "2026-08-18T11:00:00+08:00"


def test_dump_qa_datetimes_walks_nested_payload() -> None:
    payload = dump_qa_datetimes(
        {"created_at": datetime(2026, 8, 18, 11, 0, 0), "nested": [{"t": datetime(2026, 8, 18, 12, 0, 0)}]}
    )
    assert payload["created_at"] == "2026-08-18T11:00:00+08:00"
    assert payload["nested"][0]["t"] == "2026-08-18T12:00:00+08:00"


def test_alembic_revision_follows_f090_merge() -> None:
    assert revision == "f091_qa_expert_beijing_datetime"
    assert down_revision == "f090_merge_f083_f087_f089"
