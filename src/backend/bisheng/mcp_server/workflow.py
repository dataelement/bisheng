from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from bisheng.api.services.external_workflow import ExternalWorkflowService
from bisheng.api.services.workflow_authoring import WorkflowAuthoringService
from bisheng.api.v1.schemas import GraphData
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.mcp_server.auth import McpAuthorizationMiddleware, get_current_token_scopes, get_login_user_from_mcp_token, require_mcp_scopes
from bisheng.workflow.authoring import (
    NodeTemplateDescriptor,
    NodeTypeDescriptor,
    ValidationDiagnostic,
    WorkflowGraphDescriptor,
    WorkflowManifest,
    WorkflowVersionSummary,
)

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    FastMCP = None


class WorkflowMutationResult(BaseModel):
    ok: bool = True
    message: str = 'SUCCESS'
    flow_id: Optional[str] = None
    version_id: Optional[int] = None
    status: Optional[str] = None
    draft_revision: Optional[int] = None
    node_id: Optional[str] = None
    edge_id: Optional[str] = None
    error_code: Optional[int] = None


class WorkflowValidationResult(BaseModel):
    ok: bool = True
    valid: bool = True
    flow_id: Optional[str] = None
    version_id: Optional[int] = None
    draft_revision: Optional[int] = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    diagnostics: list[ValidationDiagnostic] = Field(default_factory=list)
    error_code: Optional[int] = None


class WorkflowNodeSummary(BaseModel):
    id: str
    type: str = ''
    name: str = ''
    param_keys: list[str] = Field(default_factory=list)


class WorkflowNodeListResult(BaseModel):
    ok: bool = True
    flow_id: Optional[str] = None
    version_id: Optional[int] = None
    draft_revision: Optional[int] = None
    nodes: list[WorkflowNodeSummary] = Field(default_factory=list)
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class WorkflowNodeParamField(BaseModel):
    display_name: str = ''
    group_name: str = ''
    type: Optional[str] = None
    required: bool = False
    show: bool = False
    options: Optional[object] = None
    scope: Optional[object] = None
    placeholder: Optional[str] = None
    refresh: bool = False
    value: Optional[object] = None


class WorkflowNodeParamsResult(BaseModel):
    ok: bool = True
    flow_id: Optional[str] = None
    version_id: Optional[int] = None
    draft_revision: Optional[int] = None
    node_id: Optional[str] = None
    node_type: str = ''
    node_name: str = ''
    params: dict[str, WorkflowNodeParamField] = Field(default_factory=dict)
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class ConditionNodeResult(BaseModel):
    ok: bool = True
    flow_id: Optional[str] = None
    version_id: Optional[int] = None
    draft_revision: Optional[int] = None
    node_id: Optional[str] = None
    node_name: str = ''
    condition_cases: list[dict[str, object]] = Field(default_factory=list)
    route_handles: list[str] = Field(default_factory=list)
    outgoing_edges: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class WorkflowConnectionResult(BaseModel):
    ok: bool = True
    service: str = 'bisheng-workflow-mcp'
    authenticated: bool = True
    user_id: Optional[int] = None
    user_name: str = ''
    scopes: list[str] = Field(default_factory=list)
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class WorkflowManifestResult(BaseModel):
    ok: bool = True
    workflow: Optional[WorkflowManifest] = None
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class WorkflowManifestListResult(BaseModel):
    ok: bool = True
    workflows: list[WorkflowManifest] = Field(default_factory=list)
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class WorkflowVersionListResult(BaseModel):
    ok: bool = True
    flow_id: Optional[str] = None
    versions: list[WorkflowVersionSummary] = Field(default_factory=list)
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class WorkflowGraphResult(BaseModel):
    ok: bool = True
    graph: Optional[WorkflowGraphDescriptor] = None
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class NodeTypeListResult(BaseModel):
    ok: bool = True
    node_types: list[NodeTypeDescriptor] = Field(default_factory=list)
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


class NodeTemplateResult(BaseModel):
    ok: bool = True
    template: Optional[NodeTemplateDescriptor] = None
    message: str = 'SUCCESS'
    error_code: Optional[int] = None


def _mutation_error(exc: Exception) -> WorkflowMutationResult:
    return _error_result(WorkflowMutationResult, exc)


