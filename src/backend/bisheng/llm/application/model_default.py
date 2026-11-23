"""Default configurations and R2 bindings share the caller's transaction."""

import json
from dataclasses import dataclass

from pydantic import BaseModel

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.llm import WorkbenchChatDefaultModelError, WorkbenchEmbeddingError
from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.application.model_selection import require_new_models
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_SCHEMAS,
    extract_model_default_references,
    model_default_models_are_callable,
)
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
from bisheng.permission.application.identity import PermissionActor, resolve_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.contracts import (
    canonical_target_id,
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
                try:
                    selected = canonical_target_id(config.chat_default_model_id)
                except (TypeError, ValueError) as error:
                    raise WorkbenchChatDefaultModelError() from error
                try:
                    choices = {canonical_target_id(item.id) for item in config.models or ()}
                except (TypeError, ValueError) as error:
                    raise ResourceReferenceInvalidError(reason="model_default_configuration_invalid") from error
                if selected not in choices:
                    raise WorkbenchChatDefaultModelError()
        return config

    @staticmethod
    def _embedding_id(config):
        return canonical_target_id(config.embedding_model.id) if config.embedding_model is not None else None

    @classmethod
    async def _asave(cls, session, key, payload, *, login_user):
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
        embedding_changed = False
        if effective is not None:
            original = MODEL_DEFAULT_SCHEMAS[key].model_validate_json(effective.payload_json)
            selected = cls._embedding_id(config)
            embedding_changed = selected is not None and selected != cls._embedding_id(original)

        async def lock_root(active_session):
            current = await repository.alock_root(active_session, key)
            await cls._authorize(login_user, tenant)
            if current != own:
                raise KnowledgeOperationPlanConflictError(reason="model_default_changed")
            if effective is not None and await repository.aresolve(active_session, key, for_update=True) != effective:
                raise KnowledgeOperationPlanConflictError(reason="model_default_changed")

        # A default is copied into a space only when that space is created.
        # Saving it never reads or rewrites existing Knowledge roots or R2 slots.
        await lock_root(session)
        old_references = extract_model_default_references(key, json.loads(own.payload_json)) if own is not None else ()
        await require_new_models(session, references, old_references)
        states = await repository.aread_slot_models(
            session, tuple(int(reference.target.target_id) for reference in references)
        )
        # Unchanged missing selections remain editable; new IDs were checked above.
        existing = tuple(reference for reference in references if int(reference.target.target_id) in states)
        if not model_default_models_are_callable(key, existing, states):
            raise ResourceReferenceInvalidError(reason="reference_target_invalid")
        await cls._authorize(login_user, tenant)
        await repository.aput(session, key, canonical_payload_json(config.model_dump(mode="json")))
        return ModelDefaultSaveResult(config, embedding_changed)

    @classmethod
    async def asave(cls, session, key, payload, *, login_user):
        return (await cls._asave(session, key, payload, login_user=login_user)).config

    @classmethod
    async def arestore_inheritance(cls, session, key, *, login_user):
        tenant = current_model_default_tenant()
        if tenant == ROOT_TENANT_ID:
            raise LLMSystemConfigForbiddenError()
        await cls._authorize(login_user, tenant)
        repository = ModelDefaultRepository()
        own = await repository.aget_own(session, key)
        if own is None:
            # A consumer that only inherits Root never acquires its own index.
            return await repository.aresolve(session, key)

        async def lock_root(active_session):
            current = await repository.alock_root(active_session, key)
            await cls._authorize(login_user, tenant)
            if current != own:
                raise KnowledgeOperationPlanConflictError(reason="model_default_changed")

        await lock_root(session)
        await repository.adelete_override(session, key)
        return await repository.aresolve(session, key)
