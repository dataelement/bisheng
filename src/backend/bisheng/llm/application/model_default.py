"""Default configurations and R2 bindings share the caller's transaction."""

import json
from dataclasses import dataclass

from pydantic import BaseModel

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.llm import WorkbenchChatDefaultModelError, WorkbenchEmbeddingError
from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    MODEL_DEFAULT_SCHEMAS,
    extract_model_default_references,
)
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
from bisheng.permission.application.identity import PermissionActor, resolve_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.access import get_reference_binding_runtime
from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    SourceBindingChange,
    SourceKey,
    TargetKey,
    canonical_target_id,
    reference_set_digest,
)
from bisheng.resource_reference.application.source_contracts import canonical_payload_json


def current_model_default_tenant(expected=None):
    try:
        tenant = _resolve_tenant_id()
    except NoTenantContextError as error:
        raise ResourceReferenceInvalidError(reason="model_default_tenant_required") from error
    if (
        type(tenant) is not int
        or tenant <= 0
        or is_tenant_filter_bypassed()
        or (expected is not None and (type(expected) is not int or expected != tenant))
    ):
        raise ResourceReferenceInvalidError(reason="model_default_tenant_required")
    return tenant


@dataclass(frozen=True, slots=True)
class ModelDefaultSaveResult:
    config: BaseModel
    commands: tuple
    embedding_changed: bool = False


