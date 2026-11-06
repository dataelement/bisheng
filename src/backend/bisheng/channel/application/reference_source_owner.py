"""Channel configuration Owner for strict source execution and inspection."""

from datetime import date, datetime
from enum import Enum

from bisheng.channel.domain.repositories.reference_source_repository import ChannelReferenceSourceRepository
from bisheng.channel.domain.services.reference_extractor import (
    CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
    extract_channel_sync_references,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    canonical_payload_json,
    payload_digest,
)


def _json(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


class ChannelReferenceSourceOwner:
    def __init__(self, repository: ChannelReferenceSourceRepository | None = None):
        self.repository = repository or ChannelReferenceSourceRepository()

    async def _load(self, session, request, identity, *, for_update):
        if (
            not isinstance(request, SourceReadRequest)
            or request.source_type != SourceType.CHANNEL_SYNC
            or request.source_version not in {None, "current"}
            or request.inspect_token is not None
            or not isinstance(identity, UserPayload)
        ):
            raise ResourceReferenceInvalidError(reason="channel_source_request_invalid")
        facts = await self.repository.aload(session, request.source_id, for_update=for_update)
        if facts is None:
            raise ChannelNotFoundError()
        channel, rows = facts
        await require_business_action(identity, resource_type="channel", resource_id=channel["id"], action="visible")
        try:
            references = extract_channel_sync_references(rows)
            payload = canonical_payload_json(_json({"channel": channel, "sync": rows}))
            return AuthorizedSourceSnapshot(
                SourceKey(channel["tenant_id"], SourceType.CHANNEL_SYNC, channel["id"], "current"),
                references,
                CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
                payload_digest(payload),
                payload,
            )
        except (TypeError, ValueError, KeyError) as error:
            raise ResourceReferenceInvalidError(reason="channel_source_configuration_invalid") from error

    async def aresolve_source(self, session, request, identity):
        return await self._load(session, request, identity, for_update=False)

    async def arevalidate_source(self, session, request, identity, expected):
        if not isinstance(expected, AuthorizedSourceSnapshot):
            raise ResourceReferenceInvalidError(reason="channel_source_snapshot_invalid")
        try:
            current = await self._load(session, request, identity, for_update=True)
        except ChannelNotFoundError as error:
            raise KnowledgeOperationPlanConflictError(reason="channel_source_changed") from error
        if current != expected:
            raise KnowledgeOperationPlanConflictError(reason="channel_source_changed")
        return current
