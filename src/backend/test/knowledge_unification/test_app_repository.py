"""External APP transactions and real tenant facts. 覆盖 AC: AC-37, AC-68, AC-87, AC-89."""

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession
from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
from bisheng.app_publish.domain.repositories.reference_source_repository import HostedAppReferenceSourceRepository
from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding, RuntimeOperation, RuntimeRoute
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.open_api.domain.models.api_credential import ApiCredential


@pytest.fixture(autouse=True)
def tenant():
    token = set_current_tenant_id(101)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def version(version_id, app_id="app", number=1, **changes):
    return dict(
        id=version_id,
        app_id=app_id,
        version_no=number,
        kind="initial",
        code_object_key="snapshot",
        tier_id="light",
        runtime="python3.11",
        manifest={"original": " text "},
        capabilities={},
        **changes,
    )


@pytest.fixture
async def store(tmp_path, monkeypatch):
    models = (
        App,
        AppVersion,
        HostedAppSubject,
        ApiCredential,
        AppPreviewSession,
        RuntimeRoute,
        RuntimeCredentialBinding,
        RuntimeOperation,
        Knowledge,
    )
    names = tenant_filter._tenant_aware_tables | {
        model.__tablename__ for model in models if "tenant_id" in model.__table__.c
    }
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()
    path = tmp_path / "app.db"
    sync = sa.create_engine(f"sqlite:///{path}")
    metadata = sa.MetaData()
    for model in models:
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    col.name,
                    col.type.copy(),
                    primary_key=col.primary_key,
                    nullable=col.nullable,
                    server_default=sa.text("CURRENT_TIMESTAMP")
                    if col.name in {"create_time", "update_time"}
                    else col.server_default,
                )
                for col in model.__table__.columns
            ],
        )
    metadata.create_all(sync)
    with Session(sync) as session, bypass_tenant_filter():
        for key, tenant_id in (("app", 101), ("foreign", 202), ("root", 1)):
            session.add(
                App(
                    id=key,
                    slug=key,
                    name=key,
                    owner_user_id=11,
                    tenant_id=tenant_id,
                    state="stopped",
                    current_version_id="v1",
                )
            )
        for values in (
            version("v1"),
            version("history", number=2, terminal_state="rejected"),
            version("foreign-v", "foreign"),
        ):
            session.add(AppVersion(**values))
        session.add(HostedAppSubject(id=7, app_id="app"))
        session.add(
            ApiCredential(
                id=8,
                tenant_id=101,
                subject_kind="hosted_app",
                subject_id=7,
                name="runtime",
                key_prefix="bs-app-",
                last4="test",
                token_hash="0" * 64,
                scopes=["model:invoke", "knowledge:read"],
            )
        )
        session.add(
            AppPreviewSession(
                id="preview",
                tenant_id=101,
                app_id="app",
                version_id="history",
                approver_user_id=22,
                purpose="approval",
                credential_id=8,
                operation_id="operation",
                status="running",
                expires_at=datetime.utcnow() + timedelta(days=1),
            )
        )
        session.commit()
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    yield engine, sync
    await engine.dispose()
    sync.dispose()


async def test_parent_anchor_uuid_inventory_and_no_managed_orm(store):
    engine, _ = store
    async with AsyncSession(engine) as session, session.begin():
        repo = HostedAppReferenceSourceRepository()
        root = await repo.aget_root(session, "app")
        assert root["tenant_id"] == 101
        assert [row["id"] for row in await repo.alist_versions(session, root)] == ["history", "v1"]
        assert (await repo.aget_version(session, root, "history"))["terminal_state"] == "rejected"
        assert await repo.aget_version(session, root, "foreign-v") is None
        assert not session.identity_map and not session.dirty


@pytest.mark.parametrize("app_id", ["root", "foreign"])
async def test_current_tenant_is_not_expanded_by_root_visibility(store, app_id):
    engine, _ = store
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises(AppNotFoundError):
            await HostedAppReferenceSourceRepository().aget_root(session, app_id)


async def test_no_transaction_and_bypass_are_rejected(store):
    engine, _ = store
    async with AsyncSession(engine) as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await HostedAppReferenceSourceRepository().aget_root(session, "app")
        async with session.begin():
            with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
                await HostedAppReferenceSourceRepository().aget_root(session, "app")


async def test_version_insert_and_root_delete_are_owned_by_outer_transaction(store):
    engine, _ = store
    async with AsyncSession(engine) as session:
        async with session.begin():
            repo = HostedAppReferenceSourceRepository()
            root = await repo.aget_root(session, "app", for_update=True)
            assert await repo.amax_version_no(session, root) == 2
            await repo.ainsert_version(session, root, version("new", number=3))
            await repo.aset_deleted(session, root)
            await session.rollback()
        async with session.begin():
            root = await repo.aget_root(session, "app")
            assert root["state"] == "stopped"
            assert await repo.aget_version(session, root, "new") is None


async def test_current_reads_lock_root_version_and_identity_without_secret_material(store):
    engine, _ = store
    statements = []

    def capture(state):
        if state.is_select:
            statements.append(state.statement)

    sa.event.listen(Session, "do_orm_execute", capture)
    try:
        async with AsyncSession(engine) as session, session.begin():
            repo = HostedAppReferenceSourceRepository()
            root = await repo.aget_root(session, "app", for_update=True)
            await repo.aget_version(session, root, "v1", for_update=True)
            facts = await repo.aget_runtime_identity(session, root, 8, for_update=True)
            assert facts["credential"]["subject_id"] == 7
            assert facts["subject"]["app_id"] == "app"
            assert facts["preview"]["version_id"] == "history"
            assert "token_hash" not in facts["credential"]
            assert not session.identity_map
        assert len(statements) >= 6 and all(statement._for_update_arg is not None for statement in statements)
    finally:
        sa.event.remove(Session, "do_orm_execute", capture)


async def test_preview_route_and_operation_are_exact_same_session_current_facts(store):
    engine, _ = store
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            RuntimeOperation(
                id="operation",
                tenant_id=101,
                app_id="app",
                scope_key="101/app",
                idempotency_key="preview",
                request_digest="0" * 64,
                version_id="history",
                kind="preview",
                node_id="node",
                generation=3,
                owner_epoch=4,
                deadline=datetime.utcnow() + timedelta(hours=1),
                payload={"session_id": "preview"},
            )
        )
        session.add(
            RuntimeRoute(
                id="preview-route",
                tenant_id=101,
                app_id="app",
                operation_id="operation",
                route_key="preview:preview",
                version_id="history",
                node_id="node",
                exec_ref="preview-execution",
                generation=3,
                owner_epoch=4,
                status="serving",
            )
        )
        await session.flush()
        repo = HostedAppReferenceSourceRepository()
        root = await repo.aget_root(session, "app")
        facts = await repo.aget_runtime_identity(session, root, 8, for_update=True)
        assert facts["route"] is None
        assert (
            facts["preview_route"]["operation_id"],
            facts["preview_route"]["version_id"],
            facts["preview_route"]["generation"],
            facts["preview_route"]["owner_epoch"],
        ) == ("operation", "history", 3, 4)
        assert facts["operation"]["payload"] == {"session_id": "preview"}
