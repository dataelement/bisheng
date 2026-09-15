"""标注任务重写用户和应用 UUID."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.mark_sql import generate_mark_sql, remap_csv_ids


def test_remap_csv_ids_drops_unmapped():
    assert remap_csv_ids("7,8,9", {"7": "100", "9": "101"}) == "100,101"


def test_insert_task_record_app_user():
    sql, tmaps, rmaps, amaps = generate_mark_sql(
        batch="b1",
        tasks=[
            {
                "id": "3",
                "create_user": "bob",
                "create_id": "7",
                "app_id": "ffff,skipme",
                "process_users": "7,8",
                "mark_user": "7",
                "status": "1",
                "tenant_id": "1",
            }
        ],
        records=[
            {
                "id": "4",
                "create_user": "bob",
                "create_id": "7",
                "task_id": "3",
                "session_id": "c1",
                "flow_type": "10",
                "status": "2",
                "tenant_id": "1",
            }
        ],
        app_users=[
            {
                "id": "5",
                "app_id": "ffff",
                "user_id": "8",
                "task_id": "3",
                "create_id": "7",
                "status": "1",
                "tenant_id": "1",
            }
        ],
        maps={
            "user": {"7": "100", "8": "200"},
            "flow": {"ffff": "aabb"},
            "chat": {"c1": "c1"},
            "tenant": {"1": "1"},
        },
        a_task_ids=set(),
        a_record_ids=set(),
        a_app_user_ids=set(),
        next_task_id=10,
        next_record_id=20,
        next_app_user_id=30,
        a_tenant_default="1",
    )
    assert tmaps[0]["a_id"] == "10"
    assert rmaps[0]["a_id"] == "20"
    assert amaps[0]["a_id"] == "30"
    assert "INSERT INTO marktask" in sql
    assert "INSERT INTO markrecord" in sql
    assert "INSERT INTO markappuser" in sql
    assert "'aabb'" in sql
    assert "skipme" not in sql


def test_skips_record_when_session_unmapped():
    sql, _t, rmaps, _a = generate_mark_sql(
        batch="b1",
        tasks=[{"id": "3", "create_id": "7", "app_id": "ffff", "process_users": "7"}],
        records=[{"id": "4", "create_id": "7", "task_id": "3", "session_id": "gone"}],
        app_users=[],
        maps={
            "user": {"7": "100"},
            "flow": {"ffff": "aabb"},
            "chat": {},
            "tenant": {"1": "1"},
        },
        a_task_ids=set(),
        a_record_ids=set(),
        a_app_user_ids=set(),
        next_task_id=10,
        next_record_id=20,
        next_app_user_id=30,
        a_tenant_default="1",
    )
    assert rmaps == []
    assert "INSERT INTO markrecord" not in sql
