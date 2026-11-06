"""Actual APP whole-source admission and final cached model identity. 覆盖 AC: AC-37, AC-68, AC-71, AC-87, AC-89, AC-91, AC-92."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish import composition
from bisheng.app_publish.application import reference_source_owner
from bisheng.app_publish.application.reference_access import get_hosted_app_reference_runtime
from bisheng.app_publish.domain.services import capability_bus_service as bus
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.common.errcode.model_face import ModelFaceModelRevokedError
from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.domain.services.model_catalog import ResolvedModel
from bisheng.open_api.domain.schemas.model_gateway import ChatCompletionRequest
from bisheng.open_api.domain.services import model_gateway_service as gateway
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from test.knowledge_unification import test_app_snapshot as fixtures

ctx = fixtures.ctx
resolving = fixtures.resolving
application = fixtures.application
writing = fixtures.writing


def resolved(model_id=11, server_id=1):
    return ResolvedModel(model_id, server_id, "alpha", "own", "openai", "own/alpha")


async def admitted(context, session, *, purpose="execute"):
    composition.register()
    runtime = await get_hosted_app_reference_runtime()
    request = SourceReadRequest(SourceType.HOSTED_APP_VERSION, "actual-app", purpose=purpose)
    scope = await runtime.verifier.aissue_scope(session, request, context.identity)
    result = (
        await runtime.arequire_source_valid(session, scope, context.identity)
        if purpose == "execute"
        else await runtime.ainspect_source(session, scope, context.identity)
    )
    return runtime, result.snapshot


async def test_runtime_exposes_its_exact_registered_source_owner(writing):
    composition.register()
    runtime = await get_hosted_app_reference_runtime()
    assert runtime.source_owner is runtime.verifier._owners[SourceType.HOSTED_APP_VERSION]


async def test_candidate_or_inspection_is_not_model_execution_admission(writing):
    composition.register()
    runtime = await get_hosted_app_reference_runtime()
    async with AsyncSession(writing.engine) as session, session.begin():
        candidate = await runtime.source_owner.aresolve_source(
            session, SourceReadRequest(SourceType.HOSTED_APP_VERSION, "actual-app"), writing.identity
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.source_owner.assert_model_binding_current(
                session, candidate, writing.identity, "alpha", resolved()
            )
        _, snapshot = await admitted(writing, session, purpose="inspect")
        with pytest.raises(ResourceReferenceInvalidError):
            await runtime.source_owner.assert_model_binding_current(
                session, snapshot, writing.identity, "alpha", resolved()
            )


async def test_same_source_alias_uses_original_complete_plan_after_full_core_admission(writing):
    async with AsyncSession(writing.engine) as session, session.begin():
        runtime, snapshot = await admitted(writing, session)
        assert (
            await runtime.source_owner.assert_model_binding_current(
                session, snapshot, writing.identity, "own/alpha", resolved()
            )
            is None
        )
        assert (
            await runtime.source_owner.assert_model_binding_current(
                session, snapshot, writing.identity, "alpha", resolved()
            )
            is None
        )


@pytest.mark.parametrize("model_id,server_id", [(13, 1), (11, 2)])
async def test_cached_gateway_actual_id_or_server_mismatch_is_never_called(writing, model_id, server_id):
    async with AsyncSession(writing.engine) as session, session.begin():
        runtime, snapshot = await admitted(writing, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await runtime.source_owner.assert_model_binding_current(
                session, snapshot, writing.identity, "alpha", resolved(model_id, server_id)
            )


async def test_model_proof_cannot_cross_transaction_or_original_identity(writing):
    async with AsyncSession(writing.engine) as session:
        async with session.begin():
            runtime, snapshot = await admitted(writing, session)
            with pytest.raises(ResourceReferenceInvalidError):
                await runtime.source_owner.assert_model_binding_current(
                    session, snapshot, writing.identity.model_copy(), "alpha", resolved()
                )
        async with session.begin():
            with pytest.raises(ResourceReferenceInvalidError):
                await runtime.source_owner.assert_model_binding_current(
                    session, snapshot, writing.identity, "alpha", resolved()
                )


@pytest.fixture
async def capability_bus(writing, monkeypatch):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(writing.engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(bus, "get_async_db_session", factory)
    # A saved version must consume its frozen index, never old independent DAO/name readers.
    monkeypatch.setattr(bus, "_resolve_knowledge_refs", AsyncMock(side_effect=AssertionError("free resolution")))
    composition.register()
    return writing


async def test_actual_adapter_checks_final_cached_model_with_real_full_source(capability_bus):
    adapter = bus.HostedAppDeclarationAdapter()
    assert await adapter.assert_model_binding(capability_bus.identity, "own/alpha", resolved()) is None
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await adapter.assert_model_binding(capability_bus.identity, "alpha", resolved(13))


async def test_effective_declaration_uses_original_principal_and_frozen_ids(capability_bus):
    declaration = await bus.load_effective_declaration("actual-app", principal=capability_bus.identity)
    assert declaration.version_id == fixtures.fixtures.VERSION
    assert declaration.knowledge_whitelist == [7]
    assert declaration.model_names == frozenset({"alpha"})
    with pytest.raises(ResourceReferenceInvalidError):
        await bus.load_effective_declaration("actual-app", principal=capability_bus.identity.model_copy())


async def test_whole_source_bad_knowledge_blocks_model_and_retrieval_before_io(capability_bus, monkeypatch):
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    retrieval = AsyncMock()
    monkeypatch.setattr(RetrievalFacadeService, "retrieve", retrieval)
    async with AsyncSession(capability_bus.engine) as session, session.begin():
        await session.execute(sa.delete(Knowledge).where(Knowledge.id == 7))
    with pytest.raises(BaseErrorCode):
        await bus.HostedAppDeclarationAdapter().assert_model_binding(capability_bus.identity, "alpha", resolved())
    with pytest.raises(BaseErrorCode):
        await bus.CapabilityBusService.retrieve(
            app_id="actual-app", principal=capability_bus.identity, access_user_id=4, query="question"
        )
    retrieval.assert_not_awaited()


async def test_broken_whitelist_never_silently_drops_a_saved_reference():
    declaration = bus.EffectiveDeclaration(
        "app", 101, "actual-version", knowledge=(bus.DeclaredKnowledge("7", 7, reason=bus.REASON_REVOKED),)
    )
    with pytest.raises(ResourceReferenceInvalidError):
        _ = declaration.knowledge_whitelist


@pytest.mark.parametrize("knowledge_type", [0, 3])
async def test_actual_retrieval_keeps_access_user_narrowing_and_legacy_kinds(
    capability_bus, monkeypatch, knowledge_type
):
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    async with AsyncSession(capability_bus.engine) as session, session.begin():
        await session.execute(sa.update(Knowledge).where(Knowledge.id == 7).values(type=knowledge_type))
    access_identity = object()
    from_user = AsyncMock(return_value=access_identity)
    retrieval = AsyncMock(return_value=object())
    record = AsyncMock()
    monkeypatch.setattr(RetrievalIdentity, "from_user", from_user)
    monkeypatch.setattr(RetrievalFacadeService, "retrieve", retrieval)
    monkeypatch.setattr(bus.CapabilityBusService, "_record", record)
    result = await bus.CapabilityBusService.retrieve(
        app_id="actual-app", principal=capability_bus.identity, access_user_id=44, query="question", knowledge_ids=[7]
    )
    assert result is retrieval.return_value
    from_user.assert_awaited_once_with(44, 101)
    assert retrieval.await_args.args[0] is access_identity
    assert retrieval.await_args.args[1].whitelist == [7]
    assert retrieval.await_args.args[1].knowledge_ids == [7]
    with pytest.raises(BaseErrorCode):
        await bus.CapabilityBusService.retrieve(
            app_id="actual-app",
            principal=capability_bus.identity,
            access_user_id=44,
            query="question",
            knowledge_ids=[8],
        )
    assert retrieval.await_count == 1


async def test_historical_qa_blocks_actual_model_gateway_and_retrieval_before_provider(capability_bus, monkeypatch):
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    async with AsyncSession(capability_bus.engine) as session, session.begin():
        await session.execute(sa.update(Knowledge).where(Knowledge.id == 7).values(type=1))
    # The real range adapter, APP SourceOwner, Core and final binding run. Only
    # the existing cached catalog and external model/retrieval effects are doubles.
    monkeypatch.setattr(gateway, "resolve_model_name", AsyncMock(return_value=resolved()))
    instantiate = AsyncMock(side_effect=AssertionError("QA source reached provider"))
    monkeypatch.setattr(gateway.ModelGatewayService, "_instantiate", instantiate)
    monkeypatch.setattr(gateway.ModelGatewayService, "_start_record", Mock(return_value=SimpleNamespace()))
    monkeypatch.setattr(gateway.ModelGatewayService, "_finish_record", Mock())
    with pytest.raises(ModelFaceModelRevokedError):
        await gateway.ModelGatewayService.complete(
            capability_bus.identity,
            None,
            ChatCompletionRequest(model="alpha", messages=[{"role": "user", "content": "hi"}]),
        )
    instantiate.assert_not_awaited()
    retrieval = AsyncMock()
    monkeypatch.setattr(RetrievalFacadeService, "retrieve", retrieval)
    with pytest.raises(ResourceReferenceInvalidError):
        await bus.CapabilityBusService.retrieve(
            app_id="actual-app", principal=capability_bus.identity, access_user_id=44, query="question"
        )
    retrieval.assert_not_awaited()
    async with AsyncSession(capability_bus.engine) as session, session.begin():
        version = await session.get(fixtures.AppVersion, fixtures.fixtures.VERSION)
        assert version.capabilities["knowledge_bases"] == [{"id": "7"}]


@pytest.fixture
async def native_gateway(capability_bus, monkeypatch):
    """Real local catalog/preview reads; only external cache/FGA/provider edges are doubles."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository
    from bisheng.llm.domain.services import model_catalog
    from bisheng.permission import application as permission_api

    @asynccontextmanager
    async def factory():
        async with AsyncSession(capability_bus.engine, expire_on_commit=False) as session:
            yield session

    for path in (
        "bisheng.app_publish.domain.repositories.preview_runtime_repository",
        "bisheng.approval.domain.repositories.app_review_repository",
        "bisheng.user.domain.repositories.runtime_identity",
        "bisheng.user.domain.models.user_role",
        "bisheng.open_api.domain.repositories.credential_repository",
        "bisheng.llm.domain.models.llm_server",
        "bisheng.llm.domain.models.tenant_system_model_config",
        "bisheng.llm.application.model_default_read",
    ):
        monkeypatch.setattr(import_module(path), "get_async_db_session", factory)
    from bisheng.llm.application import model_default_read
    from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
    from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
    from bisheng.resource_reference import read_composition

    default_identity = ModelDefaultReadIdentityPort()
    default_owner = ModelDefaultSourceOwner(identity_port=default_identity)
    default_runtime = model_default_read.ModelDefaultReadRuntime(
        read_composition._model_graph(default_owner, default_identity, SourceType.MODEL_DEFAULT), default_identity
    )
    monkeypatch.setattr(model_default_read, "_runtime", default_runtime)
    coordinator = import_module("bisheng.app_runtime.domain.services.runtime_delivery_coordinator")
    monkeypatch.setattr(coordinator, "RuntimeDeliveryRepository", lambda: RuntimeDeliveryRepository(factory))
    redis = import_module("bisheng.core.cache.redis_manager")
    cache = SimpleNamespace(aget=AsyncMock(return_value=None), aset=AsyncMock())
    monkeypatch.setattr(redis, "get_redis_client", AsyncMock(return_value=cache))
    permissions = SimpleNamespace(check=AsyncMock(return_value=False), list_resource_ids=AsyncMock(return_value=[]))
    monkeypatch.setattr(permission_api, "get_permission_relation_api", AsyncMock(return_value=permissions))
    monkeypatch.setattr(gateway.ModelGatewayService, "_start_record", Mock(return_value=SimpleNamespace()))
    monkeypatch.setattr(gateway.ModelGatewayService, "_finish_record", Mock())
    provider = AsyncMock(side_effect=RuntimeError("provider boundary"))
    monkeypatch.setattr(gateway.ModelGatewayService, "_instantiate", provider)
    model_catalog.invalidate_catalog()
    try:
        yield SimpleNamespace(**vars(capability_bus), provider=provider)
    finally:
        model_catalog.invalidate_catalog()


