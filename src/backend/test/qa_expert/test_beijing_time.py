"""东八区时钟与存量平移辅助。"""

from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from bisheng.common.utils.beijing_time import (
    dump_qa_datetimes,
    now_beijing,
    shift_stored_iso,
    to_beijing_iso,
)
from bisheng.core.database.alembic.versions.v2_6_0_f091_qa_expert_beijing_datetime import (
    add_hours_sql,
    down_revision,
    revision,
    shift_table_datetimes,
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


def test_shift_stored_iso_adds_eight_for_naive_utc() -> None:
    assert shift_stored_iso("2026-08-18T03:00:00") == "2026-08-18T11:00:00+08:00"
    assert shift_stored_iso("2026-08-18T03:00:00Z") == "2026-08-18T11:00:00+08:00"
    assert shift_stored_iso("2026-08-18T11:00:00+08:00") == "2026-08-18T11:00:00+08:00"


def test_shift_stored_iso_negative_hours_for_downgrade() -> None:
    assert shift_stored_iso("2026-08-18T11:00:00", hours=-8) == "2026-08-18T03:00:00"
    assert shift_stored_iso("2026-08-18T11:00:00+08:00", hours=-8) == "2026-08-18T03:00:00"


def test_add_hours_sql_mysql_and_dm() -> None:
    assert add_hours_sql("created_at", "mysql", 8) == "DATE_ADD(`created_at`, INTERVAL 8 HOUR)"
    assert add_hours_sql("created_at", "mysql", -8) == "DATE_SUB(`created_at`, INTERVAL 8 HOUR)"
    assert "+ (8/24.0)" in add_hours_sql("created_at", "dm", 8)


def test_alembic_revision_follows_f090_merge() -> None:
    assert revision == "f091_qa_expert_beijing_datetime"
    assert down_revision == "f090_merge_f083_f087_f089"


def test_shift_table_datetimes_sqlite() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE qa_comment (id INTEGER PRIMARY KEY, created_at DATETIME)"))
        conn.execute(text("INSERT INTO qa_comment (id, created_at) VALUES (1, '2026-08-18 03:00:00')"))
        shift_table_datetimes(conn, "qa_comment", ("created_at",), hours=8)
        value = conn.execute(text("SELECT created_at FROM qa_comment WHERE id = 1")).scalar()
    assert "11:00:00" in str(value)
