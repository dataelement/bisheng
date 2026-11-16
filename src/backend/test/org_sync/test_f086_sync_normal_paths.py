"""Normal SSO paths: legal mounts, mixed batches and rollback (R2/R3)."""

from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models import department as department_model
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.department.domain.services import department_service as owner
from bisheng.sso_sync.domain.schemas.payloads import DepartmentsSyncRequest, DepartmentUpsertItem
from bisheng.sso_sync.domain.services.departments_sync_service import DepartmentsSyncService
from test.permission.test_f048_department_scope_runtime import session_factory as department_sessions


@pytest.fixture
async def tree(monkeypatch):
    async for factory in department_sessions.__wrapped__():
        monkeypatch.setattr(owner, "get_async_db_session", factory)
        monkeypatch.setattr(department_model, "get_async_db_session", factory)
        monkeypatch.setattr(owner, "_uses_f048_department_projection", lambda: False)
        monkeypatch.setattr(owner.DepartmentChangeHandler, "execute_async", AsyncMock())
        with bypass_tenant_filter():
            async with factory() as db:
                for identity, parent, path in [
                    (1, None, "/1/"),
                    (2, 1, "/1/2/"),
                    (3, 1, "/1/3/"),
                    (11, 2, "/1/2/11/"),
                    (22, 11, "/1/2/11/22/"),
                    (33, 22, "/1/2/11/22/33/"),
                ]:
                    db.add(
                        Department(
                            id=identity,
                            tenant_id=1,
                            dept_id=f"f086-normal-{identity}",
                            name="before",
                            source="wecom",
                            external_id=str(identity),
                            parent_id=parent,
                            path=path,
                        )
                    )
                await db.commit()
            root = await DepartmentDao.aget_by_id(1)
            monkeypatch.setattr(DepartmentDao, "aget_tenant_root_via_pointer", AsyncMock(return_value=root))
            yield factory


async def move():
    return await owner.DepartmentTopologyProjectionService.aupsert_synced_department(
        source="wecom",
        external_id="11",
        name="after",
        parent_id=3,
        parent_path="/1/3/",
        sort_order=0,
        last_sync_ts=20,
    )


@pytest.mark.parametrize("leaf_tenant", [1, 8])
async def test_legal_mounted_subtree_keeps_identity_and_moves_paths(tree, leaf_tenant):
    async with tree() as db:
        mount, leaf = await db.get(Department, 22), await db.get(Department, 33)
        mount.is_tenant_root, mount.mounted_tenant_id = 1, 8
        leaf.tenant_id = leaf_tenant
        await db.commit()
    await DepartmentDao.aassert_reparent_legal(11, 3)
    await move()
    async with tree() as db:
        root, mount, leaf = [await db.get(Department, i) for i in (11, 22, 33)]
        assert root.parent_id == 3 and root.path == "/1/3/11/"
        assert (mount.path, mount.tenant_id, mount.is_tenant_root, mount.mounted_tenant_id) == ("/1/3/11/22/", 1, 1, 8)
        assert leaf.path == "/1/3/11/22/33/" and leaf.tenant_id == leaf_tenant
        assert all(r.permission_projection_state == "CURRENT" for r in (root, mount, leaf))


@pytest.mark.parametrize("invalid", ["nested_mount", "unexplained_tenant", "dangling_mount"])
async def test_invalid_mount_or_tenant_crossing_rolls_back_tree(tree, invalid):
    async with tree() as db:
        parent, child = await db.get(Department, 3), await db.get(Department, 22)
        if invalid == "nested_mount":
            parent.is_tenant_root, parent.mounted_tenant_id = 1, 9
            child.is_tenant_root, child.mounted_tenant_id = 1, 8
        elif invalid == "unexplained_tenant":
            child.tenant_id = 99
        else:
            child.mounted_tenant_id = 8
        await db.commit()
    with pytest.raises(PermissionInvalidResourceError):
        await move()
    async with tree() as db:
        root, leaf = await db.get(Department, 11), await db.get(Department, 33)
        assert (root.name, root.parent_id, root.path, root.last_sync_ts) == ("before", 2, "/1/2/11/", 0)
        assert leaf.path == "/1/2/11/22/33/"


async def test_mixed_batch_and_repeat_do_not_restore_cached_old_path(tree):
    payload = DepartmentsSyncRequest(
        source_ts=20,
        upsert=[
            DepartmentUpsertItem(external_id="11", name="after", parent_external_id="3", ts=20),
            DepartmentUpsertItem(external_id="33", name="after", parent_external_id="22", ts=20),
        ],
        remove=[],
    )
    for _ in range(2):
        result = await DepartmentsSyncService.execute(payload, row_source="wecom")
        assert not result.errors and result.applied_upsert == 2
        async with tree() as db:
            parent, child = await db.get(Department, 22), await db.get(Department, 33)
            assert parent.path == "/1/3/11/22/"
            assert child.path == parent.path + "33/"


async def test_stale_parent_snapshot_from_another_request_is_not_authoritative(tree):
    await move()
    # A second caller retained a parent snapshot from before the first move.
    await owner.DepartmentTopologyProjectionService.aupsert_synced_department(
        source="wecom",
        external_id="33",
        name="after",
        parent_id=22,
        parent_path="/1/2/11/22/",
        sort_order=0,
        last_sync_ts=30,
    )
    async with tree() as db:
        child = await db.get(Department, 33)
        assert child.path == "/1/3/11/22/33/" and child.last_sync_ts == 30


async def test_healthy_rename_does_not_expand_subtree_reads(tree, monkeypatch):
    walk = AsyncMock(side_effect=AssertionError("healthy rename must not walk the tree"))
    monkeypatch.setattr(owner.DepartmentTopologyProjectionService, "_update_synced_subtree_paths", walk)
    await owner.DepartmentTopologyProjectionService.aupsert_synced_department(
        source="wecom",
        external_id="11",
        name="renamed",
        parent_id=2,
        parent_path="/1/2/",
        sort_order=10,
        last_sync_ts=30,
    )
    walk.assert_not_called()
    async with tree() as db:
        department = await db.get(Department, 11)
        assert department.name == "renamed" and department.path == "/1/2/11/"
