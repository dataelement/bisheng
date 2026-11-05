"""Workflow business writes join the caller's transaction and root latch.

覆盖 AC: AC-87, AC-88, AC-89. SQLite proves atomic SQL behavior, not real
MySQL/DM8 locking; lock statements are also inspected using MySQL compilation.
"""

import re
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import Session

from bisheng.common.errcode.flow import CurVersionDelError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.core.database import tenant_filter
from bisheng.database.models import flow as flow_module
from bisheng.database.models.flow import Flow, FlowDao, FlowType
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.repositories.workflow_version_repository import WorkflowVersionRepository


def data(label):
    return {"nodes": [], "edges": [], "label": label}


@pytest.fixture(autouse=True)
def tenant():
    token = set_current_tenant_id(101)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    names = tenant_filter._tenant_aware_tables | {Flow.__tablename__, FlowVersion.__tablename__}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()
    path = tmp_path / "workflow.db"
    sync_engine = sa.create_engine(f"sqlite:///{path}")
    metadata = sa.MetaData()
    for model in (Flow, FlowVersion):
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    column.name,
                    column.type.copy(),
                    primary_key=column.primary_key,
                    nullable=column.nullable,
                    server_default=(
                        sa.text("CURRENT_TIMESTAMP")
                        if column.name in {"create_time", "update_time"}
                        else column.server_default
                    ),
                )
                for column in model.__table__.columns
            ],
        )
    metadata.create_all(sync_engine)
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    @contextmanager
    def sync_session():
        with Session(sync_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(flow_module, "get_sync_db_session", sync_session)
    monkeypatch.setattr(flow_module.telemetry_service, "log_event_sync", lambda **kwargs: None)
    with Session(sync_engine) as session:
        session.add(Flow(id="wf", name="workflow", user_id=11, tenant_id=101, data=data("v0")))
        session.add(FlowVersion(id=1, flow_id="wf", name="v0", tenant_id=101, is_current=1, data=data("v0")))
        session.add(FlowVersion(id=2, flow_id="wf", name="draft", tenant_id=101, data=data("draft")))
        session.add(FlowVersion(id=3, flow_id="wf", name="deleted", tenant_id=101, is_delete=1, data=data("deleted")))
        session.add(Flow(id="other", name="other tenant", user_id=21, tenant_id=202, data=data("other")))
        session.commit()
    yield async_engine, sync_engine
    await async_engine.dispose()
    sync_engine.dispose()


def snapshot(sync_engine):
    with sync_engine.connect() as connection:
        return (
            connection.execute(sa.text("SELECT id,data,is_delete FROM flow ORDER BY id")).all(),
            connection.execute(
                sa.text("SELECT id,flow_id,name,data,is_delete,is_current FROM flowversion ORDER BY id")
            ).all(),
        )


async def test_new_root_and_v0_id_are_flushed_but_external_rollback_removes_both(store):
    async_engine, sync_engine = store
    before = snapshot(sync_engine)
    async with AsyncSession(async_engine, expire_on_commit=False) as session:
        root = Flow(id="new", name="new", user_id=11, tenant_id=101, data=data("new"))
        saved, initial = await WorkflowVersionRepository.acreate_workflow(session, root)
        assert saved is root and initial.id is not None
        assert initial.flow_id == "new" and initial.is_current == 1 and initial.tenant_id == 101
        assert initial.data == root.data
        await session.rollback()
    assert snapshot(sync_engine) == before


@pytest.mark.parametrize("operation", ["create", "update", "restore", "delete_version", "delete_root", "current"])
async def test_reference_failure_rolls_back_the_whole_external_business_unit(store, operation):
    async_engine, sync_engine = store
    before = snapshot(sync_engine)
    with pytest.raises(RuntimeError, match="binding write failed"):
        async with AsyncSession(async_engine, expire_on_commit=False) as session, session.begin():
            root = await WorkflowVersionRepository.alock_root(session, "wf", 101)
            if operation == "create":
                version = await WorkflowVersionRepository.acreate_version(
                    session, root, FlowVersion(flow_id="wf", name="new", data=data("new"))
                )
                assert version.id not in {None, 1, 2, 3}
            elif operation in {"update", "restore"}:
                version = FlowVersion(
                    id=1 if operation == "update" else 3,
                    flow_id="wf",
                    name="changed",
                    description="changed description",
                    data=data("changed"),
                    is_delete=0,
                )
                await WorkflowVersionRepository.aupdate_version(session, root, version)
                assert root.data == data("changed") if operation == "update" else root.data == data("v0")
            elif operation == "delete_version":
                await WorkflowVersionRepository.asoft_delete_version(session, root, 2)
            elif operation == "delete_root":
                assert {
                    version.id for version in await WorkflowVersionRepository.asoft_delete_workflow(session, root)
                } == {1, 2, 3}
            else:
                await WorkflowVersionRepository.aswitch_current(session, root, 2)
                assert root.data == data("draft")
            raise RuntimeError("binding write failed")
    assert snapshot(sync_engine) == before


async def test_delete_one_version_preserves_current_and_other_saved_versions(store):
    async_engine, _ = store
    async with AsyncSession(async_engine, expire_on_commit=False) as session, session.begin():
        root = await WorkflowVersionRepository.alock_root(session, "wf", 101)
        await WorkflowVersionRepository.asoft_delete_version(session, root, 2)
        assert [version.id for version in await WorkflowVersionRepository.alist_versions(session, root)] == [1]
        all_versions = await WorkflowVersionRepository.alist_versions(session, root, include_deleted=True)
        assert [(version.id, version.is_delete) for version in all_versions] == [(1, 0), (2, 1), (3, 1)]
        assert all_versions[1].data == data("draft")


async def test_switch_current_keeps_previous_and_draft_rows_and_configuration(store):
    async_engine, _ = store
    async with AsyncSession(async_engine, expire_on_commit=False) as session, session.begin():
        root = await WorkflowVersionRepository.alock_root(session, "wf", 101)
        await WorkflowVersionRepository.aswitch_current(session, root, 2)
        versions = await WorkflowVersionRepository.alist_versions(session, root)
        assert [(version.id, version.is_current, version.data) for version in versions] == [
            (1, 0, data("v0")),
            (2, 1, data("draft")),
        ]


async def test_all_version_mutations_use_the_same_real_root_lock(store, monkeypatch):
    async_engine, _ = store
    injected = []

    def actual_sql(connection, cursor, statement, parameters, context, executemany):
        if re.search(r"\bFROM flow\b", statement):
            injected.append((statement, parameters))

    sa.event.listen(async_engine.sync_engine, "before_cursor_execute", actual_sql)
    async with AsyncSession(async_engine, expire_on_commit=False) as session, session.begin():
        statements = []
        execute = session.execute

        async def capture(statement, *args, **kwargs):
            if getattr(statement, "_for_update_arg", None) is not None:
                statements.append(
                    str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
                )
            return await execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", capture)
        for version_id in (1, 2):
            root = await WorkflowVersionRepository.alock_root(session, "wf", 101)
            await WorkflowVersionRepository.aget_version(session, root, version_id)
        assert len(statements) == 2
        assert all("flow.id = 'wf'" in statement for statement in statements)
        # C3 adds the tenant predicate at execution, not in this Repository's
        # authored SELECT. Lock identity and final SQL isolation are both kept.
        assert all("flow.tenant_id =" not in statement for statement in statements)
        assert all("FOR UPDATE" in statement for statement in statements)
    sa.event.remove(async_engine.sync_engine, "before_cursor_execute", actual_sql)
    assert len(injected) == 2
    assert all("flow.tenant_id = ?" in statement and 101 in parameters for statement, parameters in injected)


async def test_root_and_version_reads_reject_cross_tenant_or_deleted_identity(store):
    async_engine, _ = store
    async with AsyncSession(async_engine) as session:
        with pytest.raises(NotFoundError):
            await WorkflowVersionRepository.alock_root(session, "other", 101)
        root = await WorkflowVersionRepository.alock_root(session, "wf", 101)
        with pytest.raises(NotFoundError):
            await WorkflowVersionRepository.aget_version(session, root, 3)
        assert (await WorkflowVersionRepository.aget_version(session, root, 3, include_deleted=True)).id == 3
        with pytest.raises(CurVersionDelError):
            await WorkflowVersionRepository.asoft_delete_version(session, root, 1)


async def test_old_self_committing_dao_caller_remains_compatible(store):
    _, sync_engine = store
    created = FlowDao.create_flow(
        Flow(id="legacy", name="legacy", user_id=11, tenant_id=101, data=data("legacy")), FlowType.WORKFLOW.value
    )
    assert created.id == "legacy"
    with Session(sync_engine) as session:
        assert session.get(Flow, "legacy").is_delete == 0
        versions = session.exec(sa.select(FlowVersion).where(FlowVersion.flow_id == "legacy")).all()
        assert len(versions) == 1 and versions[0][0].is_current == 1


async def test_workflow_name_lookup_keeps_user_tenant_type_and_live_scope(store):
    async_engine, _ = store
    async with AsyncSession(async_engine) as session, session.begin():
        session.add_all(
            [
                Flow(id="assistant", name="assistant-only", user_id=11, tenant_id=101, flow_type=5),
                Flow(id="gone", name="deleted-only", user_id=11, tenant_id=101, is_delete=1),
                Flow(id="other-user", name="other-user-only", user_id=12, tenant_id=101),
            ]
        )
        await session.flush()
        lookup = WorkflowVersionRepository.aget_root_by_name
        assert (await lookup(session, 101, 11, "workflow")).id == "wf"
        for tenant_id, user_id, name in (
            (101, 11, "assistant-only"),
            (101, 11, "deleted-only"),
            (101, 11, "other-user-only"),
            (101, 21, "other tenant"),
            (202, 11, "workflow"),
        ):
            assert await lookup(session, tenant_id, user_id, name) is None


async def test_version_name_lookup_keeps_root_tenant_and_live_scope(store):
    async_engine, _ = store
    async with AsyncSession(async_engine) as session, session.begin():
        root = await WorkflowVersionRepository.alock_root(session, "wf", 101)
        lookup = WorkflowVersionRepository.aget_version_by_name
        assert (await lookup(session, root, "draft")).id == 2
        assert await lookup(session, root, "deleted") is None
        assert await lookup(session, root, "missing") is None
        session.add(FlowVersion(flow_id="wf", name="foreign-tenant", tenant_id=202))
        await session.flush()
        assert await lookup(session, root, "foreign-tenant") is None


async def test_version_and_version_list_support_explicit_current_locking_reads(store, monkeypatch):
    async_engine, _ = store
    async with AsyncSession(async_engine) as session, session.begin():
        root = await WorkflowVersionRepository.alock_root(session, "wf", 101)
        statements = []
        scalar, scalars = session.scalar, session.scalars

        async def capture_scalar(statement, *args, **kwargs):
            statements.append(statement)
            return await scalar(statement, *args, **kwargs)

        async def capture_scalars(statement, *args, **kwargs):
            statements.append(statement)
            return await scalars(statement, *args, **kwargs)

        monkeypatch.setattr(session, "scalar", capture_scalar)
        monkeypatch.setattr(session, "scalars", capture_scalars)
        await WorkflowVersionRepository.aget_version(session, root, 1)
        await WorkflowVersionRepository.alist_versions(session, root)
        await WorkflowVersionRepository.aget_version(session, root, 1, for_update=True)
        await WorkflowVersionRepository.alist_versions(session, root, for_update=True)
        assert [getattr(statement, "_for_update_arg", None) is not None for statement in statements] == [
            False,
            False,
            True,
            True,
        ]
        assert all("FOR UPDATE" in str(statement.compile(dialect=mysql.dialect())) for statement in statements[-2:])


async def test_all_repository_selects_delegate_tenant_isolation_to_real_listener(store, monkeypatch):
    async_engine, _ = store
    authored, executed = [], []
    token = set_visible_tenant_ids(frozenset({101, 202}))

    def actual_sql(connection, cursor, statement, parameters, context, executemany):
        if re.search(r"\bFROM (flow|flowversion)\b", statement):
            executed.append((statement, parameters))

    sa.event.listen(async_engine.sync_engine, "before_cursor_execute", actual_sql)
    try:
        async with AsyncSession(async_engine) as session:
            scalar, scalars, execute = session.scalar, session.scalars, session.execute

            async def capture_scalar(statement, *args, **kwargs):
                authored.append(str(statement.whereclause))
                return await scalar(statement, *args, **kwargs)

            async def capture_scalars(statement, *args, **kwargs):
                authored.append(str(statement.whereclause))
                return await scalars(statement, *args, **kwargs)

            async def capture_execute(statement, *args, **kwargs):
                authored.append(str(statement.whereclause))
                return await execute(statement, *args, **kwargs)

            monkeypatch.setattr(session, "scalar", capture_scalar)
            monkeypatch.setattr(session, "scalars", capture_scalars)
            monkeypatch.setattr(session, "execute", capture_execute)
            root = await WorkflowVersionRepository.aget_root(session, "wf", 101)
            assert await WorkflowVersionRepository.aget_root_by_name(session, 101, 11, "workflow") is root
            assert await WorkflowVersionRepository.alock_root(session, "wf", 101) is root
            assert (await WorkflowVersionRepository.aget_version(session, root, 1)).id == 1
            assert [row.id for row in await WorkflowVersionRepository.alist_versions(session, root)] == [1, 2]
            assert (await WorkflowVersionRepository.aget_version_by_name(session, root, "draft")).id == 2
            with pytest.raises(NotFoundError):
                await WorkflowVersionRepository.aget_root(session, "other", 101)
            assert authored and all("tenant_id" not in clause for clause in authored)
        assert executed and all(re.search(r"\b(?:flow|flowversion)\.tenant_id = \?", sql) for sql, _ in executed)
        assert all(101 in parameters and 202 not in parameters for _, parameters in executed)
    finally:
        sa.event.remove(async_engine.sync_engine, "before_cursor_execute", actual_sql)
        visible_tenant_ids.reset(token)


@pytest.mark.parametrize("operation", ["root", "lock", "name", "version", "versions", "version_name", "create"])
async def test_repository_does_not_accept_a_tenant_bypass_for_workflow_operations(store, operation):
    async_engine, sync_engine = store
    before = snapshot(sync_engine)
    async with AsyncSession(async_engine) as session:
        root = await WorkflowVersionRepository.aget_root(session, "wf", 101)
        with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
            if operation == "root":
                await WorkflowVersionRepository.aget_root(session, "wf", 101)
            elif operation == "lock":
                await WorkflowVersionRepository.alock_root(session, "wf", 101)
            elif operation == "name":
                await WorkflowVersionRepository.aget_root_by_name(session, 101, 11, "workflow")
            elif operation == "version":
                await WorkflowVersionRepository.aget_version(session, root, 1)
            elif operation == "versions":
                await WorkflowVersionRepository.alist_versions(session, root)
            elif operation == "version_name":
                await WorkflowVersionRepository.aget_version_by_name(session, root, "draft")
            else:
                await WorkflowVersionRepository.acreate_workflow(
                    session, Flow(id="bypass-new", name="bypass", user_id=11, tenant_id=101)
                )
    assert snapshot(sync_engine) == before


@pytest.mark.parametrize("supplied_tenant", [101, 202])
async def test_repository_requires_context_and_refuses_a_different_explicit_pin(store, supplied_tenant):
    async_engine, _ = store
    token = current_tenant_id.set(None if supplied_tenant == 101 else 101)
    try:
        async with AsyncSession(async_engine) as session:
            with pytest.raises(ResourceReferenceInvalidError):
                await WorkflowVersionRepository.aget_root(session, "wf", supplied_tenant)
    finally:
        current_tenant_id.reset(token)


async def test_tracked_root_from_a_different_owner_cannot_drive_version_queries(store):
    async_engine, _ = store
    async with AsyncSession(async_engine) as session:
        with bypass_tenant_filter():
            foreign = await session.get(Flow, "other")
        assert foreign.tenant_id == 202
        with pytest.raises(ResourceReferenceInvalidError):
            await WorkflowVersionRepository.alist_versions(session, foreign)
