"""OpenFGA 只给新增传统库/工作流/助手写 owner, 禁止碰到 A 空间."""

import pytest

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.openfga_tuples import (
    assert_no_a_space_objects,
    generate_owner_tuples,
    write_body,
)


def test_owners_for_library_workflow_assistant():
    rows = generate_owner_tuples(
        knowledges=[
            {"id": "5", "type": 0, "user_id": "7"},
            {"id": "9", "type": 3, "user_id": "7"},
        ],
        flows=[{"id": "ffff", "flow_type": 10, "user_id": "7"}],
        assistants=[{"id": "aa", "user_id": "7"}],
        maps={
            "user": {"7": "100"},
            "knowledge": {"5": "10", "9": "99"},
            "flow": {"ffff": "aabb"},
            "assistant": {"aa": "cc"},
        },
        migrate_b_spaces=False,
    )
    objs = {r["object"] for r in rows}
    assert "knowledge_library:10" in objs
    assert "workflow:aabb" in objs
    assert "assistant:cc" in objs
    assert "knowledge_space:99" not in objs
    assert all(r["relation"] == "owner" and r["user"] == "user:100" for r in rows)


def test_refuses_tuple_on_a_space():
    with pytest.raises(ValueError, match="A 原空间"):
        assert_no_a_space_objects(
            [{"user": "user:1", "relation": "owner", "object": "knowledge_library:3"}],
            {3},
        )


def test_write_body_shape():
    body = write_body(
        [{"user": "user:1", "relation": "owner", "object": "workflow:x"}],
        "model-1",
    )
    assert body["authorization_model_id"] == "model-1"
    assert body["writes"]["tuple_keys"][0]["relation"] == "owner"
