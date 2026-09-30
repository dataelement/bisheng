"""Database regression tests for sync-driven department subtree moves."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

import bisheng.database.models.department as department_module
from bisheng.common.errcode.department import DepartmentCircularMoveError, DepartmentNotFoundError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, DepartmentDao


@pytest.mark.asyncio
async def test_sync_upsert_rewrites_descendant_paths(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Department.__table__.create)

    @asynccontextmanager
    async def _session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(department_module, "get_async_db_session", _session_factory)

    with bypass_tenant_filter():
        async with _session_factory() as session:
            default_root = Department(
                dept_id="BS@root",
                name="默认组织",
                tenant_id=1,
                parent_id=None,
                path="/1/",
                source="local",
                external_id="BS@root",
            )
            session.add(default_root)
            await session.commit()
            await session.refresh(default_root)
            default_root.path = f"/{default_root.id}/"

            synced_root = Department(
                dept_id="SG@root",
                name="第三方根部门",
                tenant_id=1,
                parent_id=None,
                path="",
                source="sg",
                external_id="root",
            )
            session.add(synced_root)
            await session.commit()
            await session.refresh(synced_root)
            synced_root.path = f"/{synced_root.id}/"

            child = Department(
                dept_id="SG@child",
                name="下级部门",
                tenant_id=1,
                parent_id=synced_root.id,
                path=f"/{synced_root.id}/",
                source="sg",
                external_id="child",
            )
            session.add(child)
            await session.commit()
            await session.refresh(child)
            child.path = f"/{synced_root.id}/{child.id}/"
            session.add_all([default_root, synced_root, child])
            await session.commit()

        moved = await DepartmentDao.aupsert_by_external_id(
            source="sg",
            external_id="root",
            name="第三方根部门",
            parent_id=int(default_root.id),
            path=default_root.path,
            sort_order=0,
            last_sync_ts=100,
            tenant_id=1,
        )

        async with _session_factory() as session:
            refreshed_child = (
                await session.exec(
                    select(Department).where(Department.id == child.id),
                )
            ).one()

    assert moved.parent_id == default_root.id
    assert moved.path == f"/{default_root.id}/{synced_root.id}/"
    assert refreshed_child.path == f"/{default_root.id}/{synced_root.id}/{child.id}/"

    await engine.dispose()


@pytest.fixture
async def broken_tree(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Department.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(department_module, "get_async_db_session", sessions)
    with bypass_tenant_filter():
        async with sessions() as session:
            for oid, parent, path, tenant in [
                (1, None, "/1/", 1), (2, 1, "/2/", 1), (3, 1, "/1/3/", 1),
                (4, 3, "/3/4/", 1), (5, 4, "", 1),
                (7, 1, "/1/3/7/", 1), (8, None, "/1/3/8/", 2),
            ]:
                session.add(Department(
                    id=oid, dept_id=f"SG@{oid}", source="sg", external_id=str(oid),
                    name=f"组织{oid}", tenant_id=tenant, parent_id=parent, path=path,
                    status="archived" if oid == 5 else "active", is_deleted=int(oid == 5),
                    is_tenant_root=int(oid == 3), mounted_tenant_id=30 if oid == 3 else None,
                ))
            await session.commit()
        yield sessions
    await engine.dispose()


def stub_move_side_effects(monkeypatch, sessions):
    import bisheng.department.domain.services.department_service as service

    async def get_department(session, _dept_id, _user):
        return (await session.exec(select(Department).where(Department.id == 3))).one()

    monkeypatch.setattr(service, "get_async_db_session", sessions)
    monkeypatch.setattr(service, "_get_dept_and_check_permission", get_department)
    monkeypatch.setattr(service, "aassert_default_root_parent_immutable", AsyncMock())
    monkeypatch.setattr(DepartmentDao, "aassert_reparent_legal", AsyncMock())
    monkeypatch.setattr(service.DepartmentChangeHandler, "on_moved", lambda *a: [])
    monkeypatch.setattr(service.DepartmentChangeHandler, "execute_async", AsyncMock())
    monkeypatch.setattr(
        "bisheng.points.domain.services.department_org_level_labeler.relabel_subtree", AsyncMock()
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.knowledge_space_content.KnowledgeSpaceContentStat.enqueue_department_stat_async",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.tenant.domain.services.user_tenant_sync_service.UserTenantSyncService.sync_subtree_primary_users",
        AsyncMock(),
    )
    return service


async def apply_tree_change(action, parent_id, sessions, monkeypatch):
    if action == "relink":
        return await DepartmentDao.aupdate_parent_link(
            dept_id=3, parent_id=parent_id, parent_path="/stale-cache/", last_sync_ts=100
        )
    if action == "upsert":
        return await DepartmentDao.aupsert_by_external_id(
            source="sg", external_id="3", name="组织3", parent_id=parent_id,
            path="/stale-cache/", sort_order=0, last_sync_ts=100, tenant_id=1,
        )
    from bisheng.department.domain.schemas.department_schema import DepartmentMoveRequest

    service = stub_move_side_effects(monkeypatch, sessions)
    return await service.DepartmentService.amove_department(
        "SG@3", DepartmentMoveRequest(new_parent_id=parent_id), SimpleNamespace(user_id=1, tenant_id=1)
    )


@pytest.mark.parametrize("action", ["upsert", "relink", "move"])
@pytest.mark.parametrize("parent_id", [1, 2], ids=["same-parent", "new-parent"])
async def test_rebuild_uses_relations_not_stored_paths(broken_tree, monkeypatch, action, parent_id):
    await apply_tree_change(action, parent_id, broken_tree, monkeypatch)
    async with broken_tree() as session:
        rows = {d.id: d for d in (await session.exec(select(Department))).all()}
    prefix = "/1/3/" if parent_id == 1 else "/1/2/3/"
    assert rows[3].parent_id == parent_id
    assert (rows[3].is_tenant_root, rows[3].mounted_tenant_id) == (1, 30)
    assert rows[3].path == prefix
    assert rows[4].path == prefix + "4/"
    assert rows[5].path == prefix + "4/5/"
    assert (rows[5].status, rows[5].is_deleted) == ("archived", 1)
    assert rows[7].path == "/1/3/7/"  # 无关组织即使具有旧前缀也不能误改。
    assert rows[8].path == "/1/3/8/"  # 不触碰其他租户。


@pytest.mark.parametrize("action", ["upsert", "relink", "move"])
@pytest.mark.parametrize("parent_id", [4, 8, 999], ids=["descendant", "other-tenant", "missing"])
async def test_invalid_reparent_leaves_tree_unchanged(broken_tree, monkeypatch, action, parent_id):
    async with broken_tree() as session:
        before = [(d.id, d.parent_id, d.path) for d in (await session.exec(select(Department).order_by(Department.id))).all()]
    expected_error = DepartmentCircularMoveError if parent_id == 4 else DepartmentNotFoundError
    with pytest.raises(expected_error):
        await apply_tree_change(action, parent_id, broken_tree, monkeypatch)
    async with broken_tree() as session:
        after = [(d.id, d.parent_id, d.path) for d in (await session.exec(select(Department).order_by(Department.id))).all()]
    assert after == before


@pytest.mark.parametrize("entry", ["sync", "manual"])
@pytest.mark.parametrize("parent_id", [2, 999], ids=["stale-parent-path", "missing-parent"])
async def test_sync_creation_is_canonical_and_atomic(broken_tree, monkeypatch, parent_id, entry):
    async def create():
        if entry == "manual":
            from bisheng.department.domain.schemas.department_schema import DepartmentCreate

            service = stub_move_side_effects(monkeypatch, broken_tree)
            monkeypatch.setattr(service, "_check_permission", AsyncMock())
            monkeypatch.setattr(service, "_get_dept_id_prefix", lambda: "BS")
            monkeypatch.setattr(service, "generate_dept_id", lambda _prefix: "new")
            monkeypatch.setattr(service.DepartmentChangeHandler, "on_created", lambda *a: [])
            monkeypatch.setattr(
                "bisheng.points.domain.services.department_org_level_labeler.apply_org_level_to_node", AsyncMock()
            )
            return await service.DepartmentService.acreate_department(
                DepartmentCreate(name="新增组织", parent_id=parent_id), SimpleNamespace(user_id=1, tenant_id=1)
            )
        return await DepartmentDao.aupsert_by_external_id(
            source="sg", external_id="new", name="新增组织", parent_id=parent_id,
            path="/wrong/", sort_order=0, last_sync_ts=100, tenant_id=1,
        )
    if parent_id == 999:
        with pytest.raises(DepartmentNotFoundError):
            await create()
        async with broken_tree() as session:
            assert (await session.exec(select(Department).where(Department.external_id == "new"))).first() is None
    else:
        created = await create()
        assert created.path == f"/1/2/{created.id}/"


@pytest.mark.parametrize("action", ["upsert", "relink", "move"])
async def test_broken_path_cannot_hide_nested_tenant_mount(broken_tree, monkeypatch, action):
    from bisheng.common.errcode.tenant_tree import TenantTreeNestingForbiddenError

    async with broken_tree() as session:
        for oid in (2, 5):
            dept = (await session.exec(select(Department).where(Department.id == oid))).one()
            dept.is_tenant_root = 1
            dept.mounted_tenant_id = oid + 10
            session.add(dept)
        await session.commit()
    with pytest.raises(TenantTreeNestingForbiddenError):
        await apply_tree_change(action, 2, broken_tree, monkeypatch)
    async with broken_tree() as session:
        root = (await session.exec(select(Department).where(Department.id == 3))).one()
        assert root.parent_id == 1 and root.path == "/1/3/"


@pytest.mark.parametrize("action", ["upsert", "relink", "move"])
async def test_database_write_failure_rolls_back_entire_subtree(broken_tree, monkeypatch, action):
    from sqlalchemy import event

    async with broken_tree() as session:
        engine = session.bind.sync_engine

    writes = []

    def fail_update(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("UPDATE DEPARTMENT"):
            writes.append(statement)
            if len(writes) == 2:
                raise RuntimeError("injected-write-failure")

    event.listen(engine, "before_cursor_execute", fail_update)
    try:
        with pytest.raises(RuntimeError, match="injected-write-failure"):
            await apply_tree_change(action, 2, broken_tree, monkeypatch)
        assert len(writes) == 2
    finally:
        event.remove(engine, "before_cursor_execute", fail_update)
    async with broken_tree() as session:
        nodes = {d.id: d for d in (await session.exec(select(Department))).all()}
        assert (nodes[3].parent_id, nodes[3].path, nodes[4].path, nodes[5].path) == (1, "/1/3/", "/3/4/", "")
