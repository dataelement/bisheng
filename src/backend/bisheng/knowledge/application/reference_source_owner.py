"""Knowledge owns its current model slots and original resource authorization."""

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeNotExistError,
    KnowledgeOperationPlanConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.services.model_reference_extractor import (
    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    extract_knowledge_model_references,
)
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.resource_reference.application.contracts import SourceKey, SourceType, canonical_target_id
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    canonical_payload_json,
    payload_digest,
)
from bisheng.utils.async_utils import run_async_safe


class KnowledgeReferenceSourceOwner:
    def __init__(self, repository=None, identity_port=None):
        self.repository = repository if repository is not None else KnowledgeModelReferenceRepository()
        self.identity_port = identity_port

    @staticmethod
    def _request(request):
        if (
            not isinstance(request, SourceReadRequest)
            or request.source_type != SourceType.KNOWLEDGE
            or request.source_version not in {None, "current"}
            or request.inspect_token is not None
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_model_source_request_invalid")
        try:
            return int(canonical_target_id(request.source_id))
        except ValueError as error:
            raise ResourceReferenceInvalidError(reason="knowledge_model_source_request_invalid") from error

    def _actor(self, session, request, identity):
        knowledge_id = self._request(request)
        if isinstance(identity, UserPayload):
            return knowledge_id, None
        if self.identity_port is None or request.purpose != "execute":
            raise ResourceReferenceInvalidError(reason="knowledge_model_original_identity_required")
        return knowledge_id, self.identity_port.assert_source(session, identity, knowledge_id)

    @staticmethod
    async def _authorize(identity, row, actor):
        if not isinstance(identity, UserPayload) and row["tenant_id"] != identity.tenant_id:
            raise ResourceReferenceInvalidError(reason="knowledge_model_internal_source_not_owned")
        arguments = {
            "resource_type": "knowledge_space" if row["type"] == KnowledgeTypeEnum.SPACE.value else "knowledge_library",
            "resource_id": row["id"],
            "action": "visible",
        }
        if isinstance(identity, UserPayload):
            await require_business_action(identity, **arguments)
        # A private identity admits only owned model configuration. It is not a
        # KN data/visible grant: original AS/WF and retrieval authorization stays
        # in the upstream consumer, including knowledge_auth=False semantics.

    @staticmethod
    def _snapshot(row):
        if row is None:
            raise KnowledgeNotExistError()
        references = extract_knowledge_model_references(model=row["model"], model_transition=row["model_transition"])
        try:
            payload = canonical_payload_json({"knowledge": row})
            return AuthorizedSourceSnapshot(
                SourceKey(row["tenant_id"], SourceType.KNOWLEDGE, str(row["id"]), "current"),
                references,
                KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
                payload_digest(payload),
                payload,
            )
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="knowledge_model_source_configuration") from error

    def resolve_source(self, session, request, identity):
        knowledge_id, actor = self._actor(session, request, identity)
        row = self.repository.load_source(session, knowledge_id)
        if row is None:
            raise KnowledgeNotExistError()
        if isinstance(identity, UserPayload):
            run_async_safe(self._authorize(identity, row, actor))
        elif row["tenant_id"] != identity.tenant_id:
            raise ResourceReferenceInvalidError(reason="knowledge_model_internal_source_not_owned")
        return self._snapshot(row)

    async def aresolve_source(self, session, request, identity):
        knowledge_id, actor = self._actor(session, request, identity)
        row = await self.repository.aload_source(session, knowledge_id)
        if row is None:
            raise KnowledgeNotExistError()
        await self._authorize(identity, row, actor)
        return self._snapshot(row)

    def revalidate_source(self, session, request, identity, expected):
        knowledge_id, actor = self._actor(session, request, identity)
        row = self.repository.load_source(session, knowledge_id, for_update=True)
        return self._revalidate(identity, row, actor, expected)

    def _revalidate(self, identity, row, actor, expected):
        if row is None:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_source_changed")
        if isinstance(identity, UserPayload):
            run_async_safe(self._authorize(identity, row, actor))
        elif row["tenant_id"] != identity.tenant_id:
            raise ResourceReferenceInvalidError(reason="knowledge_model_internal_source_not_owned")
        current = self._snapshot(row)
        if not isinstance(expected, AuthorizedSourceSnapshot) or current != expected:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_source_changed")
        return current

    async def arevalidate_source(self, session, request, identity, expected):
        knowledge_id, actor = self._actor(session, request, identity)
        row = await self.repository.aload_source(session, knowledge_id, for_update=True)
        if row is None:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_source_changed")
        await self._authorize(identity, row, actor)
        current = self._snapshot(row)
        if not isinstance(expected, AuthorizedSourceSnapshot) or current != expected:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_source_changed")
        return current
