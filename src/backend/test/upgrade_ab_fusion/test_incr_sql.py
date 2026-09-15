"""增量 SQL: 删除不回滚整批, UPDATE 不碰 A 空间."""

import pytest

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.incr_sql import generate_incr_delete_sql, generate_incr_update_sql


def test_delete_does_not_mark_batch_rolled_back():
    sql = generate_incr_delete_sql(
        batch="b1",
        deleted=[{"entity": "file", "src_id": "12"}, {"entity": "knowledge", "src_id": "5"}],
        maps={"file": {"12": "20"}, "knowledge": {"5": "10"}},
        a_space_ids={3},
    )
    assert "DELETE FROM knowledgefile WHERE id IN (20)" in sql
    assert "DELETE FROM knowledge WHERE id IN (10) AND type IN (0,1)" in sql
    assert "fusion_map" in sql
    assert "rolled_back" not in sql
    assert "AND entity='knowledge' AND src_id IN ('5')" in sql
    assert "UPDATE fusion_batch" not in sql


def test_delete_refuses_a_space():
    with pytest.raises(ValueError, match="A 原空间"):
        generate_incr_delete_sql(
            batch="b1",
            deleted=[{"entity": "knowledge", "src_id": "5"}],
            maps={"knowledge": {"5": "3"}},
            a_space_ids={3},
        )


def test_update_knowledge_requires_type_filter():
    sql = generate_incr_update_sql(
        batch="b1",
        knowledges=[{"id": "5", "name": "库", "state": 1, "description": "d"}],
        files=[],
        flows=[],
        assistants=[],
        maps={"knowledge": {"5": "10"}},
        updated={("knowledge", "5")},
        a_space_ids={3},
        a_tenant_default="1",
    )
    assert "UPDATE knowledge SET" in sql
    assert "type IN (0,1)" in sql
    assert "status=" not in sql.split("UPDATE knowledge")[1].split(";")[0]


def test_update_refuses_a_space_id():
    with pytest.raises(ValueError, match="A 原空间"):
        generate_incr_update_sql(
            batch="b1",
            knowledges=[{"id": "5", "name": "x"}],
            files=[],
            flows=[],
            assistants=[],
            maps={"knowledge": {"5": "3"}},
            updated={("knowledge", "5")},
            a_space_ids={3},
            a_tenant_default="1",
        )


def test_update_flow_does_not_touch_status():
    sql = generate_incr_update_sql(
        batch="b1",
        knowledges=[],
        files=[],
        flows=[
            {
                "id": "ffff",
                "name": "wf",
                "description": "d",
                "data": {"nodes": [], "edges": []},
                "status": 2,
            }
        ],
        assistants=[],
        maps={"flow": {"ffff": "aabb"}},
        updated={("flow", "ffff")},
        a_space_ids=set(),
        a_tenant_default="1",
    )
    assert "UPDATE flow SET name=" in sql
    assert "SET status=" not in sql
