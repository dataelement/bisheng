"""The assistant Owner authorizes a real persisted source, never a caller DTO."""

from datetime import date, datetime
from enum import Enum
from hashlib import sha256
from urllib.parse import quote

from bisheng.api.services.f048_application_permission import ApplicationPermissionRecord
from bisheng.assistant.domain.repositories.reference_source_repository import AssistantReferenceSourceRepository
from bisheng.assistant.domain.services.reference_extractor import (
    ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
    extract_assistant_references,
    extract_legacy_assistant_knowledge_references,
    legacy_assistant_name_version,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.assistant import AssistantNotExistsError
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.public_endpoints import PublicGuestAccessDisabledError
from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.assistant import AssistantStatus
from bisheng.permission.application.access import get_f048_resource_adapter, get_f048_runtime
from bisheng.permission.application.business_authorization import batch_check_business_actions, require_business_action
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_ALL
from bisheng.resource_reference.application.contracts import SourceKey, SourceType, TransactionIdentity
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    canonical_payload_json,
    payload_digest,
)
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure


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

    async def adisclose_sources(
        self, session, *, identity, source_keys: tuple[SourceKey, ...]
    ) -> tuple[SourceDisclosure | None, ...]:
        if (
            type(source_keys) is not tuple
            or len(source_keys) > 200
            or any(
                not isinstance(key, SourceKey)
                or key.source_type != SourceType.ASSISTANT
                or key.source_version != "current"
                for key in source_keys
            )
        ):
            raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_batch")
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
                raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_identity")
            transaction = TransactionIdentity.capture(session)
            ids = tuple(dict.fromkeys(key.source_id for key in source_keys if key.tenant_id == tenant))
            if not ids:
                return (None,) * len(source_keys)
            capture = AuthenticatedSourceReadIdentity()
            original = await capture.acapture(identity)
            if original.request_tenant_id != tenant:
                raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_identity_changed")
            actor = await resolve_permission_actor(identity)
            rows = await self.repository.alist_disclosure_rows(session, assistant_ids=ids)
            by_id = {row.id: row for row in rows}
            if len(by_id) != len(rows) or set(by_id) != set(ids):
                raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_missing_metadata")
            runtime = await get_f048_runtime()
            snapshots = await runtime.get_permission_snapshots(tuple((tenant, "assistant", ident) for ident in ids))
            records = []
            for ident in ids:
                row, snapshot = by_id[ident], snapshots.get((tenant, "assistant", ident))
                if (
                    row.tenant_id != tenant
                    or row.is_delete
                    or type(row.name) is not str
                    or snapshot is None
                    or type(snapshot.version) is not int
                    or snapshot.version <= 0
                    or snapshot.mode != "CUSTOM"
                    or snapshot.parent_type is not None
                    or snapshot.parent_id is not None
                ):
                    raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_invalid_metadata")
                status = AssistantStatus(row.status).name
                context = sha256(
                    f"{snapshot.context_version}|{row.update_time.isoformat() if row.update_time else '0'}".encode()
                ).hexdigest()
                records.append(
                    ApplicationPermissionRecord(
                        tenant, "assistant", ident, status, row.user_id, snapshot.version, context
                    )
                )
            adapter = await get_f048_resource_adapter("assistant")
            # Validate the loaded business rows even on existing public/system paths.
            for record in records:
                adapter._record_target(record, actor, action="visible")
            from bisheng.public_endpoints.domain.services import guest_policy

            allowed, pending = {}, []
            for record in records:
                if guest_policy.is_public_published_resource(record.resource_id, "assistant"):
                    try:
                        await guest_policy.ensure_guest_link_enabled("assistant", record.resource_id)
                        allowed[record.resource_id] = True
                    except PublicGuestAccessDisabledError:
                        allowed[record.resource_id] = False
                else:
                    pending.append(record)
            if actor.super_admin and actor.data_scope == DATA_SCOPE_ALL and pending:
                decisions = await batch_check_business_actions(
                    identity,
                    resource_type="assistant",
                    resource_ids=tuple(row.resource_id for row in pending),
                    actions=("visible",),
                )
                if set(decisions) != {row.resource_id for row in pending}:
                    raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_incomplete_permissions")
                allowed.update((ident, "visible" in actions) for ident, actions in decisions.items())
            else:
                for offset in range(0, len(pending), 100):
                    batch = tuple(pending[offset : offset + 100])
                    decisions = await adapter.batch_check_loaded(records=batch, actor=actor, action="visible")
                    if len(decisions) != len(batch):
                        raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_incomplete_permissions")
                    allowed.update(
                        (record.resource_id, bool(value)) for record, value in zip(batch, decisions, strict=True)
                    )
            transaction.assert_current(session)
            if await capture.acapture(identity) != original:
                raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_identity_changed")
            return tuple(
                SourceDisclosure(key, by_id[key.source_id].name, None, f"/assistant/{quote(key.source_id, safe='')}")
                if key.tenant_id == tenant and allowed[key.source_id]
                else None
                for key in source_keys
            )
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_failed") from error

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
            source_key = SourceKey(row["tenant_id"], SourceType.ASSISTANT, row["id"], "current")
            legacy_version = legacy_assistant_name_version(row["model_name"])
            retained = legacy_version is not None and await self.repository.ahas_legacy_name_retention(
                session, source_key, legacy_version
            )
            references = (extract_legacy_assistant_knowledge_references if retained else extract_assistant_references)(
                model_name=row["model_name"],
                knowledge_ids=[link["knowledge_id"] for link in links if link["knowledge_id"]],
            )
            payload = canonical_payload_json(_json_value({"assistant": row, "links": links}))
            return AuthorizedSourceSnapshot(
                source_key,
                references,
                legacy_version if retained else ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
                payload_digest(payload),
                payload,
                invalid_reason="assistant_legacy_model_name_unresolved" if retained else None,
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
