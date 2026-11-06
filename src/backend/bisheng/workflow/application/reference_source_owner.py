"""Workflow source authority over real immutable root/version read facts."""

import json
from copy import deepcopy
from dataclasses import fields
from hashlib import sha256
from types import SimpleNamespace
from urllib.parse import quote

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.public_endpoints import PublicGuestAccessDisabledError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.permission.application.access import get_f048_resource_adapter, get_f048_runtime
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    check_business_action,
    require_business_action,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_ALL
from bisheng.public_endpoints.domain.context import get_current_public_api_principal
from bisheng.resource_reference.application.contracts import SourceKey, SourceType, TargetType
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    AuthorizedTransientSnapshot,
    SourceReadRequest,
    TransientTargetRequest,
    canonical_payload_json,
    payload_digest,
)
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure
from bisheng.workflow.domain.repositories.reference_source_repository import WorkflowReferenceSourceRepository
from bisheng.workflow.domain.services.reference_extractor import (
    WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
    extract_workflow_version_references,
)


def normalize_execution_graph(graph: dict | None) -> dict:
    """Keep every execution node/edge field and array order, excluding outer UI."""
    if graph is None or graph == {}:
        return {"nodes": [], "edges": []}
    if not isinstance(graph, dict) or any(not isinstance(graph.get(key), list) for key in ("nodes", "edges")):
        raise ResourceReferenceInvalidError(reason="workflow_execution_graph_invalid")
    result = deepcopy({"nodes": graph["nodes"], "edges": graph["edges"]})
    try:
        canonical_payload_json(result)
    except (TypeError, ValueError) as exc:
        raise ResourceReferenceInvalidError(reason="workflow_execution_graph_invalid") from exc
    return result


def _fact_payload(fact) -> dict:
    return {item.name: getattr(fact, item.name) for item in fields(fact) if item.name != "data_json"}


def _references(graph):
    try:
        return extract_workflow_version_references(graph)
    except (TypeError, ValueError) as exc:
        raise ResourceReferenceInvalidError(reason="workflow_reference_invalid") from exc


