"""F009 AC-04, AC-05, AC-38: business boundaries differ from storage."""

import pytest

from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant
from test.fixtures.managed_tenant import managed_db as managed_db


@pytest.fixture
async def scope_db(managed_db, monkeypatch):
    from bisheng.department.domain.repositories import policy_scope_repository as module

    await managed_db.create(Department, Tenant)
    monkeypatch.setattr(module, "get_async_db_session", managed_db.sessions)
    monkeypatch.setattr(module, "get_sync_db_session", managed_db.sync_sessions)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            session.add_all(
                [
                    Tenant(id=1, tenant_code="root", tenant_name="Root", root_dept_id=10),
                    Tenant(id=2, tenant_code="child", tenant_name="Child", root_dept_id=20, parent_tenant_id=1),
                    Department(id=10, dept_id="root", name="root", tenant_id=1, path="/10/"),
                    Department(
                        id=20,
                        dept_id="mount",
                        name="mount",
                        tenant_id=1,
                        path="/10/20/",
                        parent_id=10,
                        is_tenant_root=1,
                        mounted_tenant_id=2,
                    ),
                    Department(id=30, dept_id="leaf", name="leaf", tenant_id=1, path="/10/20/30/", parent_id=20),
                ]
            )
            await session.commit()
    return managed_db


async def test_mounted_storage_root_resolves_child_business(scope_db):
    """AC-04: neither actor H nor department storage S determines B."""
    from bisheng.department.application.business_scope import department_policy_facts, department_policy_facts_sync

    facts = await department_policy_facts(30)
    assert (facts.business_tenant_id, facts.storage_tenant_id) == (2, 1)
    assert facts.ancestor_ids == (20, 30)
    assert department_policy_facts_sync(30) == facts


@pytest.mark.parametrize("damage", ["disabled", "pointer", "path", "cycle", "projection"])
async def test_invalid_mount_facts_fail_closed(scope_db, damage):
    """AC-38: invalid boundary cannot silently fall back to Root."""
    from bisheng.department.application.business_scope import department_policy_facts

    with bypass_tenant_filter():
        async with scope_db.sessions() as session:
            mount = await session.get(Department, 20)
            if damage == "disabled":
                (await session.get(Tenant, 2)).status = "disabled"
            elif damage == "pointer":
                (await session.get(Tenant, 2)).root_dept_id = 30
            elif damage == "path":
                mount.path = "/20/"
            elif damage == "cycle":
                mount.parent_id = 30
            else:
                mount.permission_projection_state = "PROJECTING"
            await session.commit()
    with pytest.raises(RolePolicyUnavailableError):
        await department_policy_facts(30)
