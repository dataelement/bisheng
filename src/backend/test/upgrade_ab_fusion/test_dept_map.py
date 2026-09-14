"""部门映射: 按 external_id bind/create, 禁止按名合并。"""

from __future__ import annotations

from test.upgrade_ab_fusion._packutil import P4, load_module

propose = load_module("fusion_propose_dept", P4 / "03-propose-dept-map.py")
dept_sql = load_module("fusion_dept_sql", P4 / "dept_to_sql.py")


def test_bind_same_external_id_keeps_b_pk():
    result = propose.propose(
        [{"id": "10", "name": "财务", "external_id": "D1", "parent_id": "", "source": "sg", "is_deleted": "0"}],
        [{"id": "88", "name": "财务部", "external_id": "D1", "parent_id": "", "is_deleted": "0"}],
    )
    assert result["map"][0]["action"] == "bind"
    assert result["map"][0]["b_dept_pk"] == "88"
    assert result["conflict"] == []


def test_same_name_different_code_creates_not_merge():
    result = propose.propose(
        [{"id": "10", "name": "财务", "external_id": "A1", "parent_id": "", "source": "sg", "is_deleted": "0"}],
        [{"id": "88", "name": "财务", "external_id": "B9", "parent_id": "", "is_deleted": "0"}],
    )
    assert result["map"][0]["action"] == "create"
    assert result["map"][0]["b_dept_pk"] == ""
    assert "不合并" in result["map"][0]["note"]


def test_missing_external_id_goes_manual():
    result = propose.propose(
        [{"id": "10", "name": "本地科室", "external_id": "", "parent_id": "", "is_deleted": "0"}],
        [],
    )
    assert result["map"] == []
    assert result["manual"][0]["id"] == "10"


def test_create_sql_parent_before_child_and_new_dept_id():
    sql = dept_sql.generate_sql(
        [
            {
                "a_dept_pk": "1",
                "b_dept_pk": "",
                "external_id": "P",
                "action": "create",
                "a_name": "父",
                "a_parent_pk": "",
                "a_source": "sg",
                "a_sort_order": "0",
                "a_status": "active",
                "a_tenant_id": "1",
            },
            {
                "a_dept_pk": "2",
                "b_dept_pk": "",
                "external_id": "C",
                "action": "create",
                "a_name": "子",
                "a_parent_pk": "1",
                "a_source": "sg",
                "a_sort_order": "0",
                "a_status": "active",
                "a_tenant_id": "1",
            },
        ],
        [{"user_id": "9", "department_id": "2", "is_primary": "1", "source": "sg"}],
        "batch-1",
    )
    parent_at = sql.index("external_id='P'")
    child_at = sql.index("external_id='C'")
    assert parent_at < child_at
    assert "fusion-a1" in sql
    assert "fusion_user_map" in sql
    assert "user_department" in sql
