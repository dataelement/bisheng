"""Behavioral regression tests using real SQL, without external middleware."""

from contextlib import asynccontextmanager, contextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models import flow as module
from bisheng.database.models import flow_version as versions
from bisheng.database.models.app import App
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.flow import Flow, FlowDao, FlowType
from bisheng.database.models.flow_version import FlowVersion, FlowVersionDao


@pytest.fixture(autouse=True)
def scoped_tenant():
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    token = set_current_tenant_id(1)
    yield
    current_tenant_id.reset(token)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    path = tmp_path / "flows.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    metadata = sa.MetaData()
    for model in (Flow, FlowVersion, Assistant, App):
        columns = []
        for col in model.__table__.columns:
            default = col.server_default
            if col.name in {"create_time", "update_time"}:
                default = sa.text("CURRENT_TIMESTAMP")
            columns.append(
                sa.Column(
                    col.name,
                    col.type.copy(),
                    primary_key=col.primary_key,
                    nullable=col.nullable,
                    server_default=default,
                )
            )
        if model is Flow and "is_delete" not in model.__table__.columns:
            columns.append(sa.Column("is_delete", sa.Integer, server_default="0", nullable=False))
        sa.Table(model.__tablename__, metadata, *columns)
    metadata.create_all(engine)
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    @contextmanager
    def sync_session():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            yield session

    for target in (module, versions):
        monkeypatch.setattr(target, "get_sync_db_session", sync_session)
        monkeypatch.setattr(target, "get_async_db_session", async_session)
    with Session(engine) as session:
        session.add(Flow(id="live", name="live", user_id=1, tenant_id=1, data={"nodes": [], "edges": []}))
        session.add(Flow(id="gone", name="gone", user_id=1, tenant_id=1, data={"nodes": [], "edges": []}))
        session.add(
            FlowVersion(
                id=1, flow_id="live", name="v0", user_id=1, is_current=1, data={"nodes": [], "edges": []}, tenant_id=1
            )
        )
        session.commit()
        session.exec(sa.text("UPDATE flow SET is_delete=1 WHERE id='gone'"))
        session.commit()
    yield engine
    await async_engine.dispose()
    engine.dispose()


async def test_delete_retains_definition_and_marks_versions(store):
    original = FlowDao.get_flow_by_id("live")
    FlowDao.delete_flow(original)
    with Session(store) as session:
        kept = session.get(Flow, "live")
        assert kept is not None
        assert kept.data == {"nodes": [], "edges": []}
        assert kept.is_delete == 1
        assert session.get(FlowVersion, 1).is_delete == 1
    assert FlowDao.get_flow_by_id("live") is None


@pytest.mark.parametrize(
    "lookup",
    [
        lambda: FlowDao.get_flow_by_id("gone"),
        lambda: FlowDao.get_flow_by_idstr("gone"),
        lambda: FlowDao.get_flow_by_name(1, "gone"),
        lambda: FlowDao.get_one_flow_simple_sync("gone"),
    ],
)
async def test_deleted_flow_is_absent_from_normal_lookup(store, lookup):
    assert lookup() is None


async def test_deleted_flow_excluded_from_lists_and_counts(store):
    assert [f.id for f in FlowDao.get_flow_by_ids(["live", "gone"])] == ["live"]
    assert [f.id for f in FlowDao.get_flow_by_user(1)] == ["live"]
    assert FlowDao.get_flow_list_by_name("gone") == []
    flows = FlowDao.get_flows(1, [], "", page=1, limit=1)
    assert [f.id for f in flows] == ["live"]
    assert FlowDao.count_flows(1, [], "") == 1
    flows, count = FlowDao.filter_flows_by_ids(["live", "gone"])
    assert [f.id for f in flows] == ["live"] and count == 1
    with Session(store) as session:
        ids = session.exec(select(FlowDao._build_apps_subquery().c.id)).all()
    assert ids == ["live"]


async def test_async_lookups_hide_deleted(store):
    assert await FlowDao.aget_flow_by_id("gone") is None
    assert await FlowDao.get_one_flow_simple("gone") is None
    assert [f.id for f in await FlowDao.aget_flow_by_ids(["gone", "live"])] == ["live"]


async def test_stale_save_does_not_revive_deleted_flow(store):
    stale = FlowDao.get_flow_by_id("live")
    FlowDao.delete_flow(FlowDao.get_flow_by_id("live"))
    stale.name = "changed"
    with pytest.raises(NotFoundError):
        FlowDao.update_flow(stale)
    with Session(store) as session:
        assert session.get(Flow, "live").is_delete == 1
        assert session.get(Flow, "live").name == "live"


