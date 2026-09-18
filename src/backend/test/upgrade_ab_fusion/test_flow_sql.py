"""工作流 UUID 冲突换新; 未映射引用失败关闭."""

import pytest

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.flow_sql import generate_flow_sql, pick_uuid


def test_keep_uuid_when_free():
    assert pick_uuid("abc", set()) == "abc"


def test_new_uuid_when_conflict():
    assert pick_uuid("abc", {"abc"}) != "abc"


def test_flowversion_rewrites_original_version_id():
    sql, _maps, _versions, _reports = generate_flow_sql(
        batch="b1",
        flows=[
            {
                "id": "ffff",
                "name": "wf",
                "user_id": "7",
                "tenant_id": "1",
                "data": {"nodes": [], "edges": []},
                "flow_type": 10,
            }
        ],
        versions=[
            {
                "id": "1",
                "flow_id": "ffff",
                "name": "v1",
                "data": {"nodes": [], "edges": []},
                "user_id": "7",
                "original_version_id": None,
            },
            {
                "id": "2",
                "flow_id": "ffff",
                "name": "v2",
                "data": {"nodes": [], "edges": []},
                "user_id": "7",
                "original_version_id": "1",
            },
        ],
        variables=[],
        maps={"user": {"7": "100"}, "tenant": {"1": "1"}, "knowledge": {}, "model": {}, "tool": {}, "flow": {}},
        a_flow_ids=set(),
        a_flow_names=set(),
        next_version_id=8,
        a_tenant_default="1",
    )
    assert "INSERT INTO flowversion" in sql
    assert "9, 'ffff'" in sql
    assert ", 0, 8, 1);" in sql


def test_variable_insert_includes_value_type():
    sql, _maps, _versions, _reports = generate_flow_sql(
        batch="b1",
        flows=[
            {
                "id": "ffff",
                "name": "wf",
                "user_id": "7",
                "tenant_id": "1",
                "data": {"nodes": [], "edges": []},
                "flow_type": 10,
            }
        ],
        versions=[{"id": "1", "flow_id": "ffff", "name": "v1", "data": {}, "user_id": "7"}],
        variables=[
            {
                "flow_id": "ffff",
                "version_id": "1",
                "node_id": "n1",
                "variable_name": "q",
                "value_type": "1",
                "is_option": "1",
                "value": "hello",
                "tenant_id": "1",
            }
        ],
        maps={"user": {"7": "100"}, "tenant": {"1": "1"}, "knowledge": {}, "model": {}, "tool": {}, "flow": {}},
        a_flow_ids=set(),
        a_flow_names=set(),
        next_version_id=8,
        a_tenant_default="1",
    )
    assert "INSERT INTO t_variable_value" in sql
    assert "value_type" in sql
    assert "'hello'" in sql


def test_flow_dangling_knowledge_is_dropped_with_exception():
    sql, _maps, _versions, _reports = generate_flow_sql(
        batch="b1",
        flows=[
            {
                "id": "ffff",
                "name": "wf",
                "user_id": "7",
                "tenant_id": "1",
                "data": {
                    "nodes": [
                        {
                            "data": {
                                "knowledge": {"type": "knowledge", "value": [{"key": 11}]},
                            }
                        }
                    ],
                    "edges": [],
                },
                "flow_type": 10,
            }
        ],
        versions=[],
        variables=[],
        maps={"user": {"7": "100"}, "tenant": {"1": "1"}, "knowledge": {}, "model": {}, "tool": {}, "flow": {}},
        a_flow_ids=set(),
        a_flow_names=set(),
        next_version_id=8,
        a_tenant_default="1",
    )
    assert "INSERT INTO flow " in sql
    assert "INSERT INTO fusion_exception" in sql
    assert "dangling_knowledge_ref" in sql
    assert '"key": 11' not in sql


def test_orphan_flowversion_is_skipped():
    sql, _maps, version_maps, _reports = generate_flow_sql(
        batch="b1",
        flows=[],
        versions=[
            {
                "id": "33",
                "flow_id": "deadbeef",
                "name": "v0",
                "data": {},
                "user_id": "7",
                "is_delete": 1,
            }
        ],
        variables=[],
        maps={"user": {"7": "100"}, "tenant": {"1": "1"}, "knowledge": {}, "model": {}, "tool": {}, "flow": {}},
        a_flow_ids=set(),
        a_flow_names=set(),
        next_version_id=8,
        a_tenant_default="1",
    )
    assert "INSERT INTO flowversion" not in sql
    assert "orphan_flowversion" in sql
    assert version_maps == []