async def test_actual_deleted_model_still_in_cached_catalog_never_reaches_provider(native_gateway):
    from bisheng.llm.domain.models.llm_server import LLMModel
    from bisheng.llm.domain.services.model_catalog import resolve_model_name
    from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

    original = native_gateway.identity
    cached = await resolve_model_name(101, "alpha")
    assert (cached.model_id, cached.server_id) == (11, 1)
    async with AsyncSession(native_gateway.engine) as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="model",
                target_id="11",
                target_tenant_id=101,
                operation_id="actual-model-delete",
                operation_type="delete",
                stage="deleted",
                actor_type="user",
                actor_id="4",
            )
        )
    # Exercise the real cache window, not an invented current-name result.
    assert await resolve_model_name(101, "alpha") == cached
    with pytest.raises(ModelFaceModelRevokedError) as raised:
        await gateway.ModelGatewayService.complete(
            original, None, ChatCompletionRequest(model="alpha", messages=[{"role": "user", "content": "hi"}])
        )
    assert raised.value.__cause__ is not None
    native_gateway.provider.assert_not_awaited()


async def test_actual_preview_gateway_binds_pending_version_and_current_preview_facts(native_gateway, monkeypatch):
    from starlette.requests import Request

    from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession
    from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
    from bisheng.app_publish.domain.services.reference_extractor import extract_app_reference_requests
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation, RuntimeRoute
    from bisheng.app_runtime.domain.services import entry_authz_service as entry
    from bisheng.approval.application.app_review import pending_app_reviews
    from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalTask
    from bisheng.database.models.app import App
    from bisheng.database.models.tenant import UserTenant
    from bisheng.database.models.user_role import UserRole
    from bisheng.llm.domain.models.llm_server import LLMModel
    from bisheng.llm.domain.services import model_catalog
    from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal
    from bisheng.open_api.domain.models.api_credential import ApiCredential
    from bisheng.open_api.domain.services.preview_context import bind_preview_principal
    from bisheng.resource_reference.application.contracts import (
        ReferenceSpec,
        TargetKey,
        TargetType,
        reference_set_digest,
    )
    from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
    from bisheng.user.domain.models.user import User

    metadata = sa.MetaData()
    for model in (ApprovalInstance, ApprovalTask, User, UserTenant, UserRole):
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
    now = datetime.utcnow()
    preview_version = fixtures.fixtures.HISTORY
    active_version = fixtures.fixtures.VERSION
    async with native_gateway.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with AsyncSession(native_gateway.engine) as session, session.begin():
        session.add(User(user_id=22, user_name="reviewer", password="unused", delete=0))
        session.add(UserTenant(id=22, user_id=22, tenant_id=101, is_active=1, status="active"))
        session.add(
            ApprovalInstance(
                id=61,
                tenant_id=101,
                scenario_code="app_publish_request",
                scenario_name="Publish",
                handler_key="app_publish",
                business_key="actual-app:pending",
                business_resource_type="app",
                business_resource_id="actual-app",
                business_name="Application",
                applicant_user_id=4,
                applicant_user_name="owner",
                status="pending",
                payload_snapshot={"version_id": preview_version},
                detail_snapshot={},
            )
        )
        session.add(
            ApprovalTask(
                id=62,
                tenant_id=101,
                instance_id=61,
                flow_version_id=1,
                node_code="review",
                node_name="Review",
                node_order=1,
                approver_user_id=22,
                approver_source_type="user",
                node_mode="any",
                status="pending",
            )
        )
        session.add(
            ApiCredential(
                id=19,
                tenant_id=101,
                subject_kind="hosted_app",
                subject_id=7,
                name="preview",
                key_prefix="bs-app-",
                last4="prev",
                token_hash="1" * 64,
                scopes=list(native_gateway.identity.scopes),
                expires_at=now + timedelta(hours=1),
            )
        )
        session.add(
            AppPreviewSession(
                id="actual-preview",
                tenant_id=101,
                app_id="actual-app",
                version_id=preview_version,
                approver_user_id=22,
                purpose="approval",
                approval_instance_id=61,
                approval_task_id=62,
                credential_id=19,
                operation_id="preview-op",
                status="running",
                expires_at=now + timedelta(hours=1),
            )
        )
        session.add(
            RuntimeOperation(
                id="preview-op",
                tenant_id=101,
                app_id="actual-app",
                scope_key="app:actual-app",
                idempotency_key="preview",
                request_digest="2" * 64,
                version_id=preview_version,
                kind="preview",
                node_id="native-node",
                generation=2,
                owner_epoch=3,
                status="running",
                deadline=now + timedelta(hours=1),
                payload={
                    "session_id": "actual-preview",
                    "preview_purpose": "approval",
                    "preview_credential_id": 19,
                    "authorization_context": {
                        "purpose": "approval_preview",
                        "actor": {"subject_id": 22},
                        "approval_instance_id": 61,
                        "approval_task_id": 62,
                    },
                },
            )
        )
        session.add(
            RuntimeRoute(
                id="preview-route",
                tenant_id=101,
                app_id="actual-app",
                operation_id="preview-op",
                route_key="preview:actual-preview",
                version_id=preview_version,
                node_id="native-node",
                exec_ref="preview-container",
                generation=2,
                owner_epoch=3,
                status="serving",
            )
        )
        # Active and preview declarations genuinely differ. Preview must use alpha/11,
        # while the active version freezes root/slash/13 and grants no alpha name.
        active = {"models": [{"name": "root/slash"}], "knowledge_bases": [{"id": "7"}]}
        await session.execute(
            sa.update(fixtures.AppVersion)
            .where(fixtures.AppVersion.id == active_version)
            .values(capabilities=active, manifest={"capabilities": active})
        )
        active_refs = tuple(
            ReferenceSpec(
                ref.slot_key, TargetKey(ref.target_type, "13" if ref.target_type == TargetType.MODEL else "7")
            )
            for ref in extract_app_reference_requests(CapabilityDeclaration.model_validate(active))
        )
        active_model_slot = next(ref.slot_key for ref in active_refs if ref.target.target_type == TargetType.MODEL)
        await session.execute(
            sa.update(BusinessResourceReference)
            .where(
                BusinessResourceReference.source_version == active_version,
                BusinessResourceReference.target_type == "model",
            )
            .values(target_id="13", slot_key=active_model_slot)
        )
        await session.execute(
            sa.update(BusinessReferenceSet)
            .where(BusinessReferenceSet.source_version == active_version)
            .values(digest=reference_set_digest(active_refs))
        )
        assert await session.scalar(sa.select(App.current_version_id).where(App.id == "actual-app")) == active_version
        assert await session.scalar(sa.select(LLMModel.id).where(LLMModel.model_name == "alpha")) == 11

    active_declaration = await bus.load_effective_declaration("actual-app", principal=native_gateway.identity)
    assert active_declaration.version_id == active_version
    assert active_declaration.model_names == frozenset({"root/slash"})
    # Restore the real current-task lookup replaced by the shared older fixture.
    monkeypatch.setattr(reference_source_owner, "pending_app_reviews", pending_app_reviews)
    config = entry._OBOSigningConfig("native-preview-obo-test-key", "separate-session-test-key", "native-test", 3600)
    monkeypatch.setattr(entry, "_obo_signing_snapshot", lambda: config)
    obo, _ = entry._issue_obo_token(
        app_id="actual-app", user_id=22, tenant_id=101, subject_kind="user", preview_session="actual-preview"
    )
    verified = entry.verify_obo_claims(obo, app_id="actual-app", tenant_id=101)
    original = native_gateway.identity.model_copy(update={"credential_id": 19})
    preview = await bind_preview_principal(original, verified)
    assert (preview.preview_version_id, preview.preview_viewer_user_id, preview.preview_capability_user_id) == (
        preview_version,
        22,
        4,
    )
    request = Request({"type": "http", "headers": [(b"x-bisheng-access-token", obo.encode())]})
    token = set_current_open_api_principal(preview)
    try:
        declaration = await bus.load_effective_declaration("actual-app", principal=preview)
        assert declaration.version_id == preview_version and declaration.model_names == frozenset({"alpha"})
        with pytest.raises(RuntimeError, match="provider boundary"):
            await gateway.ModelGatewayService.complete(
                preview, request, ChatCompletionRequest(model="alpha", messages=[{"role": "user", "content": "hi"}])
            )
        assert native_gateway.provider.await_args.args[0] is preview
        assert native_gateway.provider.await_args.args[1].model_id == 11
        native_gateway.provider.reset_mock()
        # The same preview cannot borrow the active version's distinct model slot.
        with pytest.raises(BaseErrorCode):
            await gateway.ModelGatewayService.complete(
                preview,
                request,
                ChatCompletionRequest(model="root/slash", messages=[{"role": "user", "content": "hi"}]),
            )
        native_gateway.provider.assert_not_awaited()
        # Fresh name resolution may now point alpha at the active model's ID;
        # that still cannot replace the pending version's frozen model/11.
        async with AsyncSession(native_gateway.engine) as session, session.begin():
            await session.execute(sa.update(LLMModel).where(LLMModel.id == 11).values(model_name="preview-old"))
            await session.execute(sa.update(LLMModel).where(LLMModel.id == 13).values(model_name="alpha"))
        model_catalog.invalidate_catalog()
        assert (await model_catalog.resolve_model_name(101, "alpha")).model_id == 13
        with pytest.raises(ModelFaceModelRevokedError):
            await gateway.ModelGatewayService.complete(
                preview, request, ChatCompletionRequest(model="alpha", messages=[{"role": "user", "content": "hi"}])
            )
        native_gateway.provider.assert_not_awaited()
        async with AsyncSession(native_gateway.engine) as session, session.begin():
            await session.execute(sa.update(LLMModel).where(LLMModel.id == 11).values(model_name="alpha"))
            await session.execute(sa.update(LLMModel).where(LLMModel.id == 13).values(model_name="root/slash"))
        model_catalog.invalidate_catalog()
        # Each current fact is independently required; restoring it permits the
        # next check to reach its own real credential/operation/route/task query.
        for model, key, changed, restored in (
            (ApiCredential, 19, {"revoked_at": now}, {"revoked_at": None}),
            (RuntimeOperation, "preview-op", {"status": "cancelled"}, {"status": "running"}),
            (RuntimeRoute, "preview-route", {"generation": 9}, {"generation": 2}),
            (ApprovalTask, 62, {"status": "approved"}, {"status": "pending"}),
        ):
            async with AsyncSession(native_gateway.engine) as session, session.begin():
                await session.execute(sa.update(model).where(model.id == key).values(**changed))
            with pytest.raises(OpenApiCredentialInvalidError):
                await gateway.ModelGatewayService.complete(
                    preview, request, ChatCompletionRequest(model="alpha", messages=[{"role": "user", "content": "hi"}])
                )
            native_gateway.provider.assert_not_awaited()
            async with AsyncSession(native_gateway.engine) as session, session.begin():
                await session.execute(sa.update(model).where(model.id == key).values(**restored))
    finally:
        reset_current_open_api_principal(token)
    native_gateway.auth.assert_not_awaited()
    native_gateway.pending.assert_not_awaited()