async def test_deleted_parent_rejects_new_version(store):
    FlowDao.delete_flow(FlowDao.get_flow_by_id("live"))
    with pytest.raises(NotFoundError):
        FlowVersionDao.create_version(FlowVersion(flow_id="live", name="v1", tenant_id=1))
    with Session(store) as session:
        assert len(session.exec(select(FlowVersion)).all()) == 1


async def test_history_metadata_retains_deleted_name_but_not_definition(store, monkeypatch):
    from bisheng.workflow.domain.repositories import history_repository as history

    monkeypatch.setattr(history, "get_sync_db_session", module.get_sync_db_session)
    monkeypatch.setattr(history, "get_async_db_session", module.get_async_db_session)
    kept = history.WorkflowHistoryRepository.search_by_name("gone")[0]
    assert kept.name == "gone"
    assert not hasattr(kept, "data")
    assert [f.id for f in history.WorkflowHistoryRepository.search_by_name("gone")] == ["gone"]
    assert [f.id for f in await history.WorkflowHistoryRepository.aget_by_ids(["gone"])] == ["gone"]


async def test_template_cannot_use_deleted_workflow(store, monkeypatch):
    from bisheng.app_template.domain.repositories import template_repository as repo

    monkeypatch.setattr(repo, "get_async_db_session", module.get_async_db_session)
    assert await repo.TemplateRepository.source("gone", 10) is None
    assert (await repo.TemplateRepository.source("live", 10))["id"] == "live"


async def test_deleted_parent_rejects_version_mutation(store):
    stale_version = FlowVersionDao.get_version_by_id(1)
    FlowDao.delete_flow(FlowDao.get_flow_by_id("live"))
    stale_version.data = {"nodes": [{"id": "changed"}], "edges": []}
    with pytest.raises(NotFoundError):
        await FlowVersionDao.aupdate_version(stale_version)
    assert await FlowVersionDao.change_current_version("live", stale_version) is False
    with Session(store) as session:
        assert session.get(FlowVersion, 1).is_delete == 1
        assert session.get(Flow, "live").data == {"nodes": [], "edges": []}


async def test_async_stale_save_does_not_revive(store):
    stale = await FlowDao.aget_flow_by_id("live")
    FlowDao.delete_flow(FlowDao.get_flow_by_id("live"))
    with pytest.raises(NotFoundError):
        await FlowDao.aupdate_flow(stale)


async def test_other_flow_type_keeps_physical_deletion(store):
    with Session(store) as session:
        session.add(Flow(id="other", name="other", tenant_id=1, flow_type=FlowType.LINSIGHT.value))
        session.commit()
    FlowDao.delete_flow(FlowDao.get_flow_by_id("other"))
    with Session(store) as session:
        assert session.get(Flow, "other") is None


