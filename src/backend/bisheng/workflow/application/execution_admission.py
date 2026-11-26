"""Workflow saved execution and edit previews through the issued read authority."""

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.database import get_async_db_session
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.error_details import snapshot_reference_errors
from bisheng.resource_reference.application.source_access import get_reference_read_runtime
from bisheng.resource_reference.application.source_contracts import (
    SourceReadRequest,
    TransientTargetRequest,
    canonical_payload_json,
)
from bisheng.workflow.application.reference_source_owner import _references, normalize_execution_graph


@dataclass(frozen=True, slots=True)
class PreparedWorkflowExecution:
    source_key: SourceKey | None
    configuration_digest: str
    _graph_json: str = field(repr=False)
    _node_input_json: str | None = field(default=None, repr=False)

    @property
    def graph(self) -> dict:
        return json.loads(self._graph_json)

    @property
    def node_data(self) -> dict:
        return self.graph["nodes"][0]

    @property
    def node_input(self) -> dict | None:
        return json.loads(self._node_input_json) if self._node_input_json is not None else None


@asynccontextmanager
async def _read_session(reference_session):
    if reference_session is not None:
        if not reference_session.in_transaction():
            raise ResourceReferenceInvalidError(reason="source_read_transaction_required")
        yield reference_session
    else:
        async with get_async_db_session() as session, session.begin():
            yield session


