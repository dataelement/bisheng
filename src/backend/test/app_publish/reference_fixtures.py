"""Explicit SQL source setup for legacy capability tests; never installed in production."""

from dataclasses import dataclass

import pytest
import sqlalchemy as sa

from bisheng.app_publish.domain.repositories import preview_runtime_repository
from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
from bisheng.app_publish.domain.services.capability_bus_service import derive_scopes
from bisheng.app_publish.domain.services.reference_extractor import (
    APP_REFERENCE_EXTRACTOR_VERSION,
    extract_app_reference_requests,
)
from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding, RuntimeOperation, RuntimeRoute
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.open_api.domain.context import set_current_open_api_principal
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.permission.application.identity import (
    PermissionActor,
    set_current_permission_actor,
)
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey, TargetType, reference_set_digest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone


@dataclass(frozen=True)
class BoundSource:
    app: object
    version: object
    principal: object
    plaintext: str


async def delete_knowledge_target(session, knowledge):
    """Explicit durable deletion evidence for the selected seeded physical target."""
    await session.delete(await session.get(Knowledge, knowledge.id))
    session.add(
        ResourceReferenceTombstone(
            tenant_id=knowledge.tenant_id,
            target_type="knowledge_space",
            target_id=str(knowledge.id),
            target_tenant_id=knowledge.tenant_id,
            operation_id=f"fixture-delete:{knowledge.id}",
            operation_type="delete",
            stage="deleted",
            actor_type="user",
            actor_id=str(knowledge.user_id),
        )
    )


