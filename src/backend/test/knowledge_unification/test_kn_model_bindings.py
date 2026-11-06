"""Knowledge lifecycle binds actual serving/pending models in one transaction.

覆盖 AC: AC-68, AC-71, AC-74, AC-87, AC-88, AC-89, AC-91, AC-92, AC-93.
Real Knowledge/Model/Reference/legacy-ledger SQL and TargetOwner issuance;
permission sharing and action transport are explicit test boundaries.
"""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeNoEmbeddingError,
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.application import model_reference as app_module
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication
from bisheng.knowledge.application.reference_legacy_evidence import KnowledgeLegacyReferenceEvidence
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_kn_reference_repository as fixtures

store = fixtures.store
tenant = fixtures.tenant


@pytest.fixture
async def business(store, monkeypatch):
    sync, engine = store
    models = (
        Tenant,
        LLMServer,
        LLMModel,
        TenantSystemModelConfig,
        BusinessReferenceSet,
        BusinessResourceReference,
        ResourceReferenceTombstone,
        KnowledgeUnificationRun,
    )
    for model in models:
        model.__table__.create(sync)
    with Session(sync) as session, bypass_tenant_filter():
        session.add_all(
            [
                Tenant(id=1, tenant_code="root", tenant_name="Root"),
                Tenant(id=101, tenant_code="child", tenant_name="Child", parent_tenant_id=1),
                LLMServer(id=1, tenant_id=101, name="own", type="openai"),
                LLMServer(id=2, tenant_id=1, name="shared", type="openai"),
            ]
        )
        session.add_all(
            [
                LLMModel(
                    id=ident,
                    tenant_id=tenant,
                    server_id=server,
                    name=str(ident),
                    model_name=str(ident),
                    model_type=kind,
                )
                for ident, tenant, server, kind in (
                    (11, 101, 1, "embedding"),
                    (12, 101, 1, "embedding"),
                    (22, 1, 2, "embedding"),
                    (33, 101, 1, "llm"),
                )
            ]
        )
        session.commit()
    sharing = SimpleNamespace(allowed=frozenset({2}))

    class Sharing:
        def get_shared_server_ids(self, session, tenant_id, server_ids):
            return frozenset(server_ids) & sharing.allowed

        async def aget_shared_server_ids(self, session, tenant_id, server_ids):
            return self.get_shared_server_ids(session, tenant_id, server_ids)

    owner = ModelReferenceTargetOwner(sharing=Sharing(), legacy_evidence=KnowledgeLegacyReferenceEvidence())
    verifier = ReferenceTargetVerifier({"model": owner})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    monkeypatch.setattr(app_module, "get_reference_binding_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(app_module, "get_reference_binding_runtime_sync", lambda: runtime)
    monkeypatch.setattr(app_module, "require_business_action", AsyncMock())
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    token = set_current_permission_actor(PermissionActor(tenant_id=101, user_id=7))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    try:
        yield SimpleNamespace(sync=sync, engine=engine, sessions=sessions, runtime=runtime, user=user, sharing=sharing)
    finally:
        reset_current_permission_actor(token)


def state(context):
    with context.sync.connect() as conn:
        return {
            model.__tablename__: conn.execute(sa.select(model.__table__).order_by(model.__table__.c.id))
            .mappings()
            .all()
            for model in (Knowledge, BusinessReferenceSet, BusinessResourceReference)
        }


async def seed(context, model="11"):
    async with context.sessions() as session:
        row = Knowledge(id=40, tenant_id=101, user_id=7, name="source", type=3, model=model, index_generation="g0")
        await KnowledgeModelReferenceApplication.acreate(
            session, row, login_user=context.user, project_created=AsyncMock()
        )
        await session.commit()
    return row


async def test_create_actual_flushed_resource_and_reference_projection_share_external_rollback(business):
    before = state(business)
    projection = AsyncMock()
    async with business.sessions() as session:
        row = Knowledge(tenant_id=101, user_id=7, name="new", model="11", type=0)
        actual = await KnowledgeModelReferenceApplication.acreate(
            session, row, login_user=business.user, project_created=projection
        )
        assert actual is row and row.id is not None
        projection.assert_awaited_once_with(row)
        await session.rollback()
    assert state(business) == before


async def test_model_switch_keeps_current_model_and_old_binding_until_finalize(business):
    await seed(business)
    async with business.sessions() as session:
        prepared = await KnowledgeModelReferenceApplication.aprepare_model_change(
            session, 40, 12, login_user=business.user, operation_id="operation-1"
        )
        await KnowledgeModelReferenceApplication.aapply_model_change(session, prepared)
        await session.commit()
    row = next(row for row in state(business)["knowledge"] if row["id"] == 40)
    assert row["model"] == "11" and row["model_transition"] == {
        "schema_version": 1,
        "operation_id": "operation-1",
        "current_model_id": "11",
        "pending_model_id": "12",
    }
    assert row["model_config_revision"] == 1 and row["state"] == 3
    refs = state(business)["business_resource_reference"]
    assert {(row["slot_key"], row["target_id"]) for row in refs} == {
        ("model", "11"),
        ("model_transition.pending_model_id", "12"),
    }


async def test_legal_root_shared_embedding_is_read_through_real_verified_owner_not_client_tenant(business):
    await seed(business)
    async with business.sessions() as session:
        prepared = await KnowledgeModelReferenceApplication.aprepare_model_change(
            session, 40, 22, login_user=business.user
        )
        await KnowledgeModelReferenceApplication.aapply_model_change(session, prepared)
        await session.rollback()


async def test_wrong_actual_model_kind_is_rejected_without_partial_model_or_source_write(business):
    await seed(business)
    before = state(business)
    async with business.sessions() as session:
        with pytest.raises(KnowledgeNoEmbeddingError):
            await KnowledgeModelReferenceApplication.aprepare_model_change(session, 40, 33, login_user=business.user)
        await session.rollback()
    assert state(business) == before


@pytest.mark.parametrize("invalid", ["deleted", "legacy", "revoked"])
async def test_explicit_repair_releases_invalid_current_slot_so_strict_worker_can_execute(business, invalid):
    await seed(business, "22" if invalid == "revoked" else "11")
    if invalid == "revoked":
        business.sharing.allowed = frozenset()
    else:
        async with business.sessions() as session, session.begin():
            await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
            if invalid == "deleted":
                session.add(
                    ResourceReferenceTombstone(
                        tenant_id=101,
                        target_type="model",
                        target_id="11",
                        target_tenant_id=101,
                        operation_id="delete11",
                        operation_type="force_delete",
                        stage="deleted",
                        actor_type="user",
                        actor_id="7",
                    )
                )
            else:
                session.add(
                    KnowledgeUnificationRun(
                        tenant_id=101,
                        run_id="run-1",
                        origin="migration",
                        phase="verified",
                        baseline_hash="a" * 64,
                        plan_hash="b" * 64,
                        baseline_ref={"object_key": "baseline", "sha256": "a" * 64},
                        plan_ref={"object_key": "plan", "sha256": "b" * 64},
                    )
                )
                await session.execute(
                    sa.update(BusinessResourceReference)
                    .where(BusinessResourceReference.tenant_id == 101, BusinessResourceReference.source_id == "40")
                    .values(legacy_invalid_reason="target_missing", legacy_run_id="run-1", legacy_evidence_key="ev-1")
                )
    async with business.sessions() as session:
        prepared = await KnowledgeModelReferenceApplication.aprepare_model_change(
            session, 40, 12, login_user=business.user, operation_id="repair-1"
        )
        await KnowledgeModelReferenceApplication.aapply_model_change(session, prepared)
        await session.commit()
    row = next(row for row in state(business)["knowledge"] if row["id"] == 40)
    assert row["model"] == "12" and row["model_transition"]["current_model_id"] == "12"
    assert {row["target_id"] for row in state(business)["business_resource_reference"]} == {"12"}


async def test_deleting_current_target_freezes_even_explicit_repair(business):
    await seed(business)
    async with business.sessions() as session, session.begin():
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="model",
                target_id="11",
                target_tenant_id=101,
                operation_id="delete11",
                operation_type="force_delete",
                stage="deleting",
                actor_type="user",
                actor_id="7",
            )
        )
    before = state(business)
    async with business.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await KnowledgeModelReferenceApplication.aprepare_model_change(session, 40, 12, login_user=business.user)
        await session.rollback()
    assert state(business) == before


