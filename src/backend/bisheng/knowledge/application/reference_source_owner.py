"""Knowledge owns its current model slots and original resource authorization."""

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeNotExistError,
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.services.model_reference_extractor import (
    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    extract_knowledge_model_references,
)
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.application.business_authorization import (
    batch_check_verified_business_visible,
    require_business_action,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_ALL
from bisheng.resource_reference.application.contracts import (
    SourceKey,
    SourceType,
    TransactionIdentity,
    canonical_target_id,
)
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReadRequest,
    canonical_payload_json,
    payload_digest,
)
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure
from bisheng.utils.async_utils import run_async_safe


class KnowledgeReferenceSourceOwner:
    def __init__(self, repository=None, identity_port=None):
        self.repository = repository if repository is not None else KnowledgeModelReferenceRepository()
        self.identity_port = identity_port

    async def adisclose_sources(self, session, *, identity, source_keys: tuple[SourceKey, ...]):
        if (
            type(source_keys) is not tuple
            or len(source_keys) > 200
            or any(
                not isinstance(key, SourceKey)
                or key.source_type != SourceType.KNOWLEDGE
                or key.source_version != "current"
                for key in source_keys
            )
        ):
            raise ReferenceCoverageNotReadyError(reason="knowledge_disclosure_invalid_batch")
        if not source_keys:
            return ()
        try:
            tenant = self.repository._tenant_id()
            own = tuple(key for key in source_keys if key.tenant_id == tenant)
            if not isinstance(identity, UserPayload):
                raise ReferenceCoverageNotReadyError(reason="knowledge_disclosure_original_identity_required")
            if not own:
                return (None,) * len(source_keys)
            identity_port = AuthenticatedSourceReadIdentity()
            before = await identity_port.acapture(identity)
            transaction = TransactionIdentity.capture(session)
            rows = await self.repository.aload_disclosure_sources(
                session, knowledge_ids=tuple(sorted({int(key.source_id) for key in own}))
            )
            by_id = {str(row.id): row for row in rows}
            if set(by_id) != {key.source_id for key in own} or any(row.tenant_id != tenant for row in rows):
                raise ReferenceCoverageNotReadyError(reason="knowledge_disclosure_source_missing")
            actor = await resolve_permission_actor(identity)
            visible = {}
            if actor.super_admin and actor.data_scope == DATA_SCOPE_ALL:
                # The same full-scope shortcut used by check_business_action.
                visible = {str(row.id): True for row in rows}
            else:
                for kind, resource_type in ((3, "knowledge_space"), (0, "knowledge_library")):
                    selected = [row for row in rows if (row.type == 3) == (kind == 3)]
                    if not selected:
                        continue
                    adapter = await get_f048_resource_adapter(resource_type)
                    targets = await adapter.resolve_permission_targets_from_rows(
                        rows=selected, resource_type=resource_type, actor=actor
                    )
                    decisions = await batch_check_verified_business_visible(actor=actor, targets=targets)
                    visible.update({ident: allowed for (_, ident), allowed in decisions.items()})
            if await identity_port.acapture(identity) != before:
                raise ReferenceCoverageNotReadyError(reason="knowledge_disclosure_identity_changed")
            transaction.assert_current(session)
            return tuple(
                SourceDisclosure(
                    key,
                    by_id[key.source_id].name,
                    None,
                    f"/filelib/qalib/{key.source_id}"
                    if by_id[key.source_id].type == 1
                    else f"/filelib/{key.source_id}",
                )
                if key.tenant_id == tenant and visible.get(key.source_id, False)
                else None
                for key in source_keys
            )
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="knowledge_disclosure_failed") from error

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
