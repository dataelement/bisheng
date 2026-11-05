"""The assistant Owner authorizes a real persisted source, never a caller DTO."""

from datetime import date, datetime
from enum import Enum

from bisheng.assistant.domain.repositories.reference_source_repository import AssistantReferenceSourceRepository
from bisheng.assistant.domain.services.reference_extractor import (
    ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
    extract_assistant_references,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.assistant import AssistantNotExistsError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    canonical_payload_json,
    payload_digest,
)


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class AssistantReferenceSourceOwner:
    def __init__(self, repository: AssistantReferenceSourceRepository | None = None):
        self.repository = repository or AssistantReferenceSourceRepository()

    async def _load(self, session, request, identity, *, for_update):
        if (
            not isinstance(request, SourceReadRequest)
            or request.source_type != SourceType.ASSISTANT
            or request.source_version not in {None, "current"}
            or not isinstance(identity, UserPayload)
        ):
            raise ResourceReferenceInvalidError(reason="assistant_source_request")
        facts = await self.repository.aload(
            session, request.source_id, for_update=for_update, inspect_token=request.inspect_token
        )
        if facts is None or facts[0]["is_delete"]:
            raise AssistantNotExistsError()
        row, links = facts
        # Inspection evidence is validated from the actual ACTIVE token row by
        # the Repository in this same Session, including on current-read.
        if request.inspect_token is None:
            await require_business_action(identity, resource_type="assistant", resource_id=row["id"], action="visible")
        try:
            references = extract_assistant_references(
                model_name=row["model_name"],
                knowledge_ids=[link["knowledge_id"] for link in links if link["knowledge_id"]],
            )
            payload = canonical_payload_json(_json_value({"assistant": row, "links": links}))
            return AuthorizedSourceSnapshot(
                SourceKey(row["tenant_id"], SourceType.ASSISTANT, row["id"], "current"),
                references,
                ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
                payload_digest(payload),
                payload,
            )
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="assistant_source_configuration") from error

    async def aresolve_source(self, session, request, identity) -> AuthorizedSourceSnapshot:
        return await self._load(session, request, identity, for_update=False)

    async def arevalidate_source(self, session, request, identity, expected) -> AuthorizedSourceSnapshot:
        if not isinstance(expected, AuthorizedSourceSnapshot):
            raise ResourceReferenceInvalidError(reason="assistant_source_snapshot")
        try:
            current = await self._load(session, request, identity, for_update=True)
        except AssistantNotExistsError as error:
            raise KnowledgeOperationPlanConflictError(reason="assistant_source_changed") from error
        if current != expected:
            raise KnowledgeOperationPlanConflictError(reason="assistant_source_changed")
        return current