class WorkflowReferenceSourceOwner:
    def __init__(self, repository=None):
        self.repository = repository or WorkflowReferenceSourceRepository()

    @staticmethod
    def _identity(identity):
        if not isinstance(identity, UserPayload):
            raise ResourceReferenceInvalidError(reason="workflow_original_identity_required")

    @staticmethod
    async def _disclosure_actions(identity, rows, actor, *, action, snapshots):
        if not rows:
            return {}
        if actor.super_admin and actor.data_scope == DATA_SCOPE_ALL:
            # Same existing system path as require_business_action, after the
            # exact requested versions and their physical parents were checked.
            values = await batch_check_business_actions(
                identity, resource_type="workflow", resource_ids=tuple(rows), actions=(action,)
            )
            return {ident: action in values.get(ident, ()) for ident in rows}
        records = []
        for row in rows.values():
            snapshot = snapshots.get((row.tenant_id, "workflow", row.id))
            if snapshot is None:
                raise ReferenceCoverageNotReadyError(reason="workflow_disclosure_permission_incomplete")
            context = sha256(
                f"{snapshot.context_version}|{row.update_time.isoformat() if row.update_time else '0'}".encode()
            ).hexdigest()
            records.append(
                SimpleNamespace(
                    tenant_id=row.tenant_id,
                    resource_type="workflow",
                    resource_id=row.id,
                    status=row.status,
                    owner_user_id=row.owner_user_id,
                    permission_version=snapshot.version,
                    context_version=context,
                    system_owned=False,
                    system_allowlisted=False,
                )
            )
        adapter = await get_f048_resource_adapter("workflow")
        allowed = []
        for offset in range(0, len(records), 100):
            batch = tuple(records[offset : offset + 100])
            values = await adapter.batch_check_loaded(records=batch, actor=actor, action=action)
            if (
                type(values) is not tuple
                or len(values) != len(batch)
                or any(type(value) is not bool for value in values)
            ):
                raise ReferenceCoverageNotReadyError(reason="workflow_disclosure_permission_incomplete")
            allowed.extend(values)
        return dict(zip(rows, allowed, strict=True))

    async def adisclose_sources(self, session, *, identity, source_keys: tuple[SourceKey, ...]):
        if (
            type(source_keys) is not tuple
            or len(source_keys) > 200
            or any(
                not isinstance(key, SourceKey) or key.source_type != SourceType.WORKFLOW_VERSION for key in source_keys
            )
        ):
            raise ReferenceCoverageNotReadyError(reason="workflow_disclosure_invalid_batch")
        if not source_keys:
            return ()
        try:
            self._identity(identity)
            tenant = get_current_tenant_id()
            if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
                raise ReferenceCoverageNotReadyError(reason="workflow_disclosure_scope_invalid")
            local = tuple(dict.fromkeys(key for key in source_keys if key.tenant_id == tenant))
            if not local:
                return (None,) * len(source_keys)
            if any(
                not key.source_version.isascii()
                or not key.source_version.isdecimal()
                or int(key.source_version) <= 0
                or str(int(key.source_version)) != key.source_version
                for key in local
            ):
                raise ReferenceCoverageNotReadyError(reason="workflow_disclosure_version_invalid")
            facts = await self.repository.aload_disclosure(session, local)
            if len(facts) != len(local):
                raise ReferenceCoverageNotReadyError(reason="workflow_disclosure_metadata_incomplete")
            roots = {row.id: row for row in facts}
            actor = await resolve_permission_actor(identity)
            principal = get_current_public_api_principal()
            guest_id = str(principal.resource_id) if principal and principal.resource_type == "workflow" else None
            visible = {}
            if guest_id in roots:
                try:
                    visible[guest_id] = await check_business_action(
                        identity, resource_type="workflow", resource_id=guest_id, action="visible", actor=actor
                    )
                except PublicGuestAccessDisabledError:
                    visible[guest_id] = False
            ordinary = {ident: row for ident, row in roots.items() if ident != guest_id}
            snapshots = {}
            if ordinary and not (actor.super_admin and actor.data_scope == DATA_SCOPE_ALL):
                runtime = await get_f048_runtime()
                snapshots = await runtime.get_permission_snapshots(
                    tuple((row.tenant_id, "workflow", row.id) for row in ordinary.values())
                )
            visible.update(
                await self._disclosure_actions(identity, ordinary, actor, action="visible", snapshots=snapshots)
            )
            historical = (
                {row.id: row for row in facts if not row.is_current and visible.get(row.id)}
                if principal is None
                else {}
            )
            editable = await self._disclosure_actions(identity, historical, actor, action="edit", snapshots=snapshots)
            by_source = {}
            for key, row in zip(local, facts, strict=True):
                by_source[key] = (
                    SourceDisclosure(key, row.name, row.version_name, f"/flow/{quote(row.id, safe='')}/")
                    if visible.get(row.id) and (row.is_current or editable.get(row.id))
                    else None
                )
            return tuple(by_source.get(key) for key in source_keys)
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="workflow_disclosure_failed") from error

    async def _saved(self, session, request, identity, *, for_update=False):
        self._identity(identity)
        if request.source_type != SourceType.WORKFLOW_VERSION or request.inspect_token is not None:
            raise ResourceReferenceInvalidError(reason="workflow_source_request_invalid")
        version_id = None
        if request.source_version is not None:
            try:
                version_id = int(request.source_version)
            except (TypeError, ValueError) as exc:
                raise ResourceReferenceInvalidError(reason="workflow_version_invalid") from exc
            if version_id <= 0 or str(version_id) != request.source_version:
                raise ResourceReferenceInvalidError(reason="workflow_version_invalid")
        root = await self.repository.aget_root(session, request.source_id, for_update=for_update)
        await require_business_action(identity, resource_type="workflow", resource_id=root.id, action="visible")
        version = await self.repository.aget_version(session, root, version_id, for_update=for_update)
        if version.is_current != 1:
            if get_current_public_api_principal() is not None:
                raise ResourceReferenceInvalidError(reason="public_workflow_current_version_required")
            await require_business_action(identity, resource_type="workflow", resource_id=root.id, action="edit")
        graph = normalize_execution_graph(json.loads(version.data_json))
        if version.is_current == 1 and normalize_execution_graph(json.loads(root.data_json)) != graph:
            raise ReferenceCoverageNotReadyError(reason="workflow_current_mirror_drift")
        payload = canonical_payload_json(
            {"graph": graph, "root": _fact_payload(root), "version": _fact_payload(version)}
        )
        return AuthorizedSourceSnapshot(
            SourceKey(root.tenant_id, SourceType.WORKFLOW_VERSION, root.id, str(version.id)),
            _references(graph),
            WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
            payload_digest(payload),
            payload,
        )

    async def aresolve_source(self, session, request: SourceReadRequest, identity: object) -> AuthorizedSourceSnapshot:
        return await self._saved(session, request, identity)

    async def arevalidate_source(self, session, request, identity, expected) -> AuthorizedSourceSnapshot:
        if expected.source_key.source_type != request.source_type or expected.source_key.source_id != request.source_id:
            raise ResourceReferenceInvalidError(reason="workflow_source_snapshot_mismatch")
        try:
            return await self._saved(session, request, identity, for_update=True)
        except NotFoundError as exc:
            raise KnowledgeOperationPlanConflictError(reason="workflow_source_changed") from exc

    async def _transient(self, session, request, identity, *, for_update=False):
        self._identity(identity)
        if get_current_public_api_principal() is not None:
            raise ResourceReferenceInvalidError(reason="public_workflow_preview_forbidden")
        root = await self.repository.aget_root(session, request.resource_id, for_update=for_update)
        await require_business_action(identity, resource_type="workflow", resource_id=root.id, action="edit")
        supplied = json.loads(request.payload_json)
        if "graph" not in supplied or set(supplied) - {"graph", "node_input"}:
            raise ResourceReferenceInvalidError(reason="workflow_preview_payload_invalid")
        graph = normalize_execution_graph(supplied["graph"])
        references = _references(graph)
        for target in sorted(
            {ref.target for ref in references if ref.target.target_type == TargetType.KNOWLEDGE_SPACE},
            key=lambda item: int(item.target_id),
        ):
            kind = await self.repository.aget_knowledge_resource_type(
                session, int(target.target_id), for_update=for_update
            )
            await require_business_action(identity, resource_type=kind, resource_id=target.target_id, action="visible")
        payload = {"graph": graph}
        if "node_input" in supplied:
            payload["node_input"] = deepcopy(supplied["node_input"])
        encoded = canonical_payload_json(payload)
        return AuthorizedTransientSnapshot(
            "workflow",
            root.id,
            root.tenant_id,
            references,
            WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
            payload_digest(encoded),
            encoded,
        )

    async def aresolve_transient(
        self, session, request: TransientTargetRequest, identity: object
    ) -> AuthorizedTransientSnapshot:
        return await self._transient(session, request, identity)

    async def arevalidate_transient(self, session, request, identity, expected) -> AuthorizedTransientSnapshot:
        if expected.resource_id != request.resource_id:
            raise ResourceReferenceInvalidError(reason="workflow_preview_snapshot_mismatch")
        try:
            return await self._transient(session, request, identity, for_update=True)
        except NotFoundError as exc:
            raise KnowledgeOperationPlanConflictError(reason="workflow_preview_root_changed") from exc
