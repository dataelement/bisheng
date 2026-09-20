"""审计日志: 重写操作者/对象, 跳过未映射与 A 原空间."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.audit_sql import generate_audit_sql


def _maps(**extra):
    base = {
        "user": {"7": "100"},
        "tenant": {"1": "1"},
        "group": {"2": "8"},
        "knowledge": {"5": "10"},
        "file": {},
        "flow": {"ffff": "aabb"},
        "assistant": {},
        "dept": {},
        "llm_server": {},
        "model": {},
        "tool": {},
        "qa": {},
        "review_tag": {},
        "chat": {},
        "message": {},
        "report": {},
    }
    base.update(extra)
    return base


def _row(**kw):
    data = {
        "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "operator_id": "7",
        "operator_name": "u",
        "group_ids": [2],
        "system_id": "knowledge",
        "event_type": "create_knowledge",
        "object_type": "knowledge",
        "object_id": "5",
        "object_name": "库",
        "tenant_id": "1",
        "create_time": "2026-01-01 00:00:00",
    }
    data.update(kw)
    return data


def test_inserts_remapped_knowledge_audit():
    sql, maps = generate_audit_sql(
        batch="b1",
        rows=[_row()],
        maps=_maps(),
        a_existing_ids=set(),
        a_tenant_default="1",
        a_space_ids={3},
    )
    assert "INSERT INTO auditlog" in sql
    assert "operator_id, operator_name" in sql
    assert maps[0]["a_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert "'10'" in sql
    assert "group_ids" in sql
    assert "[8]" in sql.replace(" ", "") or '"8"' in sql or ":8" in sql
    assert "entity='audit'" in sql.replace(" ", "") or ", 'audit'" in sql


def test_skips_unmapped_operator():
    sql, maps = generate_audit_sql(
        batch="b1",
        rows=[_row(operator_id="99")],
        maps=_maps(),
        a_existing_ids=set(),
        a_tenant_default="1",
        a_space_ids=set(),
    )
    assert "INSERT INTO auditlog" not in sql
    assert maps == []
    assert "skipped operator=1" in sql


def test_keeps_system_operator_zero():
    sql, maps = generate_audit_sql(
        batch="b1",
        rows=[_row(operator_id="0", object_type="none", object_id="")],
        maps=_maps(),
        a_existing_ids=set(),
        a_tenant_default="1",
        a_space_ids=set(),
    )
    assert "INSERT INTO auditlog" in sql
    assert maps[0]["b_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_skips_knowledge_space_and_unmapped_knowledge():
    sql, maps = generate_audit_sql(
        batch="b1",
        rows=[
            _row(id="b1", object_type="knowledge_space", object_id="9"),
            _row(id="b2", object_type="knowledge", object_id="99"),
        ],
        maps=_maps(),
        a_existing_ids=set(),
        a_tenant_default="1",
        a_space_ids=set(),
    )
    assert "INSERT INTO auditlog" not in sql
    assert maps == []
    assert "skipped" in sql
    assert "object=2" in sql


def test_skips_object_mapped_to_a_space():
    sql, maps = generate_audit_sql(
        batch="b1",
        rows=[_row(object_id="5")],
        maps=_maps(knowledge={"5": "3"}),
        a_existing_ids=set(),
        a_tenant_default="1",
        a_space_ids={3},
    )
    assert "INSERT INTO auditlog" not in sql
    assert maps == []
    assert "space=1" in sql


def test_uuid_collision_allocates_new():
    src = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    sql, maps = generate_audit_sql(
        batch="b1",
        rows=[_row(id=src, object_type="none", object_id="")],
        maps=_maps(),
        a_existing_ids={src},
        a_tenant_default="1",
        a_space_ids=set(),
    )
    assert maps[0]["a_id"] != src
    assert maps[0]["a_id"] in sql


def test_skip_existing_audit():
    src = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    sql, maps = generate_audit_sql(
        batch="b1",
        rows=[_row(id=src)],
        maps=_maps(),
        a_existing_ids=set(),
        a_tenant_default="1",
        a_space_ids=set(),
        existing_audit={src: "dst-keep"},
    )
    assert "INSERT INTO auditlog" not in sql
    assert maps == [{"b_id": src, "a_id": "dst-keep"}]


def test_rewrites_metadata_knowledge_and_skips_a_space():
    sql, maps = generate_audit_sql(
        batch="b1",
        rows=[
            _row(
                object_type="none",
                object_id="",
                metadata={"knowledge_id": 5, "responsible_user_id": 7},
            )
        ],
        maps=_maps(),
        a_existing_ids=set(),
        a_tenant_default="1",
        a_space_ids=set(),
    )
    assert "INSERT INTO auditlog" in sql
    assert maps
    assert "10" in sql
    assert "100" in sql

    sql2, maps2 = generate_audit_sql(
        batch="b1",
        rows=[
            _row(
                object_type="none",
                object_id="",
                metadata={"knowledge_id": 5},
            )
        ],
        maps=_maps(knowledge={"5": "3"}),
        a_existing_ids=set(),
        a_tenant_default="1",
        a_space_ids={3},
    )
    assert "INSERT INTO auditlog" not in sql2
    assert maps2 == []
