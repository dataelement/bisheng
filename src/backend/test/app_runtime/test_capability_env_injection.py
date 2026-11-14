"""Durable env staging replaces the retired provider callback contract.

Source admission, SQL, original web context and credential staging stay real.
Only storage/control delivery and the separate commit projection are doubles.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet

from bisheng.app_publish.composition import _app_user_reference_runtime
from bisheng.app_publish.domain.models.app_secret_config import AppSecretConfig
from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
from bisheng.app_publish.domain.services.reference_extractor import (
    APP_REFERENCE_EXTRACTOR_VERSION,
    extract_app_reference_requests,
)
from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding, RuntimeOperation, RuntimeRoute
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.services import app_authorization_service, runtime_env_ports
from bisheng.app_runtime.domain.services.app_state_service import AppStateService
from bisheng.app_runtime.domain.services.app_storage_service import AppStorageService
from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService
from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.app_runtime.domain.services.runtime_payload import unseal
from bisheng.common.services.config_service import settings
from bisheng.core.database import tenant_filter
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.database.models.tenant import Tenant
from bisheng.database.models.user_role import UserRole
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceType, TargetKey, reference_set_digest
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def delivery(app_db, app_factory, app_owner, monkeypatch):
    from bisheng.user.domain.models import user_role
    from bisheng.user.domain.repositories import runtime_identity

    runtime_env_ports.clear_capability_env_provider()
    monkeypatch.setattr(settings.app_runtime, "runtime_protocol_version", 1)
    monkeypatch.setattr(settings.app_runtime, "runtime_platform_base_url", "https://platform.test")
    monkeypatch.setattr(settings.app_runtime, "runtime_payload_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings.open_platform, "enabled", True)
    for module in (user_role, runtime_identity):
        monkeypatch.setattr(module, "get_async_db_session", app_db)
    models = (
        RuntimeOperation,
        RuntimeRoute,
        RuntimeCredentialBinding,
        AppSecretConfig,
        HostedAppSubject,
        ApiCredential,
        UserRole,
        LLMModel,
        LLMServer,
        TenantSystemModelConfig,
        BusinessReferenceSet,
        BusinessResourceReference,
        ResourceReferenceTombstone,
        Knowledge,
        KnowledgeFile,
    )
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
    async with app_db() as session:
        await (await session.connection()).run_sync(metadata.create_all)
        await session.commit()
    actual = {model.__tablename__ for model in (*models, App) if "tenant_id" in model.__table__.c}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | actual)
    tenant_filter.register_tenant_filter_events()
    user = app_owner.payload
    before = user._runtime_credential_reference
    user._runtime_credential_reference = {
        "kind": "web_session",
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "token_version": user.token_version,
        "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
    }
    actor_token = set_current_permission_actor(
        PermissionActor(subject_type="user", subject_id=user.user_id, tenant_id=user.tenant_id)
    )
    principal_token = set_current_open_api_principal(None)

    async def check(identity, *, resource_type, resource_id, action, actor=None):
        async with app_db() as session:
            app = await session.get(App, resource_id)
        return bool(
            app
            and resource_type == "app"
            and identity.user_id == user.user_id == app.owner_user_id
            and actor.subject_id == user.user_id
            and actor.tenant_id == app.tenant_id
            and action == "publish"
        )

    monkeypatch.setattr(app_authorization_service, "check_business_action", check)
    storage = AsyncMock(side_effect=lambda op, **kw: {"env": {"BISHENG_STORAGE_URL": f"storage:{op.app_id}"}})
    monkeypatch.setattr(AppStorageService, "issue", storage)
    commit = AsyncMock()
    monkeypatch.setattr(AppStateService, "commit_runtime_delivery", commit)
    calls = []
    real_stage = AppRuntimeCredentialService.stage_in_transaction.__func__

    async def stage(cls, app_id, *, operation, session, scopes=()):
        calls.append((operation.id, tuple(scopes), session))
        return await real_stage(cls, app_id, operation=operation, session=session, scopes=scopes)

    monkeypatch.setattr(AppRuntimeCredentialService, "stage_in_transaction", classmethod(stage))

    async def make(*, future_models=False, environment=None):
        app, current = await app_factory(state="pending_capacity")
        async with app_db() as session, session.begin():
            if await session.get(Tenant, user.tenant_id) is None:
                session.add(Tenant(id=user.tenant_id, tenant_code="root", tenant_name="Root"))
            version = current
            if future_models:
                version = AppVersion(
                    app_id=app.id,
                    version_no=2,
                    kind="iteration",
                    code_object_key="future-code",
                    manifest={"runtime": "python3.11"},
                    capabilities={"models": [{"name": "future-model"}]},
                    injections={},
                    tier_id="light",
                    runtime="python3.11",
                )
                session.add(version)
                await session.flush()
                app.pending_version_id = version.id
                session.add(app)
                session.add(LLMServer(id=1, tenant_id=app.tenant_id, name="provider", type="openai"))
                session.add(
                    LLMModel(id=11, tenant_id=app.tenant_id, server_id=1, model_name="future-model", model_type="llm")
                )
            version.injections = {"env": environment or {}}
            session.add(version)
            session.add(
                BusinessReferenceSet(
                    tenant_id=app.tenant_id,
                    source_type="hosted_app_version",
                    source_id=app.id,
                    source_version="__root__",
                    record_kind="root_guard",
                    source_revision=1,
                    extractor_version="root-guard-v1",
                    digest=reference_set_digest(()),
                    ready=False,
                    effective=False,
                )
            )
            for saved in (current, version) if current.id != version.id else (version,):
                refs = tuple(
                    ReferenceSpec(one.slot_key, TargetKey(one.target_type, "11"))
                    for one in extract_app_reference_requests(
                        CapabilityDeclaration.model_validate(saved.capabilities or {})
                    )
                )
                session.add(
                    BusinessReferenceSet(
                        tenant_id=app.tenant_id,
                        source_type="hosted_app_version",
                        source_id=app.id,
                        source_version=saved.id,
                        source_revision=1,
                        extractor_version=APP_REFERENCE_EXTRACTOR_VERSION,
                        digest=reference_set_digest(refs),
                        ready=True,
                        effective=True,
                    )
                )
                for ref in refs:
                    session.add(
                        BusinessResourceReference(
                            tenant_id=app.tenant_id,
                            source_type="hosted_app_version",
                            source_id=app.id,
                            source_version=saved.id,
                            source_revision=1,
                            slot_key=ref.slot_key,
                            target_type=ref.target.target_type.value,
                            target_id=ref.target.target_id,
                            target_tenant_id=app.tenant_id,
                        )
                    )
        context = await RuntimeAuthorizationService.capture_user(user, app, "approved_start", version_id=version.id)
        runtime = _app_user_reference_runtime(context)
        async with app_db() as session, session.begin():
            scope = await runtime.verifier.aissue_scope(
                session, SourceReadRequest(SourceType.HOSTED_APP_VERSION, app.id, version.id), user
            )
            result = await runtime.arequire_source_valid(session, scope, user)
            assert result.snapshot.source_key.source_version == version.id
        operation = RuntimeOperation(
            tenant_id=app.tenant_id,
            app_id=app.id,
            scope_key=f"{app.tenant_id}/{app.id}",
            idempotency_key="env",
            request_digest="0" * 64,
            version_id=version.id,
            kind="deploy",
            node_id="node",
            deadline=datetime.utcnow() + timedelta(hours=1),
            status="running",
            payload={"authorization_context": context},
        )
        async with app_db() as session, session.begin():
            session.add(operation)
            await session.flush()
            session.add(
                RuntimeRoute(
                    tenant_id=app.tenant_id,
                    app_id=app.id,
                    route_key=f"app:{app.id}",
                    version_id=version.id,
                    operation_id=operation.id,
                    node_id="node",
                    exec_ref="ready-instance",
                    generation=1,
                    owner_epoch=1,
                    status="stopped",
                )
            )
        repo = RuntimeDeliveryRepository(app_db)
        coordinator = RuntimeDeliveryCoordinator(repo)
        coordinator.wake = AsyncMock()
        coordinator.wait = AsyncMock(return_value={"stage": "serving"})
        return SimpleNamespace(
            app=app,
            current=current,
            version=version,
            operation=operation,
            repo=repo,
            coordinator=coordinator,
            calls=calls,
            commit=commit,
            user=user,
            app_db=app_db,
        )

    try:
        yield make
    finally:
        user._runtime_credential_reference = before
        reset_current_permission_actor(actor_token)
        reset_current_open_api_principal(principal_token)
        runtime_env_ports.clear_capability_env_provider()


async def deploy(context):
    return await context.coordinator.deploy(
        context.app,
        context.version,
        {"cpu": 1, "mem": 1024},
        authorization_context=context.operation.payload["authorization_context"],
    )


async def environment(context):
    operation = await context.repo.get(RuntimeOperation, context.operation.id)
    return unseal(operation.payload["sealed_env"])


async def test_no_legacy_provider_still_stages_platform_storage_and_application_identity(delivery):
    context = await delivery()
    await deploy(context)
    env = await environment(context)
    assert env["BISHENG_PLATFORM_API_BASE"] == "https://platform.test"
    assert env["BISHENG_STORAGE_URL"] == f"storage:{context.app.id}"
    assert env["BISHENG_APP_TOKEN"].startswith("bs-app-") and "OPENAI_API_KEY" not in env
    assert context.calls[0][1] == ()
    assert context.operation.payload["authorization_context"]["actor"]["subject_id"] == context.user.user_id
    context.coordinator.wake.assert_awaited_once()


async def test_selected_saved_version_drives_scopes_not_current_version(delivery):
    context = await delivery(future_models=True)
    assert context.app.current_version_id == context.current.id != context.version.id
    await deploy(context)
    env = await environment(context)
    assert context.calls[0][1] == ("model:invoke",)
    assert env["OPENAI_API_KEY"] == env["BISHENG_APP_TOKEN"]
    async with context.app_db() as session, session.begin():
        binding = (await session.execute(sa.select(RuntimeCredentialBinding))).scalars().one()
        assert binding.version_id == context.version.id and binding.operation_id == context.operation.id


async def test_platform_reserved_names_override_version_environment(delivery):
    context = await delivery(
        environment={"BISHENG_APP_TOKEN": "stale", "BISHENG_STORAGE_URL": "old", "APP_OWN_FLAG": "1"}
    )
    await deploy(context)
    env = await environment(context)
    assert env["BISHENG_APP_TOKEN"] != "stale" and env["BISHENG_APP_TOKEN"].startswith("bs-app-")
    assert env["BISHENG_STORAGE_URL"] == f"storage:{context.app.id}" and env["APP_OWN_FLAG"] == "1"


@pytest.mark.parametrize("failure", ["stage", "seal"])
async def test_environment_failure_rolls_back_identity_and_never_wakes(delivery, monkeypatch, failure):
    context = await delivery()
    if failure == "stage":
        original = AppRuntimeCredentialService.stage_in_transaction.__func__

        async def failed(cls, *args, **kwargs):
            await original(cls, *args, **kwargs)
            raise RuntimeError("synthetic stage failure")

        monkeypatch.setattr(AppRuntimeCredentialService, "stage_in_transaction", classmethod(failed))
        error, match = RuntimeError, "synthetic stage failure"
    else:
        monkeypatch.setattr(settings.app_runtime, "runtime_payload_key", "invalid")
        error, match = RuntimeConflict, "runtime_payload_key_required"
    with pytest.raises(error, match=match):
        await deploy(context)
    operation = await context.repo.get(RuntimeOperation, context.operation.id)
    assert "sealed_env" not in operation.payload
    async with context.app_db() as session, session.begin():
        for model in (ApiCredential, HostedAppSubject, RuntimeCredentialBinding):
            assert not (await session.execute(sa.select(model))).scalars().all()
    context.coordinator.wake.assert_not_awaited()
    context.coordinator.wait.assert_not_awaited()
    context.commit.assert_not_awaited()


async def test_legacy_registry_remains_an_explicit_compatibility_helper():
    runtime_env_ports.clear_capability_env_provider()
    assert set(runtime_env_ports.__all__) == {
        "CapabilityEnvProvider",
        "capability_env",
        "clear_capability_env_provider",
        "register_capability_env_provider",
    }
    assert await runtime_env_ports.capability_env(app_id="x", capabilities={}) == {}
