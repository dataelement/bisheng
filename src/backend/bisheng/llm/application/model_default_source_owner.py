"""Resolve defaults from actual own/Root storage, never a claimed source tenant."""

import json

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    MODEL_DEFAULT_SCHEMAS,
    extract_model_default_references,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.resource_reference.application.contracts import SourceKey, SourceType, TransactionIdentity
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    payload_digest,
)
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure

_SETTING_TABS = {
    "knowledge_llm": "knowledge",
    "assistant_llm": "assis",
    "evaluation_llm": "evaluation",
    "workflow_llm": "workflow",
    "linsight_llm": "workbench",
}


class ModelDefaultSourceOwner:
    def __init__(self, repository=None, *, identity_port):
        self.repository = repository if repository is not None else ModelDefaultRepository()
        self.identity_port = identity_port

    async def adisclose_sources(self, session, *, identity, source_keys: tuple[SourceKey, ...]):
        if (
            type(source_keys) is not tuple
            or len(source_keys) > 200
            or any(
                not isinstance(key, SourceKey)
                or key.source_type != SourceType.MODEL_DEFAULT
                or key.source_id not in MODEL_DEFAULT_SCHEMAS
                or key.source_version != "current"
                for key in source_keys
            )
        ):
            raise ReferenceCoverageNotReadyError(reason="default_disclosure_invalid_batch")
        if not source_keys:
            return ()
        try:
            tenant = _resolve_tenant_id()
            if (
                not isinstance(identity, UserPayload)
                or type(tenant) is not int
                or tenant <= 0
                or is_tenant_filter_bypassed()
            ):
                raise ReferenceCoverageNotReadyError(reason="default_disclosure_original_identity_required")
            keys = tuple(dict.fromkeys(key.source_id for key in source_keys if key.tenant_id == tenant))
            if not keys:
                return (None,) * len(source_keys)
            actor = await resolve_permission_actor(identity)
            original = self.identity_port.issue_identity(identity)
            before = await self.identity_port.acapture(original)
            transaction = TransactionIdentity.capture(session)
            rows = await self.repository.alist_disclosure_rows(session, keys=keys)
            by_key = {row.key: row for row in rows}
            if set(by_key) != set(keys) or any(row.tenant_id != tenant for row in rows):
                raise ReferenceCoverageNotReadyError(reason="default_disclosure_source_missing")
            # Names follow the five existing authenticated GETs. The management
            # link follows the existing settings administrator boundary only.
            manage = actor.subject_type == "user" and (
                actor.super_admin or (tenant != ROOT_TENANT_ID and tenant in actor.tenant_admin_tenant_ids)
            )
            if await self.identity_port.acapture(original) != before:
                raise ReferenceCoverageNotReadyError(reason="default_disclosure_identity_changed")
            transaction.assert_current(session)
            return tuple(
                SourceDisclosure(
                    key,
                    by_key[key.source_id].key,
                    None,
                    f"/model/management?systemModel={_SETTING_TABS[key.source_id]}" if manage else None,
                )
                if key.tenant_id == tenant
                else None
                for key in source_keys
            )
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="default_disclosure_failed") from error

    @staticmethod
    def _request(request):
        if (
            not isinstance(request, SourceReadRequest)
            or request.source_type != SourceType.MODEL_DEFAULT
            or request.source_id not in MODEL_DEFAULT_SCHEMAS
            or request.source_version not in {None, "current"}
            or request.inspect_token is not None
        ):
            raise ResourceReferenceInvalidError(reason="model_default_source_request")
        return request.source_id

    @staticmethod
    def _snapshot(resolved):
        if resolved.source is None:
            raise ResourceReferenceInvalidError(reason="model_default_not_configured")
        payload = resolved.payload_json
        try:
            references = extract_model_default_references(resolved.key, json.loads(payload))
            return AuthorizedSourceSnapshot(
                resolved.source.source_key,
                references,
                MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
                payload_digest(payload),
                payload,
            )
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="model_default_configuration_invalid") from error

    def resolve_source(self, session, request, identity):
        self.identity_port.capture(identity)
        return self._snapshot(self.repository.resolve(session, self._request(request)))

    async def aresolve_source(self, session, request, identity):
        await self.identity_port.acapture(identity)
        return self._snapshot(await self.repository.aresolve(session, self._request(request)))

    def revalidate_source(self, session, request, identity, expected):
        self.identity_port.capture(identity)
        key = self._request(request)
        try:
            current = self._snapshot(self.repository.resolve(session, key, for_update=True))
        except ResourceReferenceInvalidError as error:
            raise KnowledgeOperationPlanConflictError(reason="model_default_source_changed") from error
        if current != expected:
            raise KnowledgeOperationPlanConflictError(reason="model_default_source_changed")
        return current

    async def arevalidate_source(self, session, request, identity, expected):
        await self.identity_port.acapture(identity)
        key = self._request(request)
        try:
            current = self._snapshot(await self.repository.aresolve(session, key, for_update=True))
        except ResourceReferenceInvalidError as error:
            raise KnowledgeOperationPlanConflictError(reason="model_default_source_changed") from error
        if current != expected:
            raise KnowledgeOperationPlanConflictError(reason="model_default_source_changed")
        return current