async def test_detail_does_not_expose_internal_delete_marker(store, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.api.services import flow as service

    monkeypatch.setattr(service, "check_business_action", AsyncMock(return_value=True))
    monkeypatch.setattr(service.FlowService, "get_logo_share_link_async", AsyncMock(return_value=None))
    result = await service.FlowService.get_one_flow(object(), "live")
    assert result.data["id"] == "live"
    assert "is_delete" not in result.data


async def test_delete_rolls_back_parent_when_version_update_fails(store):
    def reject_version_update(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE FLOWVERSION"):
            raise RuntimeError("version write failed")

    sa.event.listen(store, "before_cursor_execute", reject_version_update)
    try:
        with pytest.raises(RuntimeError, match="version write failed"):
            FlowDao.delete_flow(FlowDao.get_flow_by_id("live"))
    finally:
        sa.event.remove(store, "before_cursor_execute", reject_version_update)
    with Session(store) as session:
        assert session.get(Flow, "live").is_delete == 0
        assert session.get(FlowVersion, 1).is_delete == 0


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_live_parent_can_restore_individually_deleted_version(store, asynchronous):
    with Session(store) as session:
        session.exec(sa.update(FlowVersion).where(FlowVersion.id == 1).values(is_delete=1))
        session.commit()
    version = FlowVersionDao.get_version_by_id(1, include_delete=True)
    version.is_delete = 0
    if asynchronous:
        restored = await FlowVersionDao.aupdate_version(version)
    else:
        restored = FlowVersionDao.update_version(version)
    assert restored.is_delete == 0
    assert FlowVersionDao.get_version_by_id(1) is not None


@pytest.mark.parametrize("permission_allowed", [True, False])
async def test_delete_endpoint_preserves_auth_order_and_final_state(store, monkeypatch, permission_allowed):
    """AC-01/AC-05/AC-09/AC-11: real endpoint and SQL, external boundaries stubbed."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from bisheng.api.services import flow as service
    from bisheng.api.v1 import flows as endpoint
    from bisheng.common.errcode.http_error import UnAuthorizedError
    from bisheng.resource_reference.application.contracts import SourceKey
    from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
    from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
    from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
    from bisheng.workflow.domain.repositories.workflow_version_repository import WorkflowVersionRepository
    from bisheng.workflow.domain.services.reference_extractor import WORKFLOW_REFERENCE_EXTRACTOR_VERSION
    from test.knowledge_unification.test_ref_repo import TABLES

    for table in TABLES:
        table.create(store)
    async_engine = create_async_engine(str(store.url).replace("sqlite:", "sqlite+aiosqlite:"))

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            yield session

    # The real live definition has zero targets. No target Owner or receipt is
    # fabricated; this fixture models its already-completed upgrade indexing.
    verifier = ReferenceTargetVerifier({})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    async with session_factory() as session, session.begin():
        prepared = await runtime.aprepare_source_bindings(
            session,
            SourceKey(1, "workflow_version", "live", "1"),
            (),
            extractor_version=WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lambda sql: WorkflowVersionRepository.alock_root(sql, "live", 1),
            new_source=True,
        )
        await runtime.aapply_source_bindings(session, prepared)

    events = []

    async def authorize(*args, **kwargs):
        events.append("authorize")
        if not permission_allowed:
            raise UnAuthorizedError()

    async def project_existing(*args):
        events.append("project")
        assert FlowDao.get_flow_by_id("live") is not None

    def cleanup_committed(*args):
        events.append("cleanup")
        assert FlowDao.get_flow_by_id("live") is None

    project = AsyncMock(side_effect=project_existing)
    cleanup = Mock(side_effect=cleanup_committed)
    monkeypatch.setattr(service, "get_async_db_session", session_factory)
    monkeypatch.setattr(service, "get_reference_binding_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(service, "require_business_action", AsyncMock(side_effect=authorize))
    monkeypatch.setattr(service.FlowService, "project_flow_delete", project)
    monkeypatch.setattr(service.FlowService, "delete_flow_hook", cleanup)
    monkeypatch.setattr(service.telemetry_service, "log_event", AsyncMock())
    user = SimpleNamespace(user_id=1, tenant_id=1)
    try:
        if not permission_allowed:
            with pytest.raises(UnAuthorizedError):
                await endpoint.delete_flow(request=object(), flow_id="live", login_user=user)
            assert FlowDao.get_flow_by_id("live") is not None
            cleanup.assert_not_called()
            project.assert_not_awaited()
            assert events == ["authorize"]
            return
        result = await endpoint.delete_flow(request=object(), flow_id="live", login_user=user)
        assert result.status_code == 200
        assert FlowDao.get_flow_by_id("live") is None
        cleanup.assert_called_once()
        with Session(store) as session:
            assert session.get(Flow, "live").is_delete == 1
            assert session.get(FlowVersion, 1).is_delete == 1
        with pytest.raises(NotFoundError):
            await service.FlowService.get_one_flow(user, "live")
        with pytest.raises(NotFoundError):
            await endpoint.delete_flow(request=object(), flow_id="live", login_user=user)
        assert project.await_count == 1
        assert events == ["authorize", "project", "cleanup"]
    finally:
        await async_engine.dispose()


async def test_migration_defaults_existing_rows_and_is_idempotent(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(module.__file__).parents[2] / "core/database/alembic/versions/v3_1_0b1_f004_workflow_soft_delete.py"
    spec = importlib.util.spec_from_file_location("workflow_delete_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE flow (id VARCHAR(32) PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO flow (id) VALUES ('existing')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        monkeypatch.setattr(migration, "table_exists", lambda name: sa.inspect(connection).has_table(name))
        monkeypatch.setattr(
            migration,
            "column_exists",
            lambda table, name: name in {col["name"] for col in sa.inspect(connection).get_columns(table)},
        )
        migration.upgrade()
        migration.upgrade()
        assert connection.execute(sa.text("SELECT is_delete FROM flow")).scalar_one() == 0
        column = next(c for c in sa.inspect(connection).get_columns("flow") if c["name"] == "is_delete")
        assert column["nullable"] is False
        with pytest.raises(RuntimeError, match="retaining deletion filtering"):
            migration.downgrade()
    engine.dispose()