class ModelDefaultApplication:
    @staticmethod
    async def _authorize(login_user, tenant):
        if (
            not isinstance(login_user, UserPayload)
            or get_current_open_api_principal() is not None
            or get_current_public_api_principal() is not None
        ):
            raise LLMSystemConfigForbiddenError()
        actor = await resolve_permission_actor(login_user)
        if (
            not isinstance(actor, PermissionActor)
            or actor.subject_type != "user"
            or actor.subject_id != login_user.user_id
            or actor.data_scope != DATA_SCOPE_ALL
        ):
            raise LLMSystemConfigForbiddenError()
        if actor.super_admin:
            return
        if actor.current_tenant_id != tenant or tenant == ROOT_TENANT_ID or tenant not in actor.tenant_admin_tenant_ids:
            raise LLMSystemConfigForbiddenError()

    @staticmethod
    def _config(key, payload, own):
        if key not in MODEL_DEFAULT_SCHEMAS:
            raise ResourceReferenceInvalidError(reason="model_default_key_invalid")
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        if not isinstance(payload, dict):
            raise ResourceReferenceInvalidError(reason="model_default_configuration_invalid")
        config = MODEL_DEFAULT_SCHEMAS[key].model_validate(payload)
        if key == "linsight_llm":
            if config.models is None:
                original = (
                    MODEL_DEFAULT_SCHEMAS[key].model_validate_json(own.payload_json)
                    if own is not None
                    else MODEL_DEFAULT_SCHEMAS[key]()
                )
                config.models = original.models
            if config.embedding_model is not None:
                try:
                    config.embedding_model.id = canonical_target_id(config.embedding_model.id)
                except (TypeError, ValueError) as error:
                    raise WorkbenchEmbeddingError() from error
            if config.chat_default_model_id is not None:
                choices = {canonical_target_id(item.id) for item in config.models or ()}
                if canonical_target_id(config.chat_default_model_id) not in choices:
                    raise WorkbenchChatDefaultModelError()
        return config

    @staticmethod
    async def _old_source(session, runtime, key, own):
        current = await runtime.repository.aget_source_set(session, key)
        rows = await runtime.repository.alist_source_references(session, key)
        if current is None:
            if own is not None or rows:
                raise ReferenceCoverageNotReadyError(reason="source_not_indexed")
            return True
        try:
            raw = tuple(ReferenceSpec(row.slot_key, TargetKey(row.target_type, row.target_id)) for row in rows)
            old = (
                extract_model_default_references(key.source_id, json.loads(own.payload_json)) if own is not None else ()
            )
            valid = (
                current.ready
                and current.record_kind == "source"
                and current.source_revision > 0
                and current.extractor_version == MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION
                and current.digest == reference_set_digest(raw) == reference_set_digest(old)
                and all(row.source_revision == current.source_revision for row in rows)
                and current.effective == bool(own is not None and own.value)
            )
        except (TypeError, ValueError, ResourceReferenceInvalidError) as error:
            raise ReferenceCoverageNotReadyError(reason="source_configuration_drift") from error
        if not valid:
            raise ReferenceCoverageNotReadyError(reason="source_configuration_drift")
        return False

    @staticmethod
    def _embedding_id(config):
        return canonical_target_id(config.embedding_model.id) if config.embedding_model is not None else None

    @classmethod
    async def _asave(cls, session, key, payload, *, login_user, operation_id=None, allow_commands=False):
        tenant = current_model_default_tenant()
        await cls._authorize(login_user, tenant)
        repository = ModelDefaultRepository()
        own = await repository.aget_own(session, key)
        effective = await repository.aresolve(session, key) if key == "linsight_llm" else None
        if effective is not None and effective.own != own:
            raise KnowledgeOperationPlanConflictError(reason="model_default_changed")
        config = cls._config(key, payload, effective.source if effective is not None else own)
        try:
            references = extract_model_default_references(key, config)
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="model_default_configuration_invalid") from error
        source = SourceKey(tenant, "model_default", key, "current")
        runtime = await get_reference_binding_runtime()
        new_source = await cls._old_source(session, runtime, source, own)
        batch, knowledge = None, None
        embedding_changed = False
        if effective is not None:
            original = MODEL_DEFAULT_SCHEMAS[key].model_validate_json(effective.payload_json)
            selected = cls._embedding_id(config)
            embedding_changed = selected is not None and selected != cls._embedding_id(original)
            if embedding_changed:
                from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication

                knowledge = KnowledgeModelReferenceApplication
                batch = await knowledge.aplan_workbench_model_changes(
                    session, selected, login_user=login_user, operation_id=operation_id
                )
                if batch.commands and not allow_commands:
                    raise ResourceReferenceInvalidError(reason="workbench_model_change_requires_command_owner")

        async def lock_root(active_session):
            if batch is not None:
                await batch.alock_inventory(active_session)
            current = await repository.alock_root(active_session, key)
            await cls._authorize(login_user, tenant)
            if current != own:
                raise KnowledgeOperationPlanConflictError(reason="model_default_changed")
            if effective is not None and await repository.aresolve(active_session, key, for_update=True) != effective:
                raise KnowledgeOperationPlanConflictError(reason="model_default_changed")

        if batch is None:
            prepared = await runtime.aprepare_source_bindings(
                session,
                source,
                references,
                extractor_version=MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
                lock_source_root=lock_root,
                new_source=new_source,
            )
        else:
            change = SourceBindingChange(
                source, references, MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION, lock_root, new_source=new_source
            )
            prepared_sources = await runtime.aprepare_mixed_source_bindings(session, (*batch.changes, change))
            await knowledge.aapply_workbench_model_changes(session, batch, prepared_sources)
            prepared = next(item for item in prepared_sources if item.source_key == source)
        await repository.aput(session, key, canonical_payload_json(config.model_dump(mode="json")))
        await runtime.aapply_source_bindings(session, prepared)
        return ModelDefaultSaveResult(config, batch.commands if batch is not None else (), embedding_changed)

    @classmethod
    async def asave(cls, session, key, payload, *, login_user):
        return (await cls._asave(session, key, payload, login_user=login_user)).config

    @classmethod
    async def asave_with_commands(cls, session, key, payload, *, login_user, operation_id=None):
        return await cls._asave(
            session, key, payload, login_user=login_user, operation_id=operation_id, allow_commands=True
        )

    @classmethod
    async def arestore_inheritance(cls, session, key, *, login_user):
        tenant = current_model_default_tenant()
        if tenant == ROOT_TENANT_ID:
            raise LLMSystemConfigForbiddenError()
        await cls._authorize(login_user, tenant)
        repository = ModelDefaultRepository()
        own = await repository.aget_own(session, key)
        source = SourceKey(tenant, "model_default", key, "current")
        runtime = await get_reference_binding_runtime()
        new_source = await cls._old_source(session, runtime, source, own)
        if own is None and new_source:
            # A consumer that only inherits Root never acquires its own index.
            return await repository.aresolve(session, key)

        async def lock_root(active_session):
            current = await repository.alock_root(active_session, key)
            await cls._authorize(login_user, tenant)
            if current != own:
                raise KnowledgeOperationPlanConflictError(reason="model_default_changed")

        prepared = await runtime.aprepare_source_bindings(
            session,
            source,
            (),
            extractor_version=MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
            effective=False,
        )
        await repository.adelete_override(session, key)
        await runtime.aapply_source_bindings(session, prepared)
        return await repository.aresolve(session, key)
