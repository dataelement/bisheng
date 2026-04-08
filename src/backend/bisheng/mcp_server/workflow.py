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
    if isinstance(exc, BaseErrorCode):
        return WorkflowMutationResult(ok=False, message=exc.message, error_code=exc.code)
    return WorkflowMutationResult(ok=False, message=str(exc) or exc.__class__.__name__)


def _validation_error(exc: Exception) -> WorkflowValidationResult:
    if isinstance(exc, BaseErrorCode):
        return WorkflowValidationResult(
            ok=False,
            valid=False,
            errors=[exc.message],
            diagnostics=WorkflowAuthoringService.diagnostics_from_exception(exc),
            error_code=exc.code,
        )
    return WorkflowValidationResult(
        ok=False,
        valid=False,
        errors=[str(exc) or exc.__class__.__name__],
        diagnostics=WorkflowAuthoringService.diagnostics_from_exception(exc),
    )


def _node_list_error(exc: Exception) -> WorkflowNodeListResult:
    if isinstance(exc, BaseErrorCode):
        return WorkflowNodeListResult(ok=False, message=exc.message, error_code=exc.code)
    return WorkflowNodeListResult(ok=False, message=str(exc) or exc.__class__.__name__)


def _node_params_error(exc: Exception) -> WorkflowNodeParamsResult:
    if isinstance(exc, BaseErrorCode):
        return WorkflowNodeParamsResult(ok=False, message=exc.message, error_code=exc.code)
    return WorkflowNodeParamsResult(ok=False, message=str(exc) or exc.__class__.__name__)


def _workflow_manifest_error(exc: Exception) -> WorkflowManifestResult:
    if isinstance(exc, BaseErrorCode):
        return WorkflowManifestResult(ok=False, message=exc.message, error_code=exc.code)
    return WorkflowManifestResult(ok=False, message=str(exc) or exc.__class__.__name__)


def _workflow_manifest_list_error(exc: Exception) -> WorkflowManifestListResult:
    if isinstance(exc, BaseErrorCode):
        return WorkflowManifestListResult(ok=False, message=exc.message, error_code=exc.code)
    return WorkflowManifestListResult(ok=False, message=str(exc) or exc.__class__.__name__)


def _workflow_version_list_error(exc: Exception) -> WorkflowVersionListResult:
    if isinstance(exc, BaseErrorCode):
        return WorkflowVersionListResult(ok=False, message=exc.message, error_code=exc.code)
    return WorkflowVersionListResult(ok=False, message=str(exc) or exc.__class__.__name__)


def _workflow_graph_error(exc: Exception) -> WorkflowGraphResult:
    if isinstance(exc, BaseErrorCode):
        return WorkflowGraphResult(ok=False, message=exc.message, error_code=exc.code)
    return WorkflowGraphResult(ok=False, message=str(exc) or exc.__class__.__name__)


def _node_type_list_error(exc: Exception) -> NodeTypeListResult:
    if isinstance(exc, BaseErrorCode):
        return NodeTypeListResult(ok=False, message=exc.message, error_code=exc.code)
    return NodeTypeListResult(ok=False, message=str(exc) or exc.__class__.__name__)


