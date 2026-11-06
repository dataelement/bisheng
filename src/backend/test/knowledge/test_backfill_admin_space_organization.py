from types import SimpleNamespace

from scripts.backfill_admin_space_belonging_organization import (
    first_displayed_manager,
    organization_above_squad,
    organization_for_space,
)


def department(
    department_id: int,
    org_level: str | None,
    *,
    tenant_id: int = 1,
    status: str = "active",
    parent_id: int | None = None,
):
    return SimpleNamespace(
        id=department_id,
        tenant_id=tenant_id,
        status=status,
        is_deleted=0,
        org_level=org_level,
        parent_id=parent_id,
    )


def test_department_space_uses_library_admin_organization():
    organization_id, reason = organization_for_space(
        level="department",
        owner_type="department",
        owner_id=20,
        binding_department_id=20,
        department=department(44, "office"),
        creator_organization_id=None,
        tenant_id=1,
        admin_organization_id=44,
    )
    assert organization_id == 44
    assert reason == "ok"


def test_excluded_department_space_is_skipped():
    organization_id, reason = organization_for_space(
        level="department",
        owner_type="department",
        owner_id=20,
        binding_department_id=None,
        department=None,
        creator_organization_id=None,
        tenant_id=1,
        excluded=True,
        admin_organization_id=44,
    )
    assert organization_id is None
    assert reason == "department_space_excluded"


def test_first_displayed_manager_skips_admin_account_and_uses_page_order():
    chosen = first_displayed_manager(
        [(1, "张三"), (8, "李四"), (3, "王五")],
        1,
    )
    assert chosen == 8
    assert first_displayed_manager([(1, "张三")], 1) is None
    assert first_displayed_manager([(4, "同名"), (9, "同名")], 1) == 4


def test_squad_manager_organization_uses_parent_office():
    organization_id, reason = organization_above_squad(
        department(50, "squad", parent_id=30),
        department(30, "office"),
        1,
    )
    assert organization_id == 30
    assert reason == "ok"


def test_office_manager_organization_stays_on_that_office():
    organization_id, reason = organization_above_squad(department(30, "office"), None, 1)
    assert organization_id == 30
    assert reason == "ok"


def test_squad_without_office_parent_is_skipped():
    organization_id, reason = organization_above_squad(
        department(50, "squad", parent_id=20),
        department(20, "dept"),
        1,
    )
    assert organization_id is None
    assert reason == "department_manager_squad_parent_not_office"


def test_department_space_without_manager_organization_is_skipped():
    organization_id, reason = organization_for_space(
        level="department",
        owner_type="department",
        owner_id=20,
        binding_department_id=20,
        department=None,
        creator_organization_id=None,
        tenant_id=1,
        department_manager_reason="department_manager_missing",
    )
    assert organization_id is None
    assert reason == "department_manager_missing"


def test_clinic_space_uses_binding_office():
    organization_id, reason = organization_for_space(
        level="team_ks",
        owner_type="user",
        owner_id=7,
        binding_department_id=30,
        department=department(30, "office"),
        creator_organization_id=None,
        tenant_id=1,
    )
    assert organization_id == 30
    assert reason == "ok"


def test_team_without_binding_uses_creator_primary_organization():
    organization_id, reason = organization_for_space(
        level="team",
        owner_type="user_group",
        owner_id=8,
        binding_department_id=None,
        department=None,
        creator_organization_id=44,
        tenant_id=1,
        admin_organization_id=None,
    )
    assert organization_id == 44
    assert reason == "ok"


def test_team_without_creator_organization_is_skipped():
    organization_id, reason = organization_for_space(
        level="team",
        owner_type="user",
        owner_id=9,
        binding_department_id=None,
        department=None,
        creator_organization_id=None,
        tenant_id=1,
    )
    assert organization_id is None
    assert reason == "team_creator_no_unique_primary_organization"
