import asyncio
import re
from typing import Optional

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType
from bisheng.database.models.flow_version import FlowVersion, FlowVersionDao
from bisheng.database.models.role_access import RoleAccessDao, AccessType
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.workflow.authoring.contract import (
    ValidationDiagnostic,
    ValidationSeverity,
    WorkflowGraphDescriptor,
    WorkflowGraphNodeDescriptor,
    WorkflowManifest,
    WorkflowParamMetadata,
    WorkflowVersionSummary,
)
from bisheng.workflow.authoring.registry import get_node_template_descriptor, list_node_type_descriptors
from bisheng.workflow.authoring.registry import normalize_tab_descriptor
from bisheng.api.services.external_workflow import ExternalWorkflowService


class WorkflowAuthoringService:

    @staticmethod
    def _status_to_name(status: Optional[int]) -> str:
        if status == FlowStatus.ONLINE.value:
            return 'online'
        return 'offline'

    @classmethod
    def _editable_version_without_side_effect(cls, flow_id: str) -> tuple[Optional[FlowVersion], Optional[FlowVersion]]:
        current_version = FlowVersionDao.get_version_by_flow(flow_id)
        editable_version = ExternalWorkflowService._get_existing_external_draft_version(flow_id) or current_version
        return current_version, editable_version

    @classmethod
    def _build_manifest(cls, flow: Flow) -> WorkflowManifest:
        current_version, editable_version = cls._editable_version_without_side_effect(flow.id)
        draft_revision = ExternalWorkflowService.get_graph_revision(editable_version.data if editable_version else None)
        return WorkflowManifest(
            flow_id=flow.id,
            name=flow.name,
            description=flow.description,
            status=cls._status_to_name(flow.status),
            current_version_id=current_version.id if current_version else None,
            editable_version_id=editable_version.id if editable_version else None,
            draft_revision=draft_revision,
        )

    @classmethod
    async def _list_candidate_workflows(cls, login_user: UserPayload) -> list[Flow]:
        if login_user.is_admin():
            return FlowDao.get_flows(
                login_user.user_id,
                'admin',
                '',
                None,
                None,
                0,
                0,
                FlowType.WORKFLOW.value,
            )
        user_role = UserRoleDao.get_user_roles(login_user.user_id)
        role_ids = [role.role_id for role in user_role]
        role_access = RoleAccessDao.get_role_access_batch(role_ids, [AccessType.WORKFLOW, AccessType.WORKFLOW_WRITE])
        extra_ids = [access.third_id for access in role_access] if role_access else []
        return FlowDao.get_flows(
            login_user.user_id,
            extra_ids,
            '',
            None,
            None,
            0,
            0,
            FlowType.WORKFLOW.value,
        )

    @classmethod
    async def list_workflows(cls, login_user: UserPayload) -> list[WorkflowManifest]:
        candidates = await cls._list_candidate_workflows(login_user)
        permissions = await asyncio.gather(*[
            login_user.async_access_check(flow.user_id, flow.id, AccessType.WORKFLOW_WRITE) for flow in candidates
        ])
        return [cls._build_manifest(flow) for flow, allowed in zip(candidates, permissions) if allowed]

    @classmethod
    async def get_workflow(cls, login_user: UserPayload, flow_id: str) -> WorkflowManifest:
        flow = await ExternalWorkflowService._get_workflow_with_write_access(login_user, flow_id)
        return cls._build_manifest(flow)

    @classmethod
    async def get_workflow_versions(cls, login_user: UserPayload, flow_id: str) -> list[WorkflowVersionSummary]:
        flow = await ExternalWorkflowService._get_workflow_with_write_access(login_user, flow_id)
        current_version, editable_version = cls._editable_version_without_side_effect(flow.id)
        versions = FlowVersionDao.get_list_by_flow(flow.id)
        detailed_versions = {
            version.id: FlowVersionDao.get_version_by_id(version.id)
            for version in versions
        }
        return [
            WorkflowVersionSummary(
                version_id=version.id,
                name=version.name,
                description=version.description,
                is_current=version.is_current == 1,
                is_editable=editable_version is not None and version.id == editable_version.id,
                is_external_draft=detailed_versions[version.id] is not None
                and ExternalWorkflowService._is_draft_graph(detailed_versions[version.id].data),
                original_version_id=detailed_versions[version.id].original_version_id
                if detailed_versions[version.id] else None,
                draft_revision=ExternalWorkflowService.get_graph_revision(
                    detailed_versions[version.id].data if detailed_versions[version.id] else None
                ),
                create_time=version.create_time,
                update_time=version.update_time,
            )
            for version in versions
        ]

    @classmethod
    def _normalize_node_params(cls, node: dict) -> dict[str, WorkflowParamMetadata]:
        try:
            fields = ExternalWorkflowService._get_node_param_fields(node)
        except NotFoundError:
            return {}
        return {
            key: WorkflowParamMetadata(**ExternalWorkflowService._build_param_payload(group_name, value))
            for key, (group_name, value) in fields.items()
        }

    @classmethod
    def _normalize_graph_node(cls, node: dict) -> WorkflowGraphNodeDescriptor:
        node_data = node.get('data', {})
        node_type = node_data.get('type') or node.get('type', '')
        tab = node_data.get('tab')
        node_template = get_node_template_descriptor(node_type)
        params = cls._normalize_node_params(node)
        return WorkflowGraphNodeDescriptor(
            id=node.get('id', ''),
            type=node_type,
            name=node_data.get('name') or node_data.get('node', {}).get('display_name', ''),
            description=node_data.get('description'),
            tab=normalize_tab_descriptor(tab) if tab else (node_template.tab if node_template else None),
            param_keys=list(params.keys()),
            params=params,
        )

    @classmethod
    async def get_workflow_graph(cls,
                                 login_user: UserPayload,
                                 flow_id: str,
                                 version_id: Optional[int] = None) -> WorkflowGraphDescriptor:
        _, version = await ExternalWorkflowService._get_editable_version(login_user, flow_id, version_id)
        graph_data = version.data or {}
        return WorkflowGraphDescriptor(
            flow_id=flow_id,
            version_id=version.id,
            draft_revision=ExternalWorkflowService.get_graph_revision(graph_data),
            nodes=[cls._normalize_graph_node(node) for node in graph_data.get('nodes', [])],
            edges=list(graph_data.get('edges', [])),
        )

    @staticmethod
    def list_node_types():
        return list_node_type_descriptors()

    @staticmethod
    def get_node_template(node_type: str):
        template = get_node_template_descriptor(node_type)
        if template is None:
            raise NotFoundError(msg=f'Workflow node template not found: {node_type}')
        return template

    @staticmethod
    def diagnostics_from_exception(exc: Exception) -> list[ValidationDiagnostic]:
        code = ''
        if isinstance(exc, BaseErrorCode):
            code = str(exc.code)
            message = exc.message
        else:
            message = str(exc) or exc.__class__.__name__
        node_id = None
        field_path = None
        suggested_fix = None

        node_match = re.search(r'Node ([\w-]+)', message)
        if node_match:
            node_id = node_match.group(1)
        elif 'Workflow node not found:' in message:
            node_id = message.rsplit(':', 1)[-1].strip()

        param_match = re.search(r'Param ([\w.\-]+)', message)
        if param_match:
            field_path = param_match.group(1)
            suggested_fix = 'Review the parameter value and node template requirements.'
        elif 'Edge source not found:' in message:
            field_path = 'edges.source'
            suggested_fix = 'Ensure the edge source points to an existing node id.'
        elif 'Edge target not found:' in message:
            field_path = 'edges.target'
            suggested_fix = 'Ensure the edge target points to an existing node id.'
        elif 'must contain at least one node' in message:
            field_path = 'nodes'
            suggested_fix = 'Add at least one workflow node before validating or publishing.'

        return [
            ValidationDiagnostic(
                code=code,
                severity=ValidationSeverity.ERROR,
                message=message,
                node_id=node_id,
                field_path=field_path,
                suggested_fix=suggested_fix,
            )
        ]
