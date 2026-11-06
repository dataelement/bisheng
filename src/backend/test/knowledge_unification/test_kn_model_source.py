"""Actual Knowledge business source and complete model admission in both modes.

覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
Uses real Knowledge/R2 SQL and Model read Owner; C4 sharing/action transports
are test boundaries. No model provider, queue, FGA or production DB is called.
"""

import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application import model_reference_read as module
from bisheng.knowledge.application import reference_source_owner as owner_module
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication
from bisheng.knowledge.application.model_reference_read import KnowledgeModelReadRuntime
from bisheng.knowledge.application.reference_read_identity import KnowledgeModelReadIdentityPort
from bisheng.knowledge.application.reference_source_owner import KnowledgeReferenceSourceOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.permission.application.identity import get_current_permission_actor, set_current_permission_actor
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from bisheng.worker import tenant_context as workers
from test.knowledge_unification import test_kn_model_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
async def admission(business, monkeypatch):
    identity = KnowledgeModelReadIdentityPort()
    source = KnowledgeReferenceSourceOwner(identity_port=identity)
    verifier = SourceReadVerifier({SourceType.KNOWLEDGE: source}, identity)

    class Sharing:
        def get_shared_server_ids(self, session, tenant_id, server_ids):
            return frozenset(server_ids) & business.sharing.allowed

        async def aget_shared_server_ids(self, session, tenant_id, server_ids):
            return self.get_shared_server_ids(session, tenant_id, server_ids)

    target = ModelSourceReadTargetOwner(verifier, sharing=Sharing())
    core = ReferenceSourceReadRuntime(verifier, SourceReadRepository(verifier), {"model": target})
    runtime = KnowledgeModelReadRuntime(core, identity)
    monkeypatch.setattr(owner_module, "require_business_action", AsyncMock())
    monkeypatch.setattr(module, "get_async_db_session", business.sessions)

    @contextmanager
    def native_sessions():
        with Session(business.sync, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(module, "get_sync_db_session", native_sessions)
    await fixtures.seed(business)
    return business, runtime, source, identity


async def test_real_source_snapshot_contains_private_business_model_configuration(admission):
    context, runtime, source, _ = admission
    async with context.sessions() as session:
        result = await runtime.arequire(40, login_user=context.user, session=session)
        assert result.model_id == 11 and result.tenant_id == 101 and result.slot_key == "model"
        snapshot = result.read.snapshot
        facts = json.loads(snapshot.payload_json)["knowledge"]
        assert facts["model"] == "11" and facts["model_config_revision"] == 0
        assert facts["index_generation"] == "g0" and facts["model_transition"] is None
        owner_module.require_business_action.assert_not_awaited()
        # Generic raw User access retains its original visible authorization.
        await source.aresolve_source(session, SourceReadRequest(SourceType.KNOWLEDGE, "40"), context.user)
        owner_module.require_business_action.assert_awaited_once_with(
            context.user, resource_type="knowledge_space", resource_id=40, action="visible"
        )
        assert all(not isinstance(row, Knowledge) for row in session.identity_map.values())


def test_native_source_and_read_core_match_async_and_borrow_session(admission):
    context, runtime, _, _ = admission
    with Session(context.sync) as session:
        result = runtime.require(40, login_user=context.user, session=session)
        assert result.model_id == 11 and result.read.source_revision == 1
        assert session.in_transaction()
        session.rollback()


async def test_complete_source_rejects_invalid_pending_even_when_requesting_current_slot(admission):
    context, runtime, _, _ = admission
    async with context.sessions() as session:
        prepared = await KnowledgeModelReferenceApplication.aprepare_model_change(
            session, 40, 12, login_user=context.user
        )
        await KnowledgeModelReferenceApplication.aapply_model_change(session, prepared)
        await session.commit()
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 12, LLMModel.tenant_id == 101))
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.arequire(40, login_user=context.user, session=session, slot_key="model")


async def test_expected_business_revision_is_obsolescence_not_authorization(admission):
    context, runtime, _, _ = admission
    async with context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await runtime.arequire(40, login_user=context.user, session=session, expected_model_config_revision=99)
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.arequire(40, login_user=context.user, session=session, slot_key="task.model_id")


async def test_missing_source_index_and_source_config_drift_are_fail_closed(admission):
    context, runtime, _, _ = admission
    async with context.sessions() as session:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await runtime.arequire(10, login_user=context.user, session=session)
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.update(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101).values(model="12")
        )
    async with context.sessions() as session:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await runtime.arequire(40, login_user=context.user, session=session)