@pytest.fixture
async def bind_saved_source(publish_engine, publish_db, credential_redis, hosted_app_resolver, monkeypatch):
    """Bind once, explicitly after configuration setup; later changes must not repair the index."""
    monkeypatch.setattr(settings.app_runtime, "runtime_protocol_version", 1)
    monkeypatch.setattr(settings.open_platform, "enabled", True)
    models = (
        LLMServer,
        LLMModel,
        TenantSystemModelConfig,
        KnowledgeFile,
        BusinessReferenceSet,
        BusinessResourceReference,
        ResourceReferenceTombstone,
        RuntimeRoute,
        RuntimeCredentialBinding,
        RuntimeOperation,
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
    async with publish_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    actual_tables = {model.__tablename__ for model in (*models, App, Knowledge) if "tenant_id" in model.__table__.c}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | actual_tables)
    tenant_filter.register_tenant_filter_events()
    monkeypatch.setattr(preview_runtime_repository, "get_async_db_session", publish_db)
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository
    from bisheng.app_runtime.domain.services import app_authorization_service
    from bisheng.permission.application.identity import get_current_permission_actor

    async def load_app(app_id):
        return await RuntimeDeliveryRepository(publish_db).get_application(app_id)

    async def check(identity, *, resource_type, resource_id, action, actor=None):
        actor = actor or get_current_permission_actor()
        app = await load_app(resource_id)
        return bool(
            app is not None
            and resource_type == "app"
            and actor is not None
            and actor.subject_type == "user"
            and actor.subject_id == app.owner_user_id
            and actor.tenant_id == app.tenant_id
            and getattr(identity, "user_id", None) == actor.subject_id
            and action in {"visible", "edit", "manage_permission", "delete", "publish", "unpublish"}
        )

    async def batch(identity, *, resource_type, resource_ids, actions):
        return {
            app_id: frozenset(
                [
                    action
                    for action in actions
                    if await check(identity, resource_type=resource_type, resource_id=app_id, action=action)
                ]
            )
            for app_id in resource_ids
        }

    # App validity/actor resolution stay real. Only the remote permission verdict
    # is a scoped owner grant, and repository injection uses the actual SQL Repo.
    monkeypatch.setattr(app_authorization_service.AppAuthorizationService, "load_app", staticmethod(load_app))
    monkeypatch.setattr(app_authorization_service, "check_business_action", check)
    monkeypatch.setattr(app_authorization_service, "batch_check_business_actions", batch)

    async def bind(app, version=None, *, model_rows=(), server_name="provider"):
        current_tenant_id.set(int(app.tenant_id))
        async with publish_db() as session, session.begin():
            actual = await session.get(App, app.id)
            saved = await session.get(AppVersion, version.id if version is not None else actual.current_version_id)
            assert saved is not None and saved.app_id == actual.id
            existing = (
                (
                    await session.execute(
                        sa.select(BusinessReferenceSet).where(
                            BusinessReferenceSet.source_id == actual.id,
                            BusinessReferenceSet.source_version == saved.id,
                            BusinessReferenceSet.record_kind == "source",
                        )
                    )
                )
                .scalars()
                .first()
            )
            assert existing is None, "source setup is explicit and once per actual saved UUID"
            declaration = CapabilityDeclaration.model_validate(saved.capabilities or {})
            for model_id, server_id, name, online in model_rows:
                if await session.get(LLMServer, server_id) is None:
                    session.add(LLMServer(id=server_id, tenant_id=actual.tenant_id, name=server_name, type="openai"))
                    await session.flush()
                if await session.get(LLMModel, model_id) is None:
                    session.add(
                        LLMModel(
                            id=model_id,
                            server_id=server_id,
                            tenant_id=actual.tenant_id,
                            model_name=name,
                            model_type="llm",
                            online=online,
                        )
                    )
            await session.flush()
            frozen = []
            for requested in extract_app_reference_requests(declaration):
                if requested.target_type == TargetType.MODEL:
                    rows = (
                        (
                            await session.execute(
                                sa.select(LLMModel).where(LLMModel.model_name == requested.requested_name)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if not rows:
                        if await session.get(LLMServer, 1) is None:
                            session.add(LLMServer(id=1, tenant_id=actual.tenant_id, name=server_name, type="openai"))
                            await session.flush()
                        row = LLMModel(
                            server_id=1,
                            tenant_id=actual.tenant_id,
                            model_name=requested.requested_name,
                            model_type="llm",
                        )
                        session.add(row)
                        await session.flush()
                    else:
                        assert len(rows) == 1
                        row = rows[0]
                    target_id = str(row.id)
                else:
                    rows = (
                        (
                            await session.execute(
                                sa.select(Knowledge).where(
                                    Knowledge.id == int(requested.target_id)
                                    if requested.target_id
                                    else Knowledge.name == requested.requested_name
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert len(rows) == 1, (
                        "ambiguous/missing declarations use draft precheck or explicit migration evidence"
                    )
                    target_id = str(rows[0].id)
                frozen.append(ReferenceSpec(requested.slot_key, TargetKey(requested.target_type, target_id)))
            root = (
                (
                    await session.execute(
                        sa.select(BusinessReferenceSet).where(
                            BusinessReferenceSet.source_id == actual.id,
                            BusinessReferenceSet.record_kind == "root_guard",
                        )
                    )
                )
                .scalars()
                .first()
            )
            if root is None:
                session.add(
                    BusinessReferenceSet(
                        tenant_id=actual.tenant_id,
                        source_type="hosted_app_version",
                        source_id=actual.id,
                        source_version="__root__",
                        record_kind="root_guard",
                        source_revision=1,
                        extractor_version="root-guard-v1",
                        digest=reference_set_digest(()),
                        ready=False,
                        effective=False,
                    )
                )
            session.add(
                BusinessReferenceSet(
                    tenant_id=actual.tenant_id,
                    source_type="hosted_app_version",
                    source_id=actual.id,
                    source_version=saved.id,
                    source_revision=1,
                    extractor_version=APP_REFERENCE_EXTRACTOR_VERSION,
                    digest=reference_set_digest(frozen),
                    ready=True,
                    effective=True,
                )
            )
            for ref in frozen:
                session.add(
                    BusinessResourceReference(
                        tenant_id=actual.tenant_id,
                        source_type="hosted_app_version",
                        source_id=actual.id,
                        source_version=saved.id,
                        slot_key=ref.slot_key,
                        target_type=ref.target.target_type.value,
                        target_id=ref.target.target_id,
                        target_tenant_id=actual.tenant_id,
                        source_revision=1,
                    )
                )
        plaintext = await AppRuntimeCredentialService.issue(actual.id, scopes=derive_scopes(declaration))
        principal = await validate_bearer(f"Bearer {plaintext}")
        set_current_open_api_principal(principal)
        set_current_permission_actor(
            PermissionActor(
                subject_type=principal.authorization_subject_type,
                subject_id=principal.authorization_subject_id,
                tenant_id=principal.tenant_id,
            )
        )
        return BoundSource(actual, saved, principal, plaintext)

    # The package's autouse context fixture owns ContextVar cleanup. Tokens
    # created by a test callback cannot be reset in the async fixture's Context.
    return bind