def _version(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ResourceReferenceInvalidError(reason="workflow_version_invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ResourceReferenceInvalidError(reason="workflow_version_invalid") from exc
    if parsed <= 0 or str(parsed) != str(value):
        raise ResourceReferenceInvalidError(reason="workflow_version_invalid")
    return str(parsed)


def _prepared(snapshot, *, graph=None):
    payload = json.loads(snapshot.payload_json)
    return PreparedWorkflowExecution(
        getattr(snapshot, "source_key", None),
        snapshot.configuration_digest,
        canonical_payload_json(payload["graph"] if graph is None else graph),
        canonical_payload_json(payload["node_input"]) if "node_input" in payload else None,
    )


async def _saved(session, runtime, identity, workflow_id, version_id, supplied_graph, override, *, scope=None):
    if scope is None:
        scope = await runtime.verifier.aissue_scope(
            session, SourceReadRequest(SourceType.WORKFLOW_VERSION, str(workflow_id), _version(version_id)), identity
        )
    result = await runtime.arequire_source_valid(session, scope, identity)
    saved = json.loads(result.snapshot.payload_json)["graph"]
    if supplied_graph is not None and normalize_execution_graph(supplied_graph) != saved:
        raise ResourceReferenceInvalidError(reason="workflow_saved_graph_mismatch")
    executable = normalize_execution_graph(saved)
    if override:
        if not isinstance(override, dict) or any(not isinstance(value, dict) for value in override.values()):
            raise ResourceReferenceInvalidError(reason="workflow_override_invalid")
        from bisheng.worker.workflow.redis_callback import RedisCallback

        executable = RedisCallback.override_nodes_params(executable, override)
        if _references(executable) != result.snapshot.references:
            raise ResourceReferenceInvalidError(reason="workflow_override_changes_references")
    return _prepared(result.snapshot, graph=executable)


async def prepare_saved(
    identity, workflow_id, version_id=None, supplied_graph=None, override=None, *, reference_session=None
) -> PreparedWorkflowExecution:
    async with _read_session(reference_session) as session:
        runtime = await get_reference_read_runtime()
        return await _saved(session, runtime, identity, workflow_id, version_id, supplied_graph, override)


async def _preview(session, runtime, identity, workflow_id, graph, *, node_input=None):
    payload = {"graph": normalize_execution_graph(graph)}
    if node_input is not None:
        if not isinstance(node_input, dict):
            raise ResourceReferenceInvalidError(reason="workflow_node_input_invalid")
        payload["node_input"] = node_input
    scope = await runtime.verifier.aissue_transient_scope(
        session, TransientTargetRequest("workflow", str(workflow_id), canonical_payload_json(payload)), identity
    )
    result = await runtime.arequire_transient_valid(session, scope, identity)
    return _prepared(result.snapshot)


async def prepare_preview(
    identity, workflow_id, graph, version_hint=None, *, reference_session=None
) -> PreparedWorkflowExecution:
    # A UI version hint never turns an unsaved graph into a persisted source.
    _version(version_hint)
    async with _read_session(reference_session) as session:
        return await _preview(session, await get_reference_read_runtime(), identity, workflow_id, graph)


async def preflight_preview(identity, workflow_id, graph, *, reference_session=None):
    """Inspect the unsaved graph under the same authority as actual preview execution."""
    payload = {"graph": normalize_execution_graph(graph)}
    async with _read_session(reference_session) as session:
        runtime = await get_reference_read_runtime()
        try:
            scope = await runtime.verifier.aissue_transient_scope(
                session, TransientTargetRequest("workflow", str(workflow_id), canonical_payload_json(payload)), identity
            )
            result = await runtime.ainspect_transient(session, scope, identity)
        except ResourceReferenceInvalidError as error:
            if error.kwargs.get("reason") != "reference_target_invalid" or not error.kwargs.get("reference_errors"):
                raise
            errors = error.kwargs["reference_errors"]
        else:
            errors = snapshot_reference_errors(
                result.snapshot, result.target_states, limit=None, include_parameter=True
            )
            # Tenant-filtered absence also covers foreign targets. Do not expose
            # global existence through an editor-supplied selection.
            for error in errors:
                if error["state"] == "invalid_missing":
                    error["state"] = "unavailable"
    return {"valid": not errors, "errors": errors}


async def prepare_node_preview(
    identity, workflow_id, node_data, node_input, *, reference_session=None
) -> PreparedWorkflowExecution:
    if not isinstance(node_data, dict):
        raise ResourceReferenceInvalidError(reason="workflow_node_invalid")
    async with _read_session(reference_session) as session:
        return await _preview(
            session,
            await get_reference_read_runtime(),
            identity,
            workflow_id,
            {"nodes": [node_data], "edges": []},
            node_input=node_input,
        )


async def prepare_initial(
    identity, workflow_id, graph, *, execution_mode=None, version_hint=None, allow_preview=True, published_only=False
) -> PreparedWorkflowExecution:
    """Resolve endpoint-bound saved execution or an authorized editor preview."""
    if execution_mode is not None and (
        not isinstance(execution_mode, str) or execution_mode not in ("saved", "preview")
    ):
        raise ResourceReferenceInvalidError(reason="workflow_execution_mode_invalid")
    version = _version(version_hint)
    if execution_mode == "preview":
        if published_only or not allow_preview:
            raise ResourceReferenceInvalidError(reason="public_workflow_preview_forbidden")
        return await prepare_preview(identity, workflow_id, graph, version_hint=version)
    async with _read_session(None) as session:
        runtime = await get_reference_read_runtime()
        scope = await runtime.verifier.aissue_scope(
            session,
            SourceReadRequest(SourceType.WORKFLOW_VERSION, str(workflow_id), None if published_only else version),
            identity,
        )
        if published_only:
            # This policy is bound by the public WS endpoint, never by message
            # fields. Public HTTP graphs are redacted views, not execution data.
            if version is not None and version != scope.snapshot.source_key.source_version:
                raise ResourceReferenceInvalidError(reason="public_workflow_current_version_required")
            return await _saved(session, runtime, identity, workflow_id, None, None, None, scope=scope)
        candidate = json.loads(scope.snapshot.payload_json)["graph"]
        if graph is None or normalize_execution_graph(graph) == candidate:
            return await _saved(session, runtime, identity, workflow_id, version, graph, None, scope=scope)
        if execution_mode == "saved" or not allow_preview:
            raise ResourceReferenceInvalidError(reason="workflow_saved_graph_mismatch")
        return await _preview(session, runtime, identity, workflow_id, graph)
