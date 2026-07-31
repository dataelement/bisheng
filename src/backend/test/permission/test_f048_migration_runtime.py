"""Live-adapter contracts for the formal F048 migration runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.core.openfga.discovery import OpenFGARuntimePin
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionMigrationItem,
    PermissionMigrationRun,
    PermissionModel,
    PermissionModelAction,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.migration_repository import (
    MigrationRepository,
)
from bisheng.permission.migration import f048_runtime_storage
from bisheng.permission.migration.f048_runtime_source import (
    LiveMigrationSourceProvider,
)
from bisheng.permission.migration.f048_runtime_storage import (
    OpenFGAMigrationModelPublisher,
    SqlMigrationRunStore,
    SqlOpenFGAMigrationTargetWriter,
)
from bisheng.permission.migration.f048_runtime_verification import (
    LiveMigrationEvidenceProvider,
)
from bisheng.permission.migration.f048_source_inventory import (
    LegacyConfigSource,
    LegacyTupleSource,
    MigrationEnvironmentFacts,
    PermissionMigrationResourceDTO,
    SourceInventorySnapshot,
    build_source_inventory,
)
from scripts import f048_migration_runtime
from scripts.f048_migration_runtime import build_f048_migration_runtime


def _snapshot() -> SourceInventorySnapshot:
    return SourceInventorySnapshot(
        environment=MigrationEnvironmentFacts(
            schema_ready=True,
            services_stopped=True,
            active_heartbeats=0,
            expected_store_id="store-live",
            actual_store_id="store-live",
            source_model_id="legacy-model",
            source_watermark="watermark",
            observed_watermark="watermark",
        ),
        config_sources=(
            LegacyConfigSource(
                key="permission_relation_models_v1",
                row_version="7",
                raw_value='[{"id":"legacy-owner","permissions":[]}]',
            ),
        ),
        resources=(
            PermissionMigrationResourceDTO(
                tenant_id=7,
                resource_type="workflow",
                resource_id="wf-1",
                status="ONLINE",
                owner_user_id=11,
                ownership_kind="USER",
                source_locator="workflow:wf-1",
            ),
        ),
        tuples=(
            LegacyTupleSource(
                tenant_id=7,
                user="user:11",
                relation="owner",
                object="workflow:wf-1",
            ),
        ),
    )


class _MemoryMigrationRepository:
    def __init__(self) -> None:
        self.run = PermissionMigrationRun(
            id=1,
            environment_fingerprint="e" * 64,
            phase="SOURCE_VALIDATING",
            status="RUNNING",
            store_id="store-live",
            source_model_id="legacy-model",
            target_model_id=None,
            source_watermark="watermark",
            source_checksum=build_source_inventory(_snapshot()).checksum,
            version=3,
        )
        self.items = []

    async def aget_run(self, run_id: int):
        return self.run if run_id == 1 else None

    async def aupsert_items(self, items):
        self.items.extend(items)
        return list(items)

    async def alist_source_items(self, *, run_id: int):
        assert run_id == 1
        return list(self.items)


async def test_sql_run_store_rebuilds_complete_frozen_source_payload():
    repository = _MemoryMigrationRepository()
    store = SqlMigrationRunStore(repository=repository)
    inventory = build_source_inventory(_snapshot())

    await store.aput_source_items(run_id=1, items=inventory.items)
    restored = await store.aload_source_snapshot(run_id=1)

    assert build_source_inventory(restored).checksum == inventory.checksum
    assert restored.config_sources[0].raw_value == ('[{"id":"legacy-owner","permissions":[]}]')
    assert restored.resources == _snapshot().resources
    assert restored.tuples == _snapshot().tuples


class _NoopDashboardRepository:
    def __init__(self) -> None:
        self.backfill_calls = 0

    async def abackfill_custom_dashboard_tenants(self) -> int:
        self.backfill_calls += 1
        return 0


class _NoopSourceClient:
    store_id = "store-live"
    model_id = "legacy-model"

    async def read_tuples(self):
        raise AssertionError("precondition failure must not scan OpenFGA")


async def test_live_source_provider_short_circuits_before_business_scan(
    monkeypatch,
):
    dashboard = _NoopDashboardRepository()
    provider = LiveMigrationSourceProvider(
        source_client=_NoopSourceClient(),
        actual_store_id="store-live",
        source_model_id="legacy-model",
        sources=(),
        dashboard_repository=dashboard,
    )

    async def schema_not_ready():
        return False

    async def no_heartbeats():
        return 0

    monkeypatch.setattr(provider, "_schema_ready", schema_not_ready)
    monkeypatch.setattr(provider, "_active_heartbeats", no_heartbeats)
    snapshot = await provider.aload_snapshot(expected_store_id="store-live")

    assert snapshot.environment.schema_ready is False
    assert snapshot.resources == ()
    assert dashboard.backfill_calls == 0


async def test_live_source_provider_needs_no_manual_stop_ack_without_ready_heartbeats(
    monkeypatch,
):
    dashboard = _NoopDashboardRepository()
    provider = LiveMigrationSourceProvider(
        source_client=_NoopSourceClient(),
        actual_store_id="store-live",
        source_model_id="legacy-model",
        sources=(),
        dashboard_repository=dashboard,
    )
    empty_sources = {
        "configs": (),
        "resources": (),
        "tuples": (),
        "failed_tuples": (),
    }

    async def schema_ready():
        return True

    async def no_heartbeats():
        return 0

    async def load_sources():
        return empty_sources

    monkeypatch.delenv("F048_SERVICES_STOPPED", raising=False)
    monkeypatch.setattr(provider, "_schema_ready", schema_ready)
    monkeypatch.setattr(provider, "_active_heartbeats", no_heartbeats)
    monkeypatch.setattr(provider, "_load_sources", load_sources)

    snapshot = await provider.aload_snapshot(expected_store_id="store-live")

    assert snapshot.environment.services_stopped is True
    assert snapshot.environment.active_heartbeats == 0
    assert snapshot.environment.source_watermark == snapshot.environment.observed_watermark
    assert dashboard.backfill_calls == 1


def test_failed_tuple_reconciliation_uses_final_store_state():
    identity = ("user:11", "owner", "workflow:wf-1")
    resource_keys = {"workflow:wf-1"}

    assert (
        LiveMigrationSourceProvider._failed_tuple_resolution(
            status="dead",
            action="write",
            tuple_identity=identity,
            error_category="TRANSIENT_TRANSPORT_FAILURE",
            canonical_state=None,
            resource_keys=resource_keys,
            store_tuples={identity},
        )
        == "STORE_STATE_MATCHES"
    )
    assert (
        LiveMigrationSourceProvider._failed_tuple_resolution(
            status="dead",
            action="delete",
            tuple_identity=identity,
            error_category="TRANSIENT_TRANSPORT_FAILURE",
            canonical_state=None,
            resource_keys=resource_keys,
            store_tuples=set(),
        )
        == "STORE_STATE_MATCHES"
    )


def test_failed_tuple_reconciliation_only_auto_resolves_proven_outcomes():
    identity = ("user:11", "owner", "linsight_skill:skill-1")
    values = {
        "status": "dead",
        "action": "write",
        "tuple_identity": identity,
        "canonical_state": None,
        "resource_keys": set(),
        "store_tuples": set(),
    }

    assert (
        LiveMigrationSourceProvider._failed_tuple_resolution(
            **values,
            error_category="MODEL_VALIDATION_REJECTED",
        )
        == "SOURCE_MODEL_REJECTED"
    )
    assert (
        LiveMigrationSourceProvider._failed_tuple_resolution(
            **values,
            error_category="TRANSIENT_TRANSPORT_FAILURE",
        )
        is None
    )
    assert (
        LiveMigrationSourceProvider._failed_tuple_resolution(
            **{
                **values,
                "tuple_identity": ("user:11", "owner", "workflow:deleted"),
            },
            error_category="TRANSIENT_TRANSPORT_FAILURE",
        )
        == "RESOURCE_ABSENT"
    )
    assert (
        LiveMigrationSourceProvider._failed_tuple_resolution(
            **{**values, "canonical_state": True},
            error_category="TRANSIENT_TRANSPORT_FAILURE",
        )
        == "CANONICAL_IDENTITY_STATE"
    )


class _PublisherSourceClient:
    store_id = "store-live"

    def __init__(self, model: dict) -> None:
        self.model = model
        self.write_calls = 0

    async def list_authorization_models(self):
        return [{"id": "remote-model", **self.model}]

    async def write_authorization_model(self, model):
        self.write_calls += 1
        return "written-model"


async def test_model_publisher_reuses_matching_same_store_model(monkeypatch):
    model = build_authorization_model_f048()
    source_client = _PublisherSourceClient(model)
    publisher = OpenFGAMigrationModelPublisher(
        source_client=source_client,
        environment="test",
        predecessor_model_id="legacy-model",
    )
    persisted = []

    async def no_sql_release(store_id, checksum):
        return None

    async def persist_release(**kwargs):
        persisted.append(kwargs)

    monkeypatch.setattr(publisher, "_find_sql_release", no_sql_release)
    monkeypatch.setattr(publisher, "_persist_release", persist_release)

    model_id = await publisher.aget_or_publish(
        store_id="store-live",
        model=model,
        checksum=authorization_model_checksum(model),
    )

    assert model_id == "remote-model"
    assert source_client.write_calls == 0
    assert persisted[0]["model_id"] == "remote-model"


class _EvidenceModelClient:
    def __init__(self, model: dict) -> None:
        self.model = model

    async def list_authorization_models(self):
        return [{"id": "remote-model", **self.model}]


async def test_evidence_provider_checks_canonical_remote_model() -> None:
    model = build_authorization_model_f048()
    response_model = deepcopy(model)
    response_model["type_definitions"][1]["metadata"].update(
        module="",
        source_info=None,
    )
    provider = LiveMigrationEvidenceProvider(
        source_client=_EvidenceModelClient(response_model),
        target_writer=SimpleNamespace(),
    )

    assert await provider._remote_model_checksum("remote-model") == authorization_model_checksum(model)
    assert await provider._remote_model_checksum("missing-model") is None


class _TargetClient:
    def __init__(self) -> None:
        self.writes = []

    async def write_tuples(self, *, writes):
        self.writes.append(tuple(writes))


class _TupleSourceClient:
    store_id = "store-live"

    def __init__(self) -> None:
        self.target = _TargetClient()

    async def read_tuples(self):
        return [
            {
                "user": "user:1",
                "relation": "owner",
                "object": "workflow:existing",
            }
        ]

    def for_model(self, model_id):
        assert model_id == "new-model"
        return self.target


async def test_target_writer_filters_existing_tuples_across_resume(
    monkeypatch,
):
    source_client = _TupleSourceClient()
    writer = SqlOpenFGAMigrationTargetWriter(source_client=source_client)
    persisted = []

    async def persist_target_items(*, idempotency_key, tuples):
        persisted.append((idempotency_key, tuples))

    monkeypatch.setattr(
        SqlOpenFGAMigrationTargetWriter,
        "_persist_target_tuple_items",
        staticmethod(persist_target_items),
    )
    rows = (
        {
            "user": "user:1",
            "relation": "owner",
            "object": "workflow:existing",
        },
        {
            "user": "user:2",
            "relation": "owner",
            "object": "workflow:new",
        },
    )

    await writer.awrite_target_tuples(
        store_id="store-live",
        model_id="new-model",
        tuples=rows,
        idempotency_key="f048:1:target:0",
    )
    await writer.awrite_target_tuples(
        store_id="store-live",
        model_id="new-model",
        tuples=rows,
        idempotency_key="f048:1:target:0",
    )

    assert source_client.target.writes == [(rows[1],)]
    assert len(persisted) == 2


async def test_runtime_builder_discovers_store_and_source_model(
    monkeypatch,
):
    config = SimpleNamespace(
        enabled=True,
        api_url="http://openfga:8080",
        store_name="bisheng",
        timeout=5,
        force_write_model=False,
    )
    live_settings = SimpleNamespace(
        openfga=config,
        environment="test",
    )

    async def discover(*args, **kwargs):
        return OpenFGARuntimePin(
            store_id="store-live",
            model_id="legacy-model",
            model_checksum="a" * 64,
        )

    monkeypatch.setattr(
        f048_migration_runtime,
        "discover_openfga_runtime",
        discover,
    )
    runtime = await build_f048_migration_runtime(live_settings)
    try:
        assert runtime.source_client.store_id == "store-live"
        assert runtime.source_client.model_id == "legacy-model"
    finally:
        await runtime.aclose()


async def test_runtime_builder_resume_uses_durable_source_model(
    monkeypatch,
):
    config = SimpleNamespace(
        enabled=True,
        api_url="http://openfga:8080",
        store_name="bisheng",
        timeout=5,
        force_write_model=False,
    )
    live_settings = SimpleNamespace(
        openfga=config,
        environment="test",
    )
    discovered = []

    async def get_run(self, run_id):
        assert run_id == 9
        return SimpleNamespace(
            store_id="store-live",
            source_model_id="legacy-model",
        )

    async def discover(*args, **kwargs):
        discovered.append(kwargs)
        return OpenFGARuntimePin(
            store_id="store-live",
            model_id="legacy-model",
            model_checksum="a" * 64,
        )

    monkeypatch.setattr(SqlMigrationRunStore, "aget_run", get_run)
    monkeypatch.setattr(
        f048_migration_runtime,
        "discover_openfga_runtime",
        discover,
    )
    runtime = await build_f048_migration_runtime(
        live_settings,
        run_id=9,
    )
    try:
        assert discovered[0]["required_store_id"] == "store-live"
        assert discovered[0]["required_model_id"] == "legacy-model"
    finally:
        await runtime.aclose()


_CONTROL_TABLES = (
    "authorization_model_release",
    "permission_catalog_release",
    "permission_action",
    "permission_action_resource_scope",
    "permission_model",
    "permission_model_action",
    "permission_projection_operation",
    "permission_grant",
    "permission_grant_assignee",
    "resource_permission_mode",
)


async def _control_checksum(
    monkeypatch,
    *,
    id_offset: int,
) -> str:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = sa.MetaData()
    for name in _CONTROL_TABLES:
        SQLModel.metadata.tables[name].to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            engine,
            expire_on_commit=False,
        ) as session:
            yield session

    monkeypatch.setattr(
        f048_runtime_storage,
        "get_async_db_session",
        session_factory,
    )
    async with session_factory() as session:
        async with session.begin():
            authorization_release = AuthorizationModelRelease(
                id=id_offset + 1,
                environment="test",
                store_id="store-live",
                model_version="f048-v1",
                model_id="new-model",
                predecessor_model_id="legacy-model",
                model_checksum="a" * 64,
                required_relations_checksum="b" * 64,
                openfga_version="1.15.1",
                status="STAGED",
            )
            catalog = PermissionCatalogRelease(
                id=id_offset + 2,
                release_key="f048-initial",
                version=1,
                status="CURRENT",
                required_authorization_model_release_id=id_offset + 1,
                draft_owner_id=0,
                idempotency_key="f048-migration-1",
                checksum="c" * 64,
            )
            action = PermissionAction(
                id=id_offset + 3,
                catalog_release_id=id_offset + 2,
                code="download",
                name="download",
                level=1,
                active=True,
                sort_order=1,
            )
            model = PermissionModel(
                id=id_offset + 5,
                catalog_release_id=id_offset + 2,
                model_key="viewer",
                normalized_name="viewer",
                name="viewer",
                kind="STANDARD",
                config_scope="PLATFORM",
                derived_level=1,
                active=True,
                allow_same_level=False,
            )
            grant = PermissionGrant(
                id=id_offset + 7,
                tenant_id=7,
                resource_type="workflow",
                resource_id="wf-1",
                model_key="viewer",
                state="ACTIVE",
                projection_state="CURRENT",
            )
            session.add_all(
                (
                    authorization_release,
                    catalog,
                    action,
                    PermissionActionResourceScope(
                        id=id_offset + 4,
                        action_id=id_offset + 3,
                        resource_type="knowledge_file",
                    ),
                    model,
                    PermissionModelAction(
                        id=id_offset + 6,
                        model_id=id_offset + 5,
                        action_id=id_offset + 3,
                    ),
                    grant,
                    PermissionGrantAssignee(
                        id=id_offset + 8,
                        tenant_id=7,
                        grant_id=id_offset + 7,
                        subject_type="user",
                        subject_id="11",
                        source_type="DIRECT",
                        source_ref="legacy",
                        source_locator="migration:DIRECT:legacy",
                        source_fingerprint="d" * 64,
                        projected_subject="user:11",
                        protected=False,
                        state="ACTIVE",
                    ),
                    ResourcePermissionMode(
                        id=id_offset + 9,
                        tenant_id=7,
                        resource_type="workflow",
                        resource_id="wf-1",
                        mode="CUSTOM",
                        projection_state="CURRENT",
                    ),
                )
            )

    writer = SqlOpenFGAMigrationTargetWriter(source_client=SimpleNamespace(store_id="store-live"))
    checksum = await writer.acontrol_plane_checksum()
    await engine.dispose()
    return checksum


async def test_control_checksum_uses_logical_keys_not_database_sequences(
    monkeypatch,
):
    first = await _control_checksum(monkeypatch, id_offset=10)
    second = await _control_checksum(monkeypatch, id_offset=1000)

    assert first == second


async def test_d4_ready_transition_activates_only_target_release(
    monkeypatch,
):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = sa.MetaData()
    for name in (
        "authorization_model_release",
        "permission_migration_run",
        "permission_migration_item",
    ):
        table = SQLModel.metadata.tables[name].to_metadata(metadata)
        table.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            engine,
            expire_on_commit=False,
        ) as session:
            yield session

    monkeypatch.setattr(
        f048_runtime_storage,
        "get_async_db_session",
        session_factory,
    )
    async with session_factory() as session:
        async with session.begin():
            session.add_all(
                (
                    AuthorizationModelRelease(
                        id=1,
                        environment="test",
                        store_id="store-live",
                        model_version="legacy",
                        model_id="legacy-model",
                        model_checksum="1" * 64,
                        required_relations_checksum="2" * 64,
                        openfga_version="1.15.1",
                        status="ACTIVE",
                    ),
                    AuthorizationModelRelease(
                        id=2,
                        environment="test",
                        store_id="store-live",
                        model_version="f048-v1",
                        model_id="new-model",
                        predecessor_model_id="legacy-model",
                        model_checksum="3" * 64,
                        required_relations_checksum="4" * 64,
                        openfga_version="1.15.1",
                        status="STAGED",
                    ),
                    PermissionMigrationRun(
                        id=7,
                        environment_fingerprint="e" * 64,
                        phase="VERIFYING",
                        status="RUNNING",
                        store_id="store-live",
                        source_model_id="legacy-model",
                        target_model_id="new-model",
                        source_watermark="watermark",
                        source_checksum="s" * 64,
                        target_checksum="t" * 64,
                        version=4,
                    ),
                )
            )

    store = SqlMigrationRunStore(repository=MigrationRepository(session_factory))
    ready = await store.amark_ready(
        run_id=7,
        expected_version=4,
        evidence_checksum="r" * 64,
    )

    assert (ready.phase, ready.status, ready.version) == (
        "READY_TO_START",
        "COMPLETED",
        5,
    )
    async with session_factory() as session:
        releases = list(
            (await session.execute(sa.select(AuthorizationModelRelease).order_by(AuthorizationModelRelease.id)))
            .scalars()
            .all()
        )
    assert [(row.model_id, row.status) for row in releases] == [
        ("legacy-model", "RETIRED"),
        ("new-model", "ACTIVE"),
    ]
    await engine.dispose()


async def test_blocked_source_reset_replaces_only_pre_target_snapshot(
    monkeypatch,
):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = sa.MetaData()
    for name in (
        "permission_migration_run",
        "permission_migration_item",
    ):
        table = SQLModel.metadata.tables[name].to_metadata(metadata)
        table.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            engine,
            expire_on_commit=False,
        ) as session:
            yield session

    monkeypatch.setattr(
        f048_runtime_storage,
        "get_async_db_session",
        session_factory,
    )
    async with session_factory() as session:
        async with session.begin():
            session.add(
                PermissionMigrationRun(
                    id=8,
                    environment_fingerprint="f" * 64,
                    phase="SOURCE_VALIDATING",
                    status="BLOCKED",
                    store_id="store-live",
                    source_model_id="legacy-model",
                    source_watermark="old-watermark",
                    source_checksum="s" * 64,
                    version=4,
                )
            )
            session.add(
                PermissionMigrationItem(
                    run_id=8,
                    source_kind="TUPLE",
                    source_locator="tuple:stale",
                    source_checksum="t" * 64,
                    status="READY",
                    severity="BLOCKER",
                    difference_type="ORPHAN_TUPLE",
                )
            )

    store = SqlMigrationRunStore(repository=MigrationRepository(session_factory))
    reset = await store.areset_blocked_source(
        run_id=8,
        expected_version=4,
        source_watermark="new-watermark",
    )

    assert (
        reset.status,
        reset.checkpoint,
        reset.source_watermark,
        reset.source_checksum,
        reset.version,
    ) == (
        "RUNNING",
        None,
        "new-watermark",
        None,
        5,
    )
    async with session_factory() as session:
        remaining = list(
            (await session.execute(sa.select(PermissionMigrationItem).where(PermissionMigrationItem.run_id == 8)))
            .scalars()
            .all()
        )
    assert remaining == []
    await engine.dispose()
