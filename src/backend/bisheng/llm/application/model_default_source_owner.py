"""Resolve defaults from actual own/Root storage, never a claimed source tenant."""

import json

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    MODEL_DEFAULT_SCHEMAS,
    extract_model_default_references,
)
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    payload_digest,
)


class ModelDefaultSourceOwner:
    def __init__(self, repository=None, *, identity_port):
        self.repository = repository if repository is not None else ModelDefaultRepository()
        self.identity_port = identity_port

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