def test_flow_dangling_model_is_dropped_with_exception():
    sql, _maps, _versions, _reports = generate_flow_sql(
        batch="b1",
        flows=[
            {
                "id": "ffff",
                "name": "wf",
                "user_id": "7",
                "tenant_id": "1",
                "data": {
                    "nodes": [{"data": {"group_params": [{"params": [{"key": "model_id", "value": 3}]}]}}],
                    "edges": [],
                },
                "flow_type": 10,
            }
        ],
        versions=[],
        variables=[],
        maps={
            "user": {"7": "100"},
            "tenant": {"1": "1"},
            "knowledge": {},
            "model": {},
            "tool": {},
            "flow": {},
        },
        a_flow_ids=set(),
        a_flow_names=set(),
        next_version_id=8,
        a_tenant_default="1",
    )
    assert "INSERT INTO flow " in sql
    assert "dangling_model_ref" in sql
    assert '"value":3' not in sql.replace(" ", "")
    assert '"value":null' in sql.replace(" ", "")


def test_flow_unmapped_user_still_raises():
    with pytest.raises(ValueError, match="未映射"):
        generate_flow_sql(
            batch="b1",
            flows=[
                {
                    "id": "ffff",
                    "name": "wf",
                    "user_id": "7",
                    "tenant_id": "1",
                    "data": {
                        "nodes": [{"data": {"group_params": [{"params": [{"key": "user_id", "value": 99}]}]}}],
                        "edges": [],
                    },
                    "flow_type": 10,
                }
            ],
            versions=[],
            variables=[],
            maps={
                "user": {"7": "100"},
                "tenant": {"1": "1"},
                "knowledge": {},
                "model": {},
                "tool": {},
                "flow": {},
            },
            a_flow_ids=set(),
            a_flow_names=set(),
            next_version_id=8,
            a_tenant_default="1",
        )


def test_skip_existing_flow_but_insert_new_version():
    sql, flow_maps, version_maps, _reports = generate_flow_sql(
        batch="b1",
        flows=[
            {
                "id": "ffff",
                "name": "wf",
                "user_id": "7",
                "tenant_id": "1",
                "data": {"nodes": [], "edges": []},
                "flow_type": 10,
            }
        ],
        versions=[
            {
                "id": "1",
                "flow_id": "ffff",
                "name": "v1",
                "data": {"nodes": [], "edges": []},
                "user_id": "7",
            },
            {
                "id": "2",
                "flow_id": "ffff",
                "name": "v2",
                "data": {"nodes": [], "edges": []},
                "user_id": "7",
            },
        ],
        variables=[],
        maps={
            "user": {"7": "100"},
            "tenant": {"1": "1"},
            "knowledge": {},
            "model": {},
            "tool": {},
            "flow": {"ffff": "aabb"},
            "flowversion": {"1": "8"},
        },
        a_flow_ids={"aabb"},
        a_flow_names=set(),
        next_version_id=9,
        a_tenant_default="1",
    )
    assert "INSERT INTO flow " not in sql
    assert sql.count("INSERT INTO flowversion") == 1
    assert version_maps[-1]["b_id"] == "2"
    assert any(m["a_id"] == "aabb" for m in flow_maps)


def test_assistant_skips_unmapped_tool_link():
    from fusion.flow_sql import generate_assistant_sql

    sql, amaps, gaps = generate_assistant_sql(
        batch="b1",
        assistants=[
            {
                "id": "asst1",
                "name": "a",
                "user_id": "7",
                "tenant_id": "1",
                "model_name": "3",
            }
        ],
        links=[
            {"assistant_id": "asst1", "tool_id": "99", "tenant_id": "1"},
            {"assistant_id": "asst1", "knowledge_id": "5", "tenant_id": "1"},
        ],
        maps={
            "user": {"7": "100"},
            "tenant": {"1": "1"},
            "model": {"3": "9"},
            "knowledge": {"5": "201"},
            "tool": {},
            "flow": {},
        },
        a_assistant_ids=set(),
        a_tenant_default="1",
    )
    assert "INSERT INTO assistant " in sql
    assert amaps[0]["a_id"] == "asst1"
    assert len(gaps) == 1
    assert gaps[0]["b_tool_id"] == "99"
    assert sql.count("INSERT INTO assistantlink") == 1
    assert "201" in sql