async def test_real_source_owner_revalidates_model_configuration_after_target_plan(admission):
    context, _, source, _ = admission
    async with context.sessions() as session:
        request = SourceReadRequest(SourceType.KNOWLEDGE, "40", "current")
        snapshot = await source.aresolve_source(session, request, context.user)
        await session.execute(
            sa.update(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101).values(index_generation="g1")
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await source.arevalidate_source(session, request, context.user, snapshot)


async def test_private_actor_scope_is_same_original_and_current_transaction_only(admission):
    context, runtime, _, identity = admission
    async with context.sessions() as session, context.sessions() as other:
        original_actor = get_current_permission_actor()
        private = await identity.aissue(session, 40)
        request = SourceReadRequest(SourceType.KNOWLEDGE, "40", "current")
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.core.verifier.aissue_scope(session, request, replace(private))
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.core.verifier.aissue_scope(other, request, private)
        token = set_current_permission_actor(replace(original_actor))
        try:
            with pytest.raises(ResourceReferenceInvalidError):
                await runtime.core.verifier.aissue_scope(session, request, private)
        finally:
            from bisheng.permission.application.identity import reset_current_permission_actor

            reset_current_permission_actor(token)
        assert (await runtime.arequire(40, session=session)).model_id == 11
        owner_module.require_business_action.assert_not_awaited()


async def test_private_actor_scope_never_uses_user_id_to_read_foreign_knowledge(admission):
    context, runtime, _, _ = admission
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.arequire(30, session=session)


@pytest.mark.parametrize("channel", ["open", "public"])
async def test_private_scope_preserves_original_principal_and_actual_visitor_actor(admission, channel):
    from bisheng.open_api.domain.context import (
        OpenApiPrincipal,
        reset_current_open_api_principal,
        set_current_open_api_principal,
    )
    from bisheng.public_endpoints.domain.context import (
        PublicApiPrincipal,
        reset_current_public_api_principal,
        set_current_public_api_principal,
    )

    context, runtime, _, identity = admission
    if channel == "open":
        principal = OpenApiPrincipal(
            credential_id=42,
            actor_kind="hosted_app",
            actor_id=91,
            actor_name="actual app",
            tenant_id=101,
            resource_owner_user_id=99,
            scopes=frozenset({"filelib:retrieve"}),
            authorization_subject_type="service_account",
            authorization_subject_id=91,
            effective_user_id=None,
        )
        setter, reset = set_current_open_api_principal, reset_current_open_api_principal
    else:
        principal = PublicApiPrincipal(
            tenant_id=101,
            operator_user_id=99,
            operator_name="publisher",
            resource_type="assistant",
            resource_id="published",
        )
        setter, reset = set_current_public_api_principal, reset_current_public_api_principal
    token = setter(principal)
    try:
        original_actor = get_current_permission_actor()
        async with context.sessions() as session:
            private = await identity.aissue(session, 40)
            result = await runtime.arequire(40, session=session)
            assert result.model_id == 11
            assert get_current_permission_actor() is original_actor
            owner_module.require_business_action.assert_not_awaited()
            # A value-equal replacement is not the same authenticated object.
            replacement = setter(principal.model_copy())
            try:
                with pytest.raises(ResourceReferenceInvalidError):
                    await identity.acapture(private)
            finally:
                reset(replacement)
            assert (await identity.acapture(private)).request_tenant_id == 101
    finally:
        reset(token)


async def test_actual_owned_source_can_consume_root_shared_model_and_rejects_revocation(admission):
    context, runtime, _, _ = admission
    async with context.sessions() as session:
        row = Knowledge(id=41, name="shared model source", tenant_id=101, user_id=7, type=3, model="22")
        await KnowledgeModelReferenceApplication.acreate(
            session, row, login_user=context.user, project_created=AsyncMock()
        )
        await session.commit()
    async with context.sessions() as session:
        result = await runtime.arequire(41, session=session)
        assert result.model_id == 22 and result.tenant_id == 101
    context.sharing.allowed = frozenset()
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.arequire(41, session=session)


async def test_config_read_without_actor_keeps_actual_scope_and_binds_existing_background_lifecycle(
    admission, monkeypatch
):
    from bisheng.permission.application.identity import reset_current_permission_actor

    context, runtime, _, identity = admission
    sender = SimpleNamespace(
        name="bisheng.worker.knowledge.rebuild",
        request=SimpleNamespace(id="actual-task", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    actor_token = set_current_permission_actor(None)
    try:
        async with context.sessions() as session:
            with tenant_execution_scope(101):
                # Reading model configuration is not a data-access permit and
                # must also work in an already-authorized synchronous caller.
                assert (await runtime.arequire(40, session=session)).model_id == 11
            workers.restore_tenant_context(sender=sender)
            try:
                private = await identity.aissue(session, 40)
                assert (await runtime.arequire(40, session=session)).model_id == 11
                owner_module.require_business_action.assert_not_awaited()
            finally:
                workers.reset_tenant_context(sender=sender)
            with pytest.raises(ResourceReferenceInvalidError):
                await identity.acapture(private)
    finally:
        reset_current_permission_actor(actor_token)


async def test_config_only_scope_is_not_a_raw_user_or_http_inspection_permit(admission):
    from bisheng.common.errcode.http_error import UnAuthorizedError

    context, runtime, source, identity = admission
    owner_module.require_business_action.side_effect = UnAuthorizedError()
    async with context.sessions() as session:
        # knowledge_auth=False keeps its existing upstream delegation; model
        # configuration admission must not add a second KN visible decision.
        assert (await runtime.arequire(40, login_user=context.user, session=session)).model_id == 11
        owner_module.require_business_action.assert_not_awaited()
        private = await identity.aissue(session, 40, login_user=context.user)
        with pytest.raises(ResourceReferenceInvalidError):
            await source.aresolve_source(
                session, SourceReadRequest(SourceType.KNOWLEDGE, "40", purpose="inspect"), private
            )
        with pytest.raises(ResourceReferenceInvalidError):
            await KnowledgeReferenceSourceOwner().aresolve_source(
                session, SourceReadRequest(SourceType.KNOWLEDGE, "40"), private
            )
        with pytest.raises(UnAuthorizedError):
            await source.aresolve_source(session, SourceReadRequest(SourceType.KNOWLEDGE, "40"), context.user)


async def test_config_only_scope_requires_explicit_tenant_and_original_user_object(admission):
    from bisheng.core.context.tenant import current_tenant_id

    context, runtime, _, identity = admission
    async with context.sessions() as session:
        private = await identity.aissue(session, 40, login_user=context.user)
        object.__setattr__(private, "login_user", context.user.model_copy())
        with pytest.raises(ResourceReferenceInvalidError):
            await identity.acapture(private)
        token = current_tenant_id.set(None)
        try:
            with pytest.raises(ResourceReferenceInvalidError):
                await runtime.arequire(40, login_user=context.user, session=session)
        finally:
            current_tenant_id.reset(token)
