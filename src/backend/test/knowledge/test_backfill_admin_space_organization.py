from types import SimpleNamespace

from scripts.backfill_admin_space_belonging_organization import first_library_admin, organization_for_space


def department(department_id: int, org_level: str | None, *, tenant_id: int = 1, status: str = "active"):
    return SimpleNamespace(id=department_id, tenant_id=tenant_id, status=status, is_deleted=0, org_level=org_level)


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


def test_first_library_admin_follows_member_list_order():
    chosen = first_library_admin(
        [
            (3, "admin", "张三"),
            (2, "creator", "李四"),
            (1, "admin", "王五"),
            (4, "member", "阿里"),
        ]
    )
    assert chosen == 2
    assert first_library_admin([(3, "admin", "b"), (1, "admin", "a")]) == 1


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