def _node_template_result_error(exc: Exception) -> NodeTemplateResult:
    if isinstance(exc, BaseErrorCode):
        return NodeTemplateResult(ok=False, message=exc.message, error_code=exc.code)
    return NodeTemplateResult(ok=False, message=str(exc) or exc.__class__.__name__)


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

    @mcp.tool()
    async def ping() -> WorkflowConnectionResult:
        """Verify the MCP connection and return the current authenticated Bisheng user."""
        try:
            login_user = await get_login_user_from_mcp_token()
            return WorkflowConnectionResult(
                user_id=login_user.user_id,
                user_name=login_user.user_name,
                scopes=list(get_current_token_scopes()),
            )
        except Exception as exc:
            logger.exception('ping failed')
            if isinstance(exc, BaseErrorCode):
                return WorkflowConnectionResult(
                    ok=False,
                    authenticated=False,
                    message=exc.message,
                    error_code=exc.code,
                )
            return WorkflowConnectionResult(
                ok=False,
                authenticated=False,
                message=str(exc) or exc.__class__.__name__,
            )

    @mcp.tool()
    async def whoami() -> WorkflowConnectionResult:
        """Return the authenticated Bisheng user behind the current MCP bearer token."""
        try:
            login_user = await get_login_user_from_mcp_token()
            return WorkflowConnectionResult(
                user_id=login_user.user_id,
                user_name=login_user.user_name,
                scopes=list(get_current_token_scopes()),
            )
        except Exception as exc:
            logger.exception('whoami failed')
            if isinstance(exc, BaseErrorCode):
                return WorkflowConnectionResult(
                    ok=False,
                    authenticated=False,
                    message=exc.message,
                    error_code=exc.code,
                )
            return WorkflowConnectionResult(
                ok=False,
                authenticated=False,
                message=str(exc) or exc.__class__.__name__,
            )

    @mcp.tool()
    async def list_workflows() -> WorkflowManifestListResult:
        """List workflows the current MCP user can author."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.read')
            workflows = await WorkflowAuthoringService.list_workflows(login_user)
            return WorkflowManifestListResult(workflows=workflows)
        except Exception as exc:
            logger.exception('list_workflows failed')
            return _workflow_manifest_list_error(exc)

    @mcp.tool()
    async def get_workflow(flow_id: str) -> WorkflowManifestResult:
        """Return manifest information for one authorable workflow."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.read')
            workflow = await WorkflowAuthoringService.get_workflow(login_user, flow_id)
            return WorkflowManifestResult(workflow=workflow)
        except Exception as exc:
            logger.exception('get_workflow failed')
            return _workflow_manifest_error(exc)

    @mcp.tool()
    async def get_workflow_versions(flow_id: str) -> WorkflowVersionListResult:
        """List versions for one authorable workflow."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.read')
            versions = await WorkflowAuthoringService.get_workflow_versions(login_user, flow_id)
            return WorkflowVersionListResult(flow_id=flow_id, versions=versions)
        except Exception as exc:
            logger.exception('get_workflow_versions failed')
            return _workflow_version_list_error(exc)

    @mcp.tool()
    async def get_workflow_graph(flow_id: str, version_id: int = 0) -> WorkflowGraphResult:
        """Return the normalized editable graph for a workflow."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.read')
            graph = await WorkflowAuthoringService.get_workflow_graph(
                login_user=login_user,
                flow_id=flow_id,
                version_id=version_id or None,
            )
            return WorkflowGraphResult(graph=graph)
        except Exception as exc:
            logger.exception('get_workflow_graph failed')
            return _workflow_graph_error(exc)

    @mcp.tool()
    async def list_node_types() -> NodeTypeListResult:
        """List supported workflow node types for authoring."""
        try:
            await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.read')
            return NodeTypeListResult(node_types=WorkflowAuthoringService.list_node_types())
        except Exception as exc:
            logger.exception('list_node_types failed')
            return _node_type_list_error(exc)

    @mcp.tool()
    async def get_node_template(node_type: str) -> NodeTemplateResult:
        """Return the normalized template metadata for one workflow node type."""
        try:
            await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.read')
            return NodeTemplateResult(template=WorkflowAuthoringService.get_node_template(node_type))
        except Exception as exc:
            logger.exception('get_node_template failed')
            return _node_template_result_error(exc)

    @mcp.tool()
    async def list_workflow_nodes(flow_id: str, version_id: int = 0) -> WorkflowNodeListResult:
        """List nodes in a workflow version so the caller can choose a node_id to edit."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.read')
            data = await ExternalWorkflowService.list_workflow_nodes(
                login_user=login_user,
                flow_id=flow_id,
                version_id=version_id or None,
            )
            return WorkflowNodeListResult(**data)
        except Exception as exc:
            logger.exception('list_workflow_nodes failed')
            return _node_list_error(exc)

    @mcp.tool()
    async def get_workflow_node_params(flow_id: str,
                                       node_id: str,
                                       version_id: int = 0) -> WorkflowNodeParamsResult:
        """Read the current editable params of a workflow node."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.read')
            data = await ExternalWorkflowService.get_workflow_node_params(
                login_user=login_user,
                flow_id=flow_id,
                node_id=node_id,
                version_id=version_id or None,
            )
            return WorkflowNodeParamsResult(**data)
        except Exception as exc:
            logger.exception('get_workflow_node_params failed')
            return _node_params_error(exc)

    @mcp.tool()
    async def create_workflow_draft(name: str,
                                    graph_data: GraphData,
                                    description: str = '',
                                    guide_word: str = '') -> WorkflowMutationResult:
        """Create a new Bisheng workflow draft for the current logged-in user."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.write')
            flow, version = ExternalWorkflowService.create_workflow_draft(
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
        except Exception as exc:
            logger.exception('create_workflow_draft failed')
            return _mutation_error(exc)

    @mcp.tool()
    async def update_workflow_draft(flow_id: str,
                                    graph_data: GraphData,
                                    name: str = '',
                                    description: str = '',
                                    guide_word: str = '',
                                    expected_revision: int = 0) -> WorkflowMutationResult:
        """Create a new draft version for an existing Bisheng workflow."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.write')
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
        except Exception as exc:
            logger.exception('update_workflow_draft failed')
            return _mutation_error(exc)

    @mcp.tool()
    async def update_workflow_node_params(flow_id: str,
                                          node_id: str,
                                          updates: dict[str, object],
                                          version_id: int = 0,
                                          expected_revision: int = 0) -> WorkflowMutationResult:
        """Create a new draft version by patching one node's params, such as prompt or temperature."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.write')
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
        except Exception as exc:
            logger.exception('update_workflow_node_params failed')
            return _mutation_error(exc)

    @mcp.tool()
    async def validate_workflow(flow_id: str, version_id: int) -> WorkflowValidationResult:
        """Validate a Bisheng workflow version without publishing it."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.write')
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
        except Exception as exc:
            logger.exception('validate_workflow failed')
            return _validation_error(exc)

    @mcp.tool()
    async def publish_workflow(flow_id: str, version_id: int) -> WorkflowMutationResult:
        """Publish a validated Bisheng workflow version."""
        try:
            login_user = await get_login_user_from_mcp_token()
            require_mcp_scopes('workflow.publish')
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
        except Exception as exc:
            logger.exception('publish_workflow failed')
            return _mutation_error(exc)

    return mcp


_workflow_mcp_server = create_workflow_mcp_server()


def get_workflow_mcp_server():
    return _workflow_mcp_server


def get_workflow_mcp_asgi_app():
    if _workflow_mcp_server is None:
        return None
    return McpAuthorizationMiddleware(_workflow_mcp_server.streamable_http_app())