async def test_apply_failure_rolls_back_model_transition_and_refs_together(business, monkeypatch):
    await seed(business)
    before = state(business)
    monkeypatch.setattr(
        business.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("reference failed"))
    )
    async with business.sessions() as session:
        prepared = await KnowledgeModelReferenceApplication.aprepare_model_change(
            session, 40, 12, login_user=business.user
        )
        with pytest.raises(RuntimeError, match="reference failed"):
            await KnowledgeModelReferenceApplication.aapply_model_change(session, prepared)
        await session.rollback()
    assert state(business) == before


async def test_existing_unindexed_model_config_cannot_be_bootstrapped_by_save(business):
    async with business.sessions() as session:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await KnowledgeModelReferenceApplication.aprepare_model_change(session, 10, 12, login_user=business.user)


async def test_prepared_business_model_command_cannot_be_cloned_or_used_in_another_session(business):
    await seed(business)
    async with business.sessions() as session, business.sessions() as other:
        prepared = await KnowledgeModelReferenceApplication.aprepare_model_change(
            session, 40, 12, login_user=business.user
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await KnowledgeModelReferenceApplication.aapply_model_change(session, replace(prepared))
        with pytest.raises(ResourceReferenceInvalidError):
            await KnowledgeModelReferenceApplication.aapply_model_change(other, prepared)


def test_native_creation_and_switch_use_real_sql_and_external_rollback(business):
    before = state(business)
    with Session(business.sync, expire_on_commit=False) as session:
        row = Knowledge(id=40, tenant_id=101, user_id=7, name="native", type=1, model="11", index_generation="g0")
        projection = Mock()
        assert (
            KnowledgeModelReferenceApplication.create(
                session, row, login_user=business.user, project_created=projection
            )
            is row
        )
        projection.assert_called_once_with(row)
        session.commit()
        prepared = KnowledgeModelReferenceApplication.prepare_model_change(
            session, 40, 12, login_user=business.user, operation_id="native-1"
        )
        KnowledgeModelReferenceApplication.apply_model_change(session, prepared)
        assert row.model == "11" and row.model_transition["pending_model_id"] == "12"
        session.rollback()
        assert row.model_transition is None and row.model_config_revision == 0
    assert len(state(business)["knowledge"]) == len(before["knowledge"]) + 1


async def test_stale_expected_configuration_and_config_index_drift_fail_without_writes(business):
    await seed(business)
    before = state(business)
    async with business.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await KnowledgeModelReferenceApplication.aprepare_model_change(
                session, 40, 12, login_user=business.user, expected_model_config_revision=99
            )
        await session.rollback()
    assert state(business) == before
    async with business.sessions() as session, session.begin():
        await session.execute(
            sa.update(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101).values(model="12")
        )
    before = state(business)
    async with business.sessions() as session:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await KnowledgeModelReferenceApplication.aprepare_model_change(session, 40, 11, login_user=business.user)
        await session.rollback()
    assert state(business) == before
