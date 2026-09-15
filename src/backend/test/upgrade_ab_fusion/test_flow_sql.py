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


def test_flow_missing_knowledge_raises():
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