def _validation_error(exc: Exception) -> WorkflowValidationResult:
    message, error_code = _error_details(exc)
    return WorkflowValidationResult(
        ok=False,
        valid=False,
        errors=[message],
        diagnostics=WorkflowAuthoringService.diagnostics_from_exception(exc),
        error_code=error_code,
    )


def _node_list_error(exc: Exception) -> WorkflowNodeListResult:
    return _error_result(WorkflowNodeListResult, exc)


def _node_params_error(exc: Exception) -> WorkflowNodeParamsResult:
    return _error_result(WorkflowNodeParamsResult, exc)


def _condition_node_error(exc: Exception) -> ConditionNodeResult:
    return _error_result(ConditionNodeResult, exc)


def _workflow_manifest_error(exc: Exception) -> WorkflowManifestResult:
    return _error_result(WorkflowManifestResult, exc)


def _workflow_manifest_list_error(exc: Exception) -> WorkflowManifestListResult:
    return _error_result(WorkflowManifestListResult, exc)


def _workflow_version_list_error(exc: Exception) -> WorkflowVersionListResult:
    return _error_result(WorkflowVersionListResult, exc)


def _workflow_graph_error(exc: Exception) -> WorkflowGraphResult:
    return _error_result(WorkflowGraphResult, exc)


def _node_type_list_error(exc: Exception) -> NodeTypeListResult:
    return _error_result(NodeTypeListResult, exc)


def _node_template_result_error(exc: Exception) -> NodeTemplateResult:
    return _error_result(NodeTemplateResult, exc)


def _error_details(exc: Exception) -> tuple[str, Optional[int]]:
    if isinstance(exc, BaseErrorCode):
        return exc.message, exc.code
    return str(exc) or exc.__class__.__name__, None


def _error_result(result_cls, exc: Exception, **kwargs):
    message, error_code = _error_details(exc)
    return result_cls(ok=False, message=message, error_code=error_code, **kwargs)


def _connection_error(exc: Exception) -> WorkflowConnectionResult:
    message, error_code = _error_details(exc)
    return WorkflowConnectionResult(
        ok=False,
        authenticated=False,
        message=message,
        error_code=error_code,
    )


def _log_tool_failure(tool_name: str, exc: Exception):
    if isinstance(exc, BaseErrorCode):
        logger.warning(f'{tool_name} failed: {exc.message} (code={exc.code})')
        return
    logger.exception(f'{tool_name} failed')


