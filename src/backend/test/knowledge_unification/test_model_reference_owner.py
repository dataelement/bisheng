"""T276: real model/server and Root-share target verification.

覆盖 AC: AC-72, AC-87, AC-88, AC-89
SQLite verifies transaction boundaries, not MySQL/DM8 lock scheduling.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    ReferenceCoverageNotReadyError,
    ResourceReferenceConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.core.database import tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.llm.application import reference_target_owner as owner_module
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.reference_target_repository import ModelReferenceTargetRepository
from bisheng.resource_reference.application.contracts import LegacyEvidence, SourceKey, TargetKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification.test_ref_repo import tenant

TABLES = [
    Tenant.__table__,
    LLMModel.__table__,
    LLMServer.__table__,
    TenantSystemModelConfig.__table__,
    BusinessResourceReference.__table__,
    ResourceReferenceTombstone.__table__,
]
SOURCE = SourceKey(101, "assistant", "a1", "current")


@pytest.fixture(autouse=True)
def model_owner_tenant(monkeypatch):
    names = {table.name for table in TABLES if "tenant_id" in table.columns}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    with tenant(101):
        yield


@pytest.fixture
def engine(f118_engine):
    SQLModel.metadata.create_all(f118_engine, tables=TABLES)
    return f118_engine


def setup(session):
    session.add_all(
        [
            Tenant(id=1, tenant_code="root", tenant_name="Root", share_default_to_children=1),
            Tenant(id=101, tenant_code="one", tenant_name="One", parent_tenant_id=1),
            Tenant(id=202, tenant_code="two", tenant_name="Two", parent_tenant_id=1),
            LLMServer(id=1, tenant_id=101, name="own", type="openai"),
            LLMServer(id=2, tenant_id=1, name="shared", type="openai"),
            LLMServer(id=3, tenant_id=202, name="foreign", type="openai"),
            LLMModel(id=11, server_id=1, tenant_id=101, name="own", model_name="own", model_type="llm", online=False),
            LLMModel(id=22, server_id=2, tenant_id=1, name="shared", model_name="shared", model_type="llm"),
            LLMModel(id=33, server_id=3, tenant_id=202, name="foreign", model_name="foreign", model_type="llm"),
        ]
    )
    session.flush()


def verify(owner):
    return ReferenceTargetVerifier({"model": owner})


class FrozenSharing:
    def get_shared_server_ids(self, session, tenant_id, server_ids):
        assert tenant_id == 101 and server_ids == (2,)
        return frozenset({2})

    async def aget_shared_server_ids(self, session, tenant_id, server_ids):
        return self.get_shared_server_ids(session, tenant_id, server_ids)


def test_own_offline_model_is_a_live_binding_and_external_rollback_is_preserved(engine):
    with Session(engine) as session:
        with session.begin():
            setup(session)
            receipt = verify(ModelReferenceTargetOwner()).verify_targets(session, SOURCE, (TargetKey("model", "11"),))[
                0
            ]
            assert receipt.target.state == "valid" and receipt.target.model_server_id == "1"
            assert receipt.target.target_tenant_id == 101
            session.rollback()
        assert not session.exec(select(LLMModel)).all()


def test_sync_root_share_requires_native_trusted_evidence_and_cannot_enable_owner_query(engine):
    with Session(engine) as session, session.begin():
        setup(session)
        key = TargetKey("model", "22")
        with pytest.raises(ReferenceCoverageNotReadyError):
            verify(ModelReferenceTargetOwner()).verify_targets(session, SOURCE, (key,))
        owner = ModelReferenceTargetOwner(sharing=FrozenSharing())
        receipt = verify(owner).verify_targets(session, SOURCE, (key,))[0]
        assert receipt.target.target_tenant_id == 1 and receipt.target.model_server_id == "2"
        with pytest.raises(ResourceReferenceInvalidError):
            verify(owner).verify_owner_targets(session, (key,))
        with pytest.raises(ResourceReferenceInvalidError):
            verify(owner).verify_targets(session, SOURCE, (TargetKey("model", "33"),))


def test_model_server_owner_mismatch_is_rejected(engine):
    with Session(engine) as session, session.begin():
        setup(session)
        session.get(LLMModel, 11).server_id = 2
        session.flush()
        with pytest.raises(ResourceReferenceInvalidError):
            verify(ModelReferenceTargetOwner()).verify_targets(session, SOURCE, (TargetKey("model", "11"),))


def test_server_candidate_drift_rolls_back_whole_transaction(engine):
    with Session(engine) as session, session.begin():
        setup(session)
        session.add(LLMServer(id=4, tenant_id=101, name="other", type="openai"))
    changed = []

    def move_model(state):
        if state.is_select and state.statement._for_update_arg is not None and not changed:
            if LLMModel in {row.get("entity") for row in state.statement.column_descriptions}:
                changed.append(True)
                state.session.execute(update(LLMModel).where(LLMModel.id == 11).values(server_id=4))

    with Session(engine) as session:
        event.listen(session, "do_orm_execute", move_model)
        with pytest.raises(ResourceReferenceConflictError), session.begin():
            verify(ModelReferenceTargetOwner()).verify_targets(session, SOURCE, (TargetKey("model", "11"),))
    with Session(engine) as session:
        assert session.get(LLMModel, 11).server_id == 1 and changed


def test_original_deleted_model_uses_exact_owner_tombstone_without_guessing(engine):
    with Session(engine) as session, session.begin():
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="assistant",
                source_id="a1",
                source_version="current",
                slot_key="llm",
                target_type="model",
                target_id="80",
                target_tenant_id=1,
                source_revision=1,
            )
        )
        session.add(
            ResourceReferenceTombstone(
                tenant_id=1,
                target_type="model",
                target_id="80",
                target_tenant_id=1,
                operation_id="delete-1",
                operation_type="force_delete",
                stage="deleted",
                actor_type="user",
                actor_id="11",
            )
        )
        session.flush()
        receipt = verify(ModelReferenceTargetOwner()).verify_targets(session, SOURCE, (TargetKey("model", "80"),))[0]
        assert receipt.target.state == "invalid_deleted" and receipt.target.target_tenant_id == 1
        with pytest.raises(ResourceReferenceInvalidError):
            verify(ModelReferenceTargetOwner()).verify_targets(session, SOURCE, (TargetKey("model", "81"),))


def test_legacy_unknown_owner_requires_ledger_and_never_creates_tombstone(engine):
    class Ledger:
        def resolve(self, session, source_key, target, *, run_id, evidence_key):
            assert source_key == SOURCE and target == TargetKey("model", "80")
            return LegacyEvidence(run_id, "a" * 64, evidence_key)

    with Session(engine) as session, session.begin():
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="assistant",
                source_id="a1",
                source_version="current",
                slot_key="llm",
                target_type="model",
                target_id="80",
                target_tenant_id=None,
                source_revision=1,
                legacy_invalid_reason="target_missing",
                legacy_run_id="run-1",
                legacy_evidence_key="target-evidence",
            )
        )
        session.flush()
        with pytest.raises(ReferenceCoverageNotReadyError):
            verify(ModelReferenceTargetOwner()).verify_targets(session, SOURCE, (TargetKey("model", "80"),))
        receipt = verify(ModelReferenceTargetOwner(legacy_evidence=Ledger())).verify_targets(
            session, SOURCE, (TargetKey("model", "80"),)
        )[0]
        assert receipt.target.state == "invalid_legacy" and receipt.target.target_tenant_id is None
        assert not session.exec(select(ResourceReferenceTombstone)).all()


async def async_database():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=TABLES))
    async with AsyncSession(engine) as session, session.begin():
        await session.run_sync(setup)
    return engine


async def test_native_async_explicit_server_share_uses_permission_application(monkeypatch):
    class AsyncOnlyRepository(ModelReferenceTargetRepository):
        def lock_targets(self, *args, **kwargs):
            raise AssertionError("sync SQL used in async Owner")

    api = SimpleNamespace(list_resource_ids=AsyncMock(return_value=("2",)))
    monkeypatch.setattr(owner_module, "get_permission_relation_api", AsyncMock(return_value=api))
    database = await async_database()
    try:
        async with AsyncSession(database) as session, session.begin():
            receipt = (
                await verify(ModelReferenceTargetOwner(AsyncOnlyRepository())).averify_targets(
                    session, SOURCE, (TargetKey("model", "22"),)
                )
            )[0]
            assert receipt.target.target_tenant_id == 1 and receipt.target.state == "valid"
            assert api.list_resource_ids.await_args.kwargs["relation"] == "shared_with"
            assert api.list_resource_ids.await_args.kwargs["resource_type"] == "llm_server"
    finally:
        await database.dispose()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("knowledge_llm", {"embedding_model_id": 22}),
        ("assistant_llm", {"llm_list": [{"model_id": 22}]}),
        ("evaluation_llm", {"model_id": 22}),
        ("workflow_llm", {"model_id": 22}),
        ("linsight_llm", {"chat_default_model_id": "22"}),
    ],
)
async def test_actual_inherited_defaults_allow_only_their_root_servers(monkeypatch, key, value):
    monkeypatch.setattr(
        owner_module,
        "get_permission_relation_api",
        AsyncMock(return_value=SimpleNamespace(list_resource_ids=AsyncMock(return_value=()))),
    )
    database = await async_database()
    try:
        async with AsyncSession(database) as session, session.begin():
            session.add(TenantSystemModelConfig(tenant_id=1, key=key, value=json.dumps(value)))
            await session.flush()
            owner = ModelReferenceTargetOwner()
            receipt = (await verify(owner).averify_targets(session, SOURCE, (TargetKey("model", "22"),)))[0]
            assert receipt.target.target_tenant_id == 1
            session.add(TenantSystemModelConfig(tenant_id=101, key=key, value="{}"))
            await session.flush()
            with pytest.raises(ResourceReferenceInvalidError):
                await verify(owner).averify_targets(session, SOURCE, (TargetKey("model", "22"),))
    finally:
        await database.dispose()


async def test_global_root_share_flag_alone_is_not_an_allow_and_errors_do_not_narrow(monkeypatch):
    api = SimpleNamespace(list_resource_ids=AsyncMock(return_value=()))
    monkeypatch.setattr(owner_module, "get_permission_relation_api", AsyncMock(return_value=api))
    database = await async_database()
    try:
        async with AsyncSession(database) as session, session.begin():
            with pytest.raises(ResourceReferenceInvalidError):
                await verify(ModelReferenceTargetOwner()).averify_targets(session, SOURCE, (TargetKey("model", "22"),))
            api.list_resource_ids.side_effect = RuntimeError("sharing unavailable")
            with pytest.raises(RuntimeError, match="sharing unavailable"):
                await verify(ModelReferenceTargetOwner()).averify_targets(session, SOURCE, (TargetKey("model", "22"),))
    finally:
        await database.dispose()
