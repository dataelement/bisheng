"""组可见性只挂新增资源, 不给 A 原工具扩权."""

import pytest

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.group_resource_sql import generate_group_resource_sql


def test_maps_created_knowledge_skips_tool_and_space():
    sql, maps, tuples = generate_group_resource_sql(
        batch="b1",
        rows=[
            {"id": "1", "group_id": "3", "third_id": "5", "type": 1, "tenant_id": "1"},
            {"id": "2", "group_id": "3", "third_id": "8", "type": 4, "tenant_id": "1"},
            {"id": "3", "group_id": "3", "third_id": "9", "type": 1, "tenant_id": "1"},
        ],
        maps={
            "group": {"3": "30"},
            "knowledge": {"5": "10"},
            "tool": {"8": "80"},
            "tenant": {"1": "1"},
        },
        a_existing_ids=set(),
        next_id=50,
        a_tenant_default="1",
        a_space_ids={4},
    )
    assert len(maps) == 1
    assert maps[0]["a_id"] == "50"
    assert "INSERT INTO groupresource" in sql
    assert tuples[0]["user"] == "user_group:30#admin"
    assert tuples[0]["object"] == "knowledge_library:10"


def test_refuses_a_space_id():
    with pytest.raises(ValueError, match="A 原空间"):
        generate_group_resource_sql(
            batch="b1",
            rows=[{"id": "1", "group_id": "3", "third_id": "5", "type": 1}],
            maps={"group": {"3": "30"}, "knowledge": {"5": "4"}, "tenant": {"1": "1"}},
            a_existing_ids=set(),
            next_id=1,
            a_tenant_default="1",
            a_space_ids={4},
        )