def create_workflow_mcp_server():
    if FastMCP is None:
        logger.warning('mcp dependency is not available, workflow MCP server will not be mounted')
        return None

    mcp = FastMCP(
        'Bisheng Workflow MCP',
        instructions='Create, validate, and publish Bisheng workflows as drafts first.',
        json_response=True,
    )
    try:
        mcp.settings.streamable_http_path = '/'
    except Exception:
        pass

    def _connection_result(login_user, *, include_scopes: bool = True) -> WorkflowConnectionResult:
        return WorkflowConnectionResult(
            user_id=login_user.user_id,
            user_name=login_user.user_name,
            scopes=list(get_current_token_scopes()) if include_scopes else [],
        )

    async def _run_authenticated_tool(tool_name: str,
                                      operation,
                                      *,
                                      scope: Optional[str] = None,
                                      error_builder=None):
        try:
            login_user = await get_login_user_from_mcp_token()
            if scope:
                require_mcp_scopes(scope)
            return await operation(login_user)
        except Exception as exc:
            _log_tool_failure(tool_name, exc)
            return error_builder(exc)

    @mcp.tool()
    async def ping() -> WorkflowConnectionResult:
        """Verify the MCP connection and return the current authenticated Bisheng user."""
        async def _op(login_user):
            return _connection_result(login_user, include_scopes=False)

        return await _run_authenticated_tool('ping', _op, error_builder=_connection_error)

    @mcp.tool()
    async def whoami() -> WorkflowConnectionResult:
        """Return the authenticated Bisheng user behind the current MCP bearer token."""
        async def _op(login_user):
            return _connection_result(login_user, include_scopes=True)

        return await _run_authenticated_tool('whoami', _op, error_builder=_connection_error)

    @mcp.tool()
    async def list_workflows() -> WorkflowManifestListResult:
        """List workflows the current MCP user can author."""
        async def _op(login_user):
            workflows = await WorkflowAuthoringService.list_workflows(login_user)
            return WorkflowManifestListResult(workflows=workflows)
        return await _run_authenticated_tool(
            'list_workflows',
            _op,
            scope='workflow.read',
            error_builder=_workflow_manifest_list_error,
        )

    @mcp.tool()
    async def get_workflow(flow_id: str) -> WorkflowManifestResult:
        """Return manifest information for one authorable workflow."""
        async def _op(login_user):
            workflow = await WorkflowAuthoringService.get_workflow(login_user, flow_id)
            return WorkflowManifestResult(workflow=workflow)
        return await _run_authenticated_tool('get_workflow', _op, scope='workflow.read',
                                             error_builder=_workflow_manifest_error)

    @mcp.tool()
    async def get_workflow_versions(flow_id: str) -> WorkflowVersionListResult:
        """List versions for one authorable workflow."""
        async def _op(login_user):
            versions = await WorkflowAuthoringService.get_workflow_versions(login_user, flow_id)
            return WorkflowVersionListResult(flow_id=flow_id, versions=versions)
        return await _run_authenticated_tool('get_workflow_versions', _op, scope='workflow.read',
                                             error_builder=_workflow_version_list_error)

    @mcp.tool()
    async def get_workflow_graph(flow_id: str, version_id: int = 0) -> WorkflowGraphResult:
        """Return the normalized editable graph for a workflow."""
        async def _op(login_user):
            graph = await WorkflowAuthoringService.get_workflow_graph(
                login_user=login_user,
                flow_id=flow_id,
                version_id=version_id or None,
            )
            return WorkflowGraphResult(graph=graph)
        return await _run_authenticated_tool('get_workflow_graph', _op, scope='workflow.read',
                                             error_builder=_workflow_graph_error)

    @mcp.tool()
    async def list_node_types() -> NodeTypeListResult:
        """List supported workflow node types for authoring."""
        async def _op(_login_user):
            return NodeTypeListResult(node_types=WorkflowAuthoringService.list_node_types())
        return await _run_authenticated_tool('list_node_types', _op, scope='workflow.read',
                                             error_builder=_node_type_list_error)

    @mcp.tool()
    async def get_node_template(node_type: str) -> NodeTemplateResult:
        """Return the normalized template metadata for one workflow node type."""
        async def _op(_login_user):
            return NodeTemplateResult(template=WorkflowAuthoringService.get_node_template(node_type))
        return await _run_authenticated_tool('get_node_template', _op, scope='workflow.read',
                                             error_builder=_node_template_result_error)

    @mcp.tool()
    async def list_workflow_nodes(flow_id: str, version_id: int = 0) -> WorkflowNodeListResult:
        """List nodes in a workflow version so the caller can choose a node_id to edit."""
        async def _op(login_user):
            data = await ExternalWorkflowService.list_workflow_nodes(
                login_user=login_user,
                flow_id=flow_id,
                version_id=version_id or None,
            )
            return WorkflowNodeListResult(**data)
        return await _run_authenticated_tool('list_workflow_nodes', _op, scope='workflow.read',
                                             error_builder=_node_list_error)

    @mcp.tool()
    async def get_workflow_node_params(flow_id: str,
                                       node_id: str,
                                       version_id: int = 0) -> WorkflowNodeParamsResult:
        """Read the current editable params of a workflow node."""
        async def _op(login_user):
            data = await ExternalWorkflowService.get_workflow_node_params(
                login_user=login_user,
                flow_id=flow_id,
                node_id=node_id,
                version_id=version_id or None,
            )
            return WorkflowNodeParamsResult(**data)
        return await _run_authenticated_tool('get_workflow_node_params', _op, scope='workflow.read',
                                             error_builder=_node_params_error)

    @mcp.tool()
    async def get_condition_node(flow_id: str,
                                 node_id: str,
                                 version_id: int = 0) -> ConditionNodeResult:
        """Read the structured routing configuration of one condition node."""
        async def _op(login_user):
            data = await ExternalWorkflowService.get_condition_node_config(
                login_user=login_user,
                flow_id=flow_id,
                node_id=node_id,
                version_id=version_id or None,
            )
            return ConditionNodeResult(**data)
        return await _run_authenticated_tool('get_condition_node', _op, scope='workflow.read',
                                             error_builder=_condition_node_error)

    @mcp.tool()
    async def create_workflow_draft(name: str,
                                    graph_data: GraphData,
                                    description: str = '',
                                    guide_word: str = '') -> WorkflowMutationResult:
        """Create a new Bisheng workflow draft for the current logged-in user."""
        async def _op(login_user):
            flow, version = await ExternalWorkflowService.create_workflow_draft(
                login_user=login_user,
                name=name,
                graph_data=graph_data.model_dump(),
                description=description or None,
                guide_word=guide_word or None,
            )
            return WorkflowMutationResult(
                flow_id=flow.id,
                version_id=version.id,
                status='draft',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
            )
        return await _run_authenticated_tool('create_workflow_draft', _op, scope='workflow.write',
                                             error_builder=_mutation_error)

    @mcp.tool()
    async def update_workflow_draft(flow_id: str,
                                    graph_data: GraphData,
                                    name: str = '',
                                    description: str = '',
                                    guide_word: str = '',
                                    expected_revision: int = 0) -> WorkflowMutationResult:
        """Create a new draft version for an existing Bisheng workflow."""
        async def _op(login_user):
            _, version = await ExternalWorkflowService.update_workflow_draft(
                login_user=login_user,
                flow_id=flow_id,
                graph_data=graph_data.model_dump(),
                name=name or None,
                description=description or None,
                guide_word=guide_word or None,
                expected_revision=expected_revision if expected_revision >= 0 else None,
            )
            return WorkflowMutationResult(
                flow_id=flow_id,
                version_id=version.id,
                status='draft',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
            )
        return await _run_authenticated_tool('update_workflow_draft', _op, scope='workflow.write',
                                             error_builder=_mutation_error)

    @mcp.tool()
    async def add_node(flow_id: str,
                       node_type: str,
                       name: str = '',
                       position_x: float = 0,
                       position_y: float = 0,
                       initial_params: Optional[dict] = None,
                       version_id: int = 0,
                       expected_revision: int = 0) -> WorkflowMutationResult:
        """Add one node to the editable workflow graph."""
        async def _op(login_user):
            flow, version, node_id = await ExternalWorkflowService.add_workflow_node(
                login_user=login_user,
                flow_id=flow_id,
                node_type=node_type,
                name=name,
                position_x=position_x,
                position_y=position_y,
                initial_params=initial_params,
                version_id=version_id or None,
                expected_revision=expected_revision or None,
            )
            return WorkflowMutationResult(
                flow_id=flow.id,
                version_id=version.id,
                status='draft',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
                node_id=node_id,
            )
        return await _run_authenticated_tool('add_node', _op, scope='workflow.write',
                                             error_builder=_mutation_error)

    @mcp.tool()
    async def remove_node(flow_id: str,
                          node_id: str,
                          cascade: bool = True,
                          version_id: int = 0,
                          expected_revision: int = 0) -> WorkflowMutationResult:
        """Remove one node from the editable workflow graph."""
        async def _op(login_user):
            flow, version = await ExternalWorkflowService.remove_workflow_node(
                login_user=login_user,
                flow_id=flow_id,
                node_id=node_id,
                cascade=cascade,
                version_id=version_id or None,
                expected_revision=expected_revision or None,
            )
            return WorkflowMutationResult(
                flow_id=flow.id,
                version_id=version.id,
                status='draft',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
                node_id=node_id,
            )
        return await _run_authenticated_tool('remove_node', _op, scope='workflow.write',
                                             error_builder=_mutation_error)

    @mcp.tool()
    async def connect_nodes(flow_id: str,
                            source_node_id: str,
                            target_node_id: str,
                            source_handle: str,
                            target_handle: str,
                            version_id: int = 0,
                            expected_revision: int = 0) -> WorkflowMutationResult:
        """Connect two existing workflow nodes with one edge."""
        async def _op(login_user):
            flow, version, edge_id = await ExternalWorkflowService.connect_workflow_nodes(
                login_user=login_user,
                flow_id=flow_id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                source_handle=source_handle,
                target_handle=target_handle,
                version_id=version_id or None,
                expected_revision=expected_revision or None,
            )
            return WorkflowMutationResult(
                flow_id=flow.id,
                version_id=version.id,
                status='draft',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
                edge_id=edge_id,
            )
        return await _run_authenticated_tool('connect_nodes', _op, scope='workflow.write',
                                             error_builder=_mutation_error)

    @mcp.tool()
    async def disconnect_edge(flow_id: str,
                              edge_id: str = '',
                              source_node_id: str = '',
                              target_node_id: str = '',
                              source_handle: str = '',
                              target_handle: str = '',
                              version_id: int = 0,
                              expected_revision: int = 0) -> WorkflowMutationResult:
        """Disconnect one edge from the editable workflow graph."""
        async def _op(login_user):
            flow, version, removed_edge_id = await ExternalWorkflowService.disconnect_workflow_edge(
                login_user=login_user,
                flow_id=flow_id,
                edge_id=edge_id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                source_handle=source_handle,
                target_handle=target_handle,
                version_id=version_id or None,
                expected_revision=expected_revision or None,
            )
            return WorkflowMutationResult(
                flow_id=flow.id,
                version_id=version.id,
                status='draft',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
                edge_id=removed_edge_id,
            )
        return await _run_authenticated_tool('disconnect_edge', _op, scope='workflow.write',
                                             error_builder=_mutation_error)

    @mcp.tool()
    async def update_workflow_node_params(flow_id: str,
                                          node_id: str,
                                          updates: dict[str, object],
                                          version_id: int = 0,
                                          expected_revision: int = 0) -> WorkflowMutationResult:
        """Create a new draft version by patching one node's params, such as prompt or temperature."""
        async def _op(login_user):
            _, version = await ExternalWorkflowService.update_workflow_node_params(
                login_user=login_user,
                flow_id=flow_id,
                node_id=node_id,
                updates=updates,
                version_id=version_id or None,
                expected_revision=expected_revision if expected_revision >= 0 else None,
            )
            return WorkflowMutationResult(
                flow_id=flow_id,
                version_id=version.id,
                status='draft',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
            )
        return await _run_authenticated_tool('update_workflow_node_params', _op, scope='workflow.write',
                                             error_builder=_mutation_error)

    @mcp.tool()
    async def update_condition_node(flow_id: str,
                                    node_id: str,
                                    condition_cases: list[dict[str, object]],
                                    version_id: int = 0,
                                    expected_revision: int = 0) -> WorkflowMutationResult:
        """Update the structured condition cases of one existing condition node."""
        async def _op(login_user):
            flow, version = await ExternalWorkflowService.update_condition_node(
                login_user=login_user,
                flow_id=flow_id,
                node_id=node_id,
                condition_cases=condition_cases,
                version_id=version_id or None,
                expected_revision=expected_revision if expected_revision >= 0 else None,
            )
            return WorkflowMutationResult(
                flow_id=flow.id,
                version_id=version.id,
                status='draft',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
                node_id=node_id,
            )
        return await _run_authenticated_tool('update_condition_node', _op, scope='workflow.write',
                                             error_builder=_mutation_error)

    @mcp.tool()
    async def validate_workflow(flow_id: str, version_id: int) -> WorkflowValidationResult:
        """Validate a Bisheng workflow version without publishing it."""
        async def _op(login_user):
            flow, version = await ExternalWorkflowService.validate_workflow(
                login_user=login_user,
                flow_id=flow_id,
                version_id=version_id,
            )
            return WorkflowValidationResult(
                flow_id=flow.id,
                version_id=version.id,
                valid=True,
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
                diagnostics=[],
            )
        return await _run_authenticated_tool('validate_workflow', _op, scope='workflow.write',
                                             error_builder=_validation_error)

    @mcp.tool()
    async def publish_workflow(flow_id: str, version_id: int) -> WorkflowMutationResult:
        """Publish a validated Bisheng workflow version."""
        async def _op(login_user):
            flow, version = await ExternalWorkflowService.publish_workflow(
                login_user=login_user,
                flow_id=flow_id,
                version_id=version_id,
            )
            return WorkflowMutationResult(
                flow_id=flow.id,
                version_id=version.id,
                status='published',
                draft_revision=ExternalWorkflowService.get_graph_revision(version.data),
            )
        return await _run_authenticated_tool('publish_workflow', _op, scope='workflow.publish',
                                             error_builder=_mutation_error)

    return mcp


_workflow_mcp_server = create_workflow_mcp_server()


def get_workflow_mcp_server():
    return _workflow_mcp_server


def get_workflow_mcp_asgi_app():
    if _workflow_mcp_server is None:
        return None
    return McpAuthorizationMiddleware(_workflow_mcp_server.streamable_http_app())
