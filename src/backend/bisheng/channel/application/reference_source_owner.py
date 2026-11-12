"""Channel configuration Owner for strict source execution and inspection."""

from datetime import date, datetime
from enum import Enum
from hashlib import sha256
from urllib.parse import quote

from bisheng.channel.domain.repositories.reference_source_repository import ChannelReferenceSourceRepository
from bisheng.channel.domain.services.f048_channel_permission import (
    ChannelPermissionRecord,
    F048ChannelPermissionAdapter,
)
from bisheng.channel.domain.services.reference_extractor import (
    CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
    extract_channel_sync_references,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.permission.application.access import get_f048_runtime
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    batch_check_verified_business_visible,
    require_business_action,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_ALL
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    canonical_payload_json,
    payload_digest,
)
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure


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

    async def adisclose_sources(self, session, *, identity, source_keys: tuple[SourceKey, ...]):
        if (
            type(source_keys) is not tuple
            or len(source_keys) > 200
            or any(not isinstance(key, SourceKey) or key.source_type != SourceType.CHANNEL_SYNC for key in source_keys)
        ):
            raise ReferenceCoverageNotReadyError(reason="channel_disclosure_invalid_batch")
        if not source_keys:
            return ()
        try:
            tenant = get_current_tenant_id()
            if (
                not isinstance(identity, UserPayload)
                or type(tenant) is not int
                or tenant <= 0
                or is_tenant_filter_bypassed()
            ):
                raise ReferenceCoverageNotReadyError(reason="channel_disclosure_original_context_required")
            local = tuple(dict.fromkeys(key for key in source_keys if key.tenant_id == tenant))
            if not local:
                return (None,) * len(source_keys)
            if any(key.source_version != "current" for key in local):
                raise ReferenceCoverageNotReadyError(reason="channel_disclosure_version_invalid")
            facts = await self.repository.aload_disclosure(session, local)
            if len(facts) != len(local):
                raise ReferenceCoverageNotReadyError(reason="channel_disclosure_metadata_incomplete")
            rows = {row.id: row for row in facts}
            actor = await resolve_permission_actor(identity)
            if actor.super_admin and actor.data_scope == DATA_SCOPE_ALL:
                # Existing system action path, limited to the real validated
                # current-tenant Channel roots; it never exposes foreign rows.
                values = await batch_check_business_actions(
                    identity, resource_type="channel", resource_ids=tuple(rows), actions=("visible",)
                )
                visible = {ident: "visible" in values.get(ident, ()) for ident in rows}
            else:
                runtime = await get_f048_runtime()
                snapshots = await runtime.get_permission_snapshots(
                    tuple((row.tenant_id, "channel", row.id) for row in rows.values())
                )
                targets = []
                for row in rows.values():
                    snapshot = snapshots.get((row.tenant_id, "channel", row.id))
                    if (
                        snapshot is None
                        or snapshot.mode != "CUSTOM"
                        or snapshot.parent_type is not None
                        or snapshot.parent_id is not None
                        or type(snapshot.version) is not int
                        or snapshot.version <= 0
                    ):
                        raise ReferenceCoverageNotReadyError(reason="channel_disclosure_permission_incomplete")
                    context = sha256(
                        f"{snapshot.context_version}|{row.update_time.isoformat() if row.update_time else '0'}".encode()
                    ).hexdigest()
                    record = ChannelPermissionRecord(
                        row.tenant_id,
                        row.id,
                        "ACTIVE",
                        row.creator_user_id,
                        snapshot.version,
                        context,
                        shared_read_only=row.is_shared,
                    )
                    targets.append(F048ChannelPermissionAdapter._target(record, row.id, actor, action="visible"))
                allowed = await batch_check_verified_business_visible(actor=actor, targets=tuple(targets))
                if set(allowed) != {("channel", ident) for ident in rows}:
                    raise ReferenceCoverageNotReadyError(reason="channel_disclosure_permission_incomplete")
                visible = {ident: allowed["channel", ident] for ident in rows}
            disclosures = {
                key: SourceDisclosure(key, row.name, None, f"/workspace/channel/{quote(row.id, safe='')}")
                if visible.get(row.id)
                else None
                for key, row in zip(local, facts, strict=True)
            }
            return tuple(disclosures.get(key) for key in source_keys)
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="channel_disclosure_failed") from error

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
            references = extract_channel_sync_references(rows, skip_legacy_folders=True)
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
