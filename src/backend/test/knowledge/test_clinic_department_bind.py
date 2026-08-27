"""科室绑定树裁剪：只保留到 office，未打标不猜。"""

from types import SimpleNamespace

from bisheng.knowledge.domain.services.clinic_department_bind import (
    CLINIC_BIND_ORG_LEVEL,
    filter_clinic_bind_tree_departments,
    is_clinic_bindable_department,
)


def _dept(
    dept_id: int,
    *,
    name: str,
    org_level: str | None,
    parent_id: int | None = None,
    path: str | None = None,
):
    return SimpleNamespace(
        id=dept_id,
        dept_id=f"SG@{dept_id}",
        name=name,
        short_name=None,
        parent_id=parent_id,
        path=path or (f"/{parent_id}/{dept_id}/" if parent_id else f"/{dept_id}/"),
        sort_order=0,
        org_level=org_level,
        status="active",
    )


def test_is_clinic_bindable_only_office() -> None:
    assert is_clinic_bindable_department(_dept(1, name="科室", org_level="office"))
    assert not is_clinic_bindable_department(_dept(2, name="部门", org_level="dept"))
    assert not is_clinic_bindable_department(_dept(3, name="公司", org_level="company"))
    assert not is_clinic_bindable_department(_dept(4, name="班组", org_level="squad"))
    assert not is_clinic_bindable_department(_dept(5, name="未打标", org_level=None))
    assert CLINIC_BIND_ORG_LEVEL == "office"


def test_filter_keeps_company_dept_office_drops_squad_and_unlabeled() -> None:
    company = _dept(1, name="公司", org_level="company", path="/1/")
    dept = _dept(2, name="部门", org_level="dept", parent_id=1, path="/1/2/")
    office = _dept(3, name="科室", org_level="office", parent_id=2, path="/1/2/3/")
    squad = _dept(4, name="班组", org_level="squad", parent_id=3, path="/1/2/3/4/")
    unlabeled = _dept(5, name="未打标", org_level=None, parent_id=2, path="/1/2/5/")

    result = filter_clinic_bind_tree_departments([company, dept, office, squad, unlabeled])
    by_id = {item.id: item for item in result}

    assert set(by_id) == {1, 2, 3}
    assert by_id[1].parent_id is None
    assert by_id[2].parent_id == 1
    assert by_id[3].parent_id == 2
    assert by_id[3].org_level == "office"


def test_filter_drops_nodes_under_office_even_if_mislabeled() -> None:
    office = _dept(3, name="科室", org_level="office", path="/1/2/3/")
    fake_dept = _dept(9, name="科室下误标部门", org_level="dept", parent_id=3, path="/1/2/3/9/")

    result = filter_clinic_bind_tree_departments([office, fake_dept])
    assert [item.id for item in result] == [3]


def test_filter_reparents_office_when_unlabeled_parent_dropped() -> None:
    company = _dept(1, name="公司", org_level="company", path="/1/")
    unlabeled = _dept(8, name="未打标中间层", org_level=None, parent_id=1, path="/1/8/")
    office = _dept(3, name="科室", org_level="office", parent_id=8, path="/1/8/3/")

    result = filter_clinic_bind_tree_departments([company, unlabeled, office])
    by_id = {item.id: item for item in result}
    assert set(by_id) == {1, 3}
    assert by_id[3].parent_id == 1
