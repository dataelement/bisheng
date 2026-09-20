"""部门/角色授权只挂新建资源, 不给 A 原对象和工具扩权."""

import pytest

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.openfga_grants import (
    dept_subjects_from_rows,
    generate_role_access_sql,
    generate_role_grant_tuples,
    remap_b_openfga_tuples,
)


def test_role_grants_expand_users_skip_tools():
    tuples = generate_role_grant_tuples(
        role_access=[
            {"id": "1", "role_id": "9", "third_id": "5", "type": "1"},
            {"id": "2", "role_id": "9", "third_id": "8", "type": "7"},
        ],
        user_roles=[{"user_id": "7", "role_id": "9"}],
        maps={
            "role": {"9": "40"},
            "user": {"7": "100"},
            "knowledge": {"5": "10"},
            "tool": {"8": "80"},
        },
        a_space_ids={3},
    )
    assert tuples == [
        {
            "user": "user:100",
            "relation": "viewer",
            "object": "knowledge_library:10",
        }
    ]


def test_role_access_sql_refuses_a_space():
    with pytest.raises(ValueError, match="A 原空间"):
        generate_role_access_sql(
            batch="b1",
            role_access=[{"id": "1", "role_id": "9", "third_id": "5", "type": "1"}],
            maps={"role": {"9": "40"}, "knowledge": {"5": "3"}, "tenant": {"1": "1"}},
            a_existing_ids=set(),
            next_id=1,
            a_tenant_default="1",
            a_space_ids={3},
        )


def test_dept_bind_and_as_group_remap_from_b_fga():
    subjects = dept_subjects_from_rows(
        [
            {"b_dept_pk": "3", "a_dept_pk": "30", "action": "bind"},
            {"b_dept_pk": "4", "a_group_id": "88", "action": "as_group"},
        ]
    )
    rows = remap_b_openfga_tuples(
        rows=[
            {
                "user": "department:3#member",
                "relation": "editor",
                "object": "knowledge_library:5",
            },
            {
                "user": "department:4#member",
                "relation": "viewer",
                "object": "workflow:ffff",
            },
            {
                "user": "department:3#member",
                "relation": "viewer",
                "object": "tool:8",
            },
            {
                "user": "user:7",
                "relation": "owner",
                "object": "knowledge_library:99",
            },
        ],
        maps={
            "knowledge": {"5": "10"},
            "flow": {"ffff": "aabb"},
            "user": {"7": "100"},
            "group": {},
        },
        dept_subjects=subjects,
        a_space_ids={3},
    )
    objs = {(r["user"], r["relation"], r["object"]) for r in rows}
    assert ("department:30#member", "editor", "knowledge_library:10") in objs
    assert ("user_group:88#member", "viewer", "workflow:aabb") in objs
    assert not any("tool:" in r["object"] for r in rows)
    assert not any("99" in r["object"] for r in rows)
