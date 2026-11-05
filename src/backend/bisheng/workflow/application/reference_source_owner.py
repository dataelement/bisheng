"""Workflow source authority over real immutable root/version read facts."""

import json
from copy import deepcopy
from dataclasses import fields

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.permission.application.business_authorization import require_business_action
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
        return await self._saved(session, request, identity, for_update=True)

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
            kind = await self.repository.aget_knowledge_resource_type(session, int(target.target_id))
            await require_business_action(identity, resource_type=kind, resource_id=target.target_id, action="visible")
        payload = {"graph": graph, "root": _fact_payload(root)}
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
        return await self._transient(session, request, identity, for_update=True)
