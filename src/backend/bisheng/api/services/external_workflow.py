import asyncio
import copy
import time
from typing import Optional

from fastapi import Request
from sqlmodel import select

from bisheng.api.services.flow import FlowService
from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import (NotFoundVersionError, WorkflowNameExistsError,
                                         WorkFlowInitError, WorkFlowOnlineEditError, WorkFlowVersionUpdateError)
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType
from bisheng.database.models.flow_version import FlowVersion, FlowVersionDao
from bisheng.database.models.role_access import AccessType
from bisheng.utils import generate_uuid
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.edges.edges import EdgeBase
from bisheng.workflow.graph.workflow import Workflow
from bisheng.workflow.authoring.editor_compat import normalize_workflow_editor_graph
from bisheng.workflow.authoring.registry import create_graph_node_payload
from bisheng.workflow.nodes.condition.conidition_case import ConditionCases


class ExternalWorkflowService:
    _DRAFT_META_KEY = '_external_workflow_meta'
    _DRAFT_SOURCE = 'clawith_mcp'
    _MAX_EXTERNAL_DRAFT_SCAN = 20
    _WORKFLOW_VALIDATION_MAX_STEPS = 10
    _WORKFLOW_VALIDATION_TIMEOUT_SECONDS = 10
    _CONDITION_NODE_TYPE = 'condition'
    _CONDITION_PARAM_KEY = 'condition'
    _CONDITION_FALLBACK_HANDLE = 'right_handle'
    _DEFAULT_SOURCE_HANDLE = 'right_handle'
    _DEFAULT_TARGET_HANDLE = 'left_handle'
    _DEFAULT_HORIZONTAL_NODE_GAP = 320
    _NOTE_NODE_TYPE = NodeType.NOTE.value
    _EDITOR_FLOW_NODE_TYPE = 'flowNode'
    _EDITOR_NOTE_NODE_TYPE = 'noteNode'
    _START_NODE_TYPE = NodeType.START.value
    _END_NODE_TYPE = NodeType.END.value
    _SENSITIVE_KEY_PATTERNS = (
        'password',
        'token',
        'secret',
        'api_key',
        'apikey',
        'credential',
        'auth',
        'cookie',
    )
    _BLOCKED_FIELD_TYPES = {'file', 'password'}

    @staticmethod
    def _internal_request() -> Request:
        scope = {
            'type': 'http',
            'method': 'POST',
            'path': '/mcp/workflow',
            'headers': [],
            'query_string': b'',
            'client': ('127.0.0.1', 0),
            'server': ('127.0.0.1', 80),
            'scheme': 'http',
            'root_path': '',
            'http_version': '1.1',
        }
        return Request(scope)

    @staticmethod
    def _next_version_name() -> str:
        return f'draft-{int(time.time() * 1000)}'

    @classmethod
    def _raise_workflow_error(cls, message: str):
        raise WorkFlowInitError(msg=message)

    @classmethod
    def _assert_workflow_name_available(cls,
                                        login_user: UserPayload,
                                        name: str,
                                        exclude_flow_id: Optional[str] = None):
        with get_sync_db_session() as session:
            statement = select(Flow).where(
                Flow.name == name,
                Flow.flow_type == FlowType.WORKFLOW.value,
                Flow.user_id == login_user.user_id,
            )
            exists = session.exec(statement).first()
        if exists and exists.id != exclude_flow_id:
            raise WorkflowNameExistsError()

    @classmethod
    def _mark_graph_as_draft(cls, graph_data: dict, *, in_place: bool = False) -> dict:
        updated_graph = graph_data if in_place else copy.deepcopy(graph_data)
        current_meta = updated_graph.get(cls._DRAFT_META_KEY, {})
        if not isinstance(current_meta, dict):
            current_meta = {}
        updated_graph[cls._DRAFT_META_KEY] = {
            'draft': True,
            'source': cls._DRAFT_SOURCE,
            'revision': int(current_meta.get('revision', 0)) + 1,
            'updated_at': int(time.time() * 1000),
        }
        return updated_graph

    @classmethod
    def _clear_graph_draft_marker(cls, graph_data: dict, *, in_place: bool = False) -> dict:
        updated_graph = graph_data if in_place else copy.deepcopy(graph_data)
        updated_graph.pop(cls._DRAFT_META_KEY, None)
        return updated_graph

    @classmethod
    def _is_draft_graph(cls, graph_data: Optional[dict]) -> bool:
        if not isinstance(graph_data, dict):
            return False
        meta = graph_data.get(cls._DRAFT_META_KEY, {})
        return isinstance(meta, dict) and meta.get('draft') is True

    @classmethod
    def get_graph_revision(cls, graph_data: Optional[dict]) -> int:
        if not isinstance(graph_data, dict):
            return 0
        meta = graph_data.get(cls._DRAFT_META_KEY, {})
        if not isinstance(meta, dict):
            return 0
        try:
            return int(meta.get('revision', 0) or 0)
        except Exception:
            return 0

    @classmethod
    def _assert_expected_revision(cls, graph_data: Optional[dict], expected_revision: Optional[int]):
        if expected_revision is None:
            return
        current_revision = cls.get_graph_revision(graph_data)
        if current_revision != expected_revision:
            raise WorkFlowVersionUpdateError(
                msg=f'Workflow draft revision mismatch, expected {expected_revision}, got {current_revision}'
            )

    @classmethod
    def _validate_graph_structure(cls, graph_data: dict):
        if not isinstance(graph_data, dict):
            cls._raise_workflow_error('Workflow graph must be a JSON object')

        nodes = graph_data.get('nodes')
        edges = graph_data.get('edges')
        if not isinstance(nodes, list):
            cls._raise_workflow_error('Workflow graph must contain a nodes array')
        if not isinstance(edges, list):
            cls._raise_workflow_error('Workflow graph must contain an edges array')
        if not nodes:
            cls._raise_workflow_error('Workflow graph must contain at least one node')

        node_ids: set[str] = set()
        for index, raw_node in enumerate(nodes):
            if not isinstance(raw_node, dict):
                cls._raise_workflow_error(f'Node at index {index} must be an object')
            node_data = raw_node.get('data')
            if not isinstance(node_data, dict):
                cls._raise_workflow_error(f'Node {raw_node.get("id", index)} must contain a data object')
            try:
                parsed_node = BaseNodeData(**node_data)
            except Exception as exc:
                cls._raise_workflow_error(f'Invalid node structure for {raw_node.get("id", index)}: {exc}')
            if raw_node.get('id') != parsed_node.id:
                cls._raise_workflow_error(f'Node id mismatch for {raw_node.get("id", index)}')
            if parsed_node.id in node_ids:
                cls._raise_workflow_error(f'Duplicate node id: {parsed_node.id}')
            node_ids.add(parsed_node.id)
            cls._validate_node_group_params(parsed_node.id, node_data.get('group_params'))

        for index, raw_edge in enumerate(edges):
            if not isinstance(raw_edge, dict):
                cls._raise_workflow_error(f'Edge at index {index} must be an object')
            try:
                parsed_edge = EdgeBase(**raw_edge)
            except Exception as exc:
                cls._raise_workflow_error(f'Invalid edge structure at index {index}: {exc}')
            if parsed_edge.source not in node_ids:
                cls._raise_workflow_error(f'Edge source not found: {parsed_edge.source}')
            if parsed_edge.target not in node_ids:
                cls._raise_workflow_error(f'Edge target not found: {parsed_edge.target}')

    @classmethod
    def _validate_node_group_params(cls, node_id: str, group_params):
        if group_params is None:
            return
        if not isinstance(group_params, list):
            cls._raise_workflow_error(f'Node {node_id} group_params must be a list')
        seen_keys: set[str] = set()
        for group_index, group in enumerate(group_params):
            if not isinstance(group, dict):
                cls._raise_workflow_error(f'Node {node_id} group {group_index} must be an object')
            params = group.get('params', [])
            if not isinstance(params, list):
                cls._raise_workflow_error(f'Node {node_id} group {group_index} params must be a list')
            for param_index, param in enumerate(params):
                if not isinstance(param, dict):
                    cls._raise_workflow_error(
                        f'Node {node_id} param at group {group_index} index {param_index} must be an object'
                    )
                key = param.get('key')
                if not key or not isinstance(key, str):
                    cls._raise_workflow_error(f'Node {node_id} has a param without a valid key')
                if key in seen_keys:
                    cls._raise_workflow_error(f'Node {node_id} has duplicate param key: {key}')
                seen_keys.add(key)

    @classmethod
    def _validate_condition_node_routes(cls, graph_data: dict, node_id: str, condition_cases: list[dict]):
        valid_handles = {one['id'] for one in condition_cases}
        valid_handles.add(cls._CONDITION_FALLBACK_HANDLE)
        outgoing_handles = {
            (edge.get('sourceHandle') or '')
            for edge in graph_data.get('edges', [])
            if edge.get('source') == node_id
        }
        stale_handles = sorted(handle for handle in outgoing_handles if handle not in valid_handles)
        if stale_handles:
            cls._raise_workflow_error(
                f'Condition node {node_id} has stale route handles: {", ".join(stale_handles)}'
            )

        missing_handles = [one['id'] for one in condition_cases if one['id'] not in outgoing_handles]
        if missing_handles:
            cls._raise_workflow_error(
                f'Condition node {node_id} is missing route edges for: {", ".join(missing_handles)}'
            )

        if cls._CONDITION_FALLBACK_HANDLE not in outgoing_handles:
            cls._raise_workflow_error(
                f'Condition node {node_id} is missing fallback route edge: {cls._CONDITION_FALLBACK_HANDLE}'
            )

    @classmethod
    def _validate_special_node_routes(cls, graph_data: dict):
        for raw_node in graph_data.get('nodes', []):
            node_id = raw_node.get('id', '')
            node_data = raw_node.get('data', {})
            if not isinstance(node_data, dict):
                continue
            if node_data.get('type') != cls._CONDITION_NODE_TYPE:
                continue
            condition_field = cls._get_node_param_field(raw_node, cls._CONDITION_PARAM_KEY)
            condition_cases = cls._normalize_condition_cases(condition_field.get('value') or [])
            cls._validate_condition_node_routes(graph_data, node_id, condition_cases)

    @classmethod
    def _validate_workflow_runtime(cls, login_user: UserPayload, graph_data: dict, flow_name: str, flow_id: Optional[str] = None):
        try:
            Workflow(
                workflow_id=flow_id or f'draft_{generate_uuid()}',
                workflow_name=flow_name or 'draft-workflow',
                user_id=login_user.user_id,
                workflow_data=graph_data,
                async_mode=False,
                max_steps=cls._WORKFLOW_VALIDATION_MAX_STEPS,
                timeout=cls._WORKFLOW_VALIDATION_TIMEOUT_SECONDS,
                callback=None,
            )
        except Exception as exc:
            raise WorkFlowInitError(exception=exc, msg=str(exc))

    @classmethod
    def _validate_draft_graph(cls,
                              login_user: UserPayload,
                              graph_data: dict,
                              flow_name: str,
                              flow_id: Optional[str] = None):
        cls._validate_graph_structure(graph_data)
        cls._validate_special_node_routes(graph_data)
        cls._validate_workflow_runtime(login_user, graph_data, flow_name=flow_name, flow_id=flow_id)

    @classmethod
    async def _get_base_version(cls, login_user: UserPayload, flow_id: str, version_id: Optional[int] = None) -> tuple[Flow, FlowVersion]:
        flow = await cls._get_workflow_with_write_access(login_user, flow_id)
        if version_id is None:
            version = cls._get_existing_external_draft_version(flow_id)
            if version:
                return flow, version
            current_version = FlowVersionDao.get_version_by_flow(flow_id)
            if not current_version:
                raise NotFoundVersionError()
            return flow, current_version
        version = await cls._get_workflow_version(flow_id, version_id)
        return flow, version

    @classmethod
    def _get_existing_external_draft_version(cls, flow_id: str) -> Optional[FlowVersion]:
        offset = 0
        while True:
            with get_sync_db_session() as session:
                statement = select(FlowVersion).where(
                    FlowVersion.flow_id == flow_id,
                    FlowVersion.is_delete == 0,
                ).order_by(FlowVersion.id.desc()).limit(cls._MAX_EXTERNAL_DRAFT_SCAN).offset(offset)
                versions = session.exec(statement).all()
            for version in versions:
                if cls._is_draft_graph(version.data):
                    return version
            if len(versions) < cls._MAX_EXTERNAL_DRAFT_SCAN:
                break
            offset += cls._MAX_EXTERNAL_DRAFT_SCAN
        return None

    @classmethod
    def _create_external_draft_version(cls,
                                       login_user: UserPayload,
                                       flow: Flow,
                                       base_version: FlowVersion) -> FlowVersion:
        flow_version = FlowVersion(
            flow_id=flow.id,
            name=cls._next_version_name(),
            description=f'Editable draft created by external MCP at {int(time.time())}',
            user_id=login_user.user_id,
            data=cls._mark_graph_as_draft(base_version.data),
            original_version_id=base_version.id,
            flow_type=FlowType.WORKFLOW.value,
        )
        return FlowVersionDao.create_version(flow_version)

    @classmethod
    async def _get_editable_version(cls,
                                    login_user: UserPayload,
                                    flow_id: str,
                                    version_id: Optional[int] = None) -> tuple[Flow, FlowVersion]:
        flow, version = await cls._get_base_version(login_user, flow_id, version_id)
        if flow.status != FlowStatus.ONLINE.value:
            return flow, version
        if cls._is_draft_graph(version.data):
            return flow, version
        existing_draft = cls._get_existing_external_draft_version(flow_id)
        if existing_draft:
            return flow, existing_draft
        return flow, cls._create_external_draft_version(login_user, flow, version)

    @staticmethod
    def _find_node(graph_data: dict, node_id: str) -> dict:
        for node in graph_data.get('nodes', []):
            if node.get('id') == node_id:
                return node
        raise NotFoundError(msg=f'Workflow node not found: {node_id}')

    @staticmethod
    def _find_node_index(graph_data: dict, node_id: str) -> int:
        for index, node in enumerate(graph_data.get('nodes', [])):
            if node.get('id') == node_id:
                return index
        raise NotFoundError(msg=f'Workflow node not found: {node_id}')

    @staticmethod
    def _find_edge_index(graph_data: dict, edge_id: str) -> int:
        for index, edge in enumerate(graph_data.get('edges', [])):
            if edge.get('id') == edge_id:
                return index
        raise NotFoundError(msg=f'Workflow edge not found: {edge_id}')

    @staticmethod
    def _get_node_type(node: dict) -> str:
        return node.get('data', {}).get('type') or node.get('type', '')

    @classmethod
    def _assert_condition_node(cls, node: dict, node_id: str):
        if cls._get_node_type(node) != cls._CONDITION_NODE_TYPE:
            cls._raise_workflow_error(f'Workflow node {node_id} is not a condition node')

    @staticmethod
    def _get_node_template(node: dict) -> dict:
        template = node.get('data', {}).get('node', {}).get('template')
        if not isinstance(template, dict):
            raise NotFoundError(msg='Workflow node template not found')
        return template

    @staticmethod
    def _get_node_group_params(node: dict) -> list[dict]:
        group_params = node.get('data', {}).get('group_params')
        if not isinstance(group_params, list):
            raise NotFoundError(msg='Workflow node group_params not found')
        return group_params

    @staticmethod
    def _get_editable_param_keys(template: dict) -> list[str]:
        keys = []
        for key, value in template.items():
            if key.startswith('_'):
                continue
            if isinstance(value, dict):
                keys.append(key)
        return keys

    @classmethod
    def _is_sensitive_param_field(cls, key: str, field: dict) -> bool:
        lowered_key = key.lower()
        if any(pattern in lowered_key for pattern in cls._SENSITIVE_KEY_PATTERNS):
            return True
        display_name = str(field.get('display_name') or field.get('label') or '').lower()
        if any(pattern in display_name for pattern in cls._SENSITIVE_KEY_PATTERNS):
            return True
        if field.get('password') is True:
            return True
        if field.get('type') in cls._BLOCKED_FIELD_TYPES:
            return True
        return False

    @classmethod
    def _is_editable_param_field(cls, key: str, field: dict) -> bool:
        if field.get('show') is False:
            return False
        if cls._is_sensitive_param_field(key, field):
            return False
        return True

    @classmethod
    def _iter_node_param_fields(cls, node: dict):
        group_params = node.get('data', {}).get('group_params')
        if isinstance(group_params, list):
            for group in group_params:
                group_name = group.get('name', '')
                for field in group.get('params', []) or []:
                    if isinstance(field, dict) and field.get('key'):
                        yield group_name, field
            return

        template = node.get('data', {}).get('node', {}).get('template')
        if isinstance(template, dict):
            for key, field in template.items():
                if key.startswith('_') or not isinstance(field, dict):
                    continue
                normalized_field = copy.deepcopy(field)
                normalized_field.setdefault('key', key)
                normalized_field.setdefault('label', field.get('display_name', key))
                yield '', normalized_field

    @classmethod
    def _get_node_param_field(cls, node: dict, key: str) -> dict:
        for _group_name, field in cls._iter_node_param_fields(node):
            if field.get('key') == key:
                return field
        raise NotFoundError(msg=f'Workflow node param not found: {key}')

    @classmethod
    def _get_node_param_fields(cls, node: dict) -> dict[str, tuple[str, dict]]:
        fields = {}
        for group_name, field in cls._iter_node_param_fields(node):
            if cls._is_editable_param_field(field['key'], field):
                fields[field['key']] = (group_name, field)
        if not fields:
            raise NotFoundError(msg='Workflow node params not found')
        return fields

    @classmethod
    def _get_editable_node_param_keys(cls, node: dict) -> list[str]:
        return list(cls._get_node_param_fields(node).keys())

    @classmethod
    def _coerce_bool(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {'true', '1', 'yes', 'on'}:
                return True
            if lowered in {'false', '0', 'no', 'off'}:
                return False
        cls._raise_workflow_error(f'Expected boolean value, got {value!r}')

    @classmethod
    def _coerce_param_value(cls, field: dict, value):
        current_value = field.get('value')
        field_type = field.get('type')

        if field.get('required') and value in (None, '', []):
            cls._raise_workflow_error(f'Param {field.get("key")} is required')

        if isinstance(current_value, bool):
            normalized = cls._coerce_bool(value)
        elif isinstance(current_value, int) and not isinstance(current_value, bool):
            try:
                normalized = int(value)
            except Exception:
                cls._raise_workflow_error(f'Param {field.get("key")} expects an integer')
        elif isinstance(current_value, float):
            try:
                normalized = float(value)
            except Exception:
                cls._raise_workflow_error(f'Param {field.get("key")} expects a float')
        elif isinstance(current_value, list):
            if not isinstance(value, list):
                cls._raise_workflow_error(f'Param {field.get("key")} expects a list')
            normalized = value
        elif isinstance(current_value, dict):
            if not isinstance(value, dict):
                cls._raise_workflow_error(f'Param {field.get("key")} expects an object')
            normalized = value
        elif field_type in {'slide', 'float'}:
            try:
                normalized = float(value)
            except Exception:
                cls._raise_workflow_error(f'Param {field.get("key")} expects a float')
        elif field_type in {'switch', 'bool'}:
            normalized = cls._coerce_bool(value)
        elif field_type in {'bisheng_model'}:
            try:
                normalized = int(value)
            except Exception:
                cls._raise_workflow_error(f'Param {field.get("key")} expects a model id integer')
        elif field_type in {'var', 'image_prompt', 'user_question'}:
            if not isinstance(value, list):
                cls._raise_workflow_error(f'Param {field.get("key")} expects a list')
            normalized = value
        else:
            if not isinstance(value, str):
                cls._raise_workflow_error(f'Param {field.get("key")} expects a string')
            normalized = value

        scope = field.get('scope')
        if isinstance(scope, list) and len(scope) == 2 and isinstance(normalized, (int, float)):
            if normalized < scope[0] or normalized > scope[1]:
                cls._raise_workflow_error(
                    f'Param {field.get("key")} must be within scope [{scope[0]}, {scope[1]}]'
                )

        options = field.get('options')
        if isinstance(options, list) and options:
            allowed_values = set()
            for option in options:
                if isinstance(option, dict):
                    if 'key' in option:
                        allowed_values.add(option['key'])
                    if 'value' in option:
                        allowed_values.add(option['value'])
                else:
                    allowed_values.add(option)
            if allowed_values and normalized not in allowed_values:
                cls._raise_workflow_error(
                    f'Param {field.get("key")} must be one of {sorted(allowed_values)}'
                )
        return normalized

    @staticmethod
    def _build_param_payload(group_name: str, value: dict) -> dict:
        key = value['key']
        return {
            'display_name': value.get('display_name') or value.get('label') or value.get('name') or key,
            'group_name': group_name,
            'type': value.get('type'),
            'required': value.get('required', False),
            'show': value.get('show', True),
            'options': value.get('options'),
            'scope': value.get('scope'),
            'placeholder': value.get('placeholder'),
            'refresh': value.get('refresh', False),
            'value': value.get('value'),
        }

    @classmethod
    def _next_graph_node_id(cls, node_type: str) -> str:
        return f'{node_type}_{generate_uuid()[:8]}'

    @classmethod
    def _next_graph_edge_id(cls) -> str:
        return f'edge_{generate_uuid()[:8]}'

    @staticmethod
    def _node_position_value(node: dict, axis: str) -> float:
        position = node.get('position', {})
        if not isinstance(position, dict):
            return 0.0
        value = position.get(axis, 0)
        try:
            return float(value)
        except Exception:
            return 0.0

    @classmethod
    def _node_type_matches(cls, node: dict, node_type: str) -> bool:
        return cls._get_node_type(node) == node_type

    @classmethod
    def _find_nodes_by_type(cls, graph_data: dict, node_type: str) -> list[dict]:
        return [node for node in graph_data.get('nodes', []) if cls._node_type_matches(node, node_type)]

    @classmethod
    def _build_graph_edge_payload(cls,
                                  source_node_id: str,
                                  target_node_id: str,
                                  *,
                                  source_type: str,
                                  target_type: str,
                                  source_handle: str = '',
                                  target_handle: str = '',
                                  edge_id: Optional[str] = None) -> dict:
        return {
            'id': edge_id or cls._next_graph_edge_id(),
            'source': source_node_id,
            'sourceHandle': source_handle or cls._DEFAULT_SOURCE_HANDLE,
            'sourceType': source_type,
            'target': target_node_id,
            'targetHandle': target_handle or cls._DEFAULT_TARGET_HANDLE,
            'targetType': target_type,
        }

    @classmethod
    def _append_graph_edge_if_missing(cls,
                                      graph_data: dict,
                                      *,
                                      source_node: dict,
                                      target_node: dict,
                                      source_handle: str = '',
                                      target_handle: str = '') -> bool:
        resolved_source_handle = source_handle or cls._DEFAULT_SOURCE_HANDLE
        resolved_target_handle = target_handle or cls._DEFAULT_TARGET_HANDLE
        for edge in graph_data.get('edges', []):
            if (
                edge.get('source') == source_node.get('id') and
                edge.get('target') == target_node.get('id') and
                edge.get('sourceHandle') == resolved_source_handle and
                edge.get('targetHandle') == resolved_target_handle
            ):
                return False
        graph_data.setdefault('edges', []).append(
            cls._build_graph_edge_payload(
                source_node.get('id', ''),
                target_node.get('id', ''),
                source_type=cls._get_node_type(source_node),
                target_type=cls._get_node_type(target_node),
                source_handle=resolved_source_handle,
                target_handle=resolved_target_handle,
            )
        )
        return True

    @classmethod
    def _get_root_nodes(cls, graph_data: dict) -> list[dict]:
        incoming_counts = {
            node.get('id', ''): 0
            for node in graph_data.get('nodes', [])
        }
        for edge in graph_data.get('edges', []):
            target_id = edge.get('target')
            if target_id in incoming_counts:
                incoming_counts[target_id] += 1
        return [
            node for node in graph_data.get('nodes', [])
            if cls._get_node_type(node) not in {cls._NOTE_NODE_TYPE, cls._START_NODE_TYPE}
            and incoming_counts.get(node.get('id', ''), 0) == 0
        ]

    @classmethod
    def _get_terminal_nodes(cls, graph_data: dict) -> list[dict]:
        outgoing_counts = {
            node.get('id', ''): 0
            for node in graph_data.get('nodes', [])
        }
        for edge in graph_data.get('edges', []):
            source_id = edge.get('source')
            if source_id in outgoing_counts:
                outgoing_counts[source_id] += 1
        return [
            node for node in graph_data.get('nodes', [])
            if cls._get_node_type(node) not in {cls._NOTE_NODE_TYPE, cls._END_NODE_TYPE}
            and outgoing_counts.get(node.get('id', ''), 0) == 0
        ]

    @classmethod
    def _build_scaffold_node(cls,
                             node_type: str,
                             *,
                             node_id: Optional[str] = None,
                             position_x: float = 0,
                             position_y: float = 0) -> dict:
        resolved_node_id = node_id or cls._next_graph_node_id(node_type)
        node_payload = create_graph_node_payload(
            node_type,
            node_id=resolved_node_id,
            position_x=position_x,
            position_y=position_y,
        )
        if node_payload is None:
            raise NotFoundError(msg=f'Workflow node template not found: {node_type}')
        return node_payload

    @classmethod
    def _normalize_editor_node_types(cls, graph_data: dict) -> dict:
        return normalize_workflow_editor_graph(graph_data, in_place=True)

    @classmethod
    def _ensure_create_graph_scaffold(cls, graph_data: dict) -> dict:
        if not isinstance(graph_data, dict):
            return graph_data
        nodes = graph_data.get('nodes')
        edges = graph_data.get('edges')
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return graph_data

        updated_graph = copy.deepcopy(graph_data)
        cls._normalize_editor_node_types(updated_graph)
        start_nodes = cls._find_nodes_by_type(updated_graph, cls._START_NODE_TYPE)
        end_nodes = cls._find_nodes_by_type(updated_graph, cls._END_NODE_TYPE)

        if not updated_graph['nodes']:
            start_node = cls._build_scaffold_node(cls._START_NODE_TYPE, position_x=0, position_y=0)
            end_node = cls._build_scaffold_node(
                cls._END_NODE_TYPE,
                position_x=cls._DEFAULT_HORIZONTAL_NODE_GAP,
                position_y=0,
            )
            updated_graph['nodes'].extend([start_node, end_node])
            cls._append_graph_edge_if_missing(updated_graph, source_node=start_node, target_node=end_node)
            return updated_graph

        if not start_nodes:
            root_nodes = cls._get_root_nodes(updated_graph)
            root_x_positions = [cls._node_position_value(node, 'x') for node in root_nodes]
            root_y_positions = [cls._node_position_value(node, 'y') for node in root_nodes]
            start_node = cls._build_scaffold_node(
                cls._START_NODE_TYPE,
                position_x=(min(root_x_positions) - cls._DEFAULT_HORIZONTAL_NODE_GAP) if root_x_positions else 0,
                position_y=(sum(root_y_positions) / len(root_y_positions)) if root_y_positions else 0,
            )
            updated_graph['nodes'].append(start_node)
            start_nodes = [start_node]
            for root_node in root_nodes:
                cls._append_graph_edge_if_missing(updated_graph, source_node=start_node, target_node=root_node)

        if not end_nodes:
            terminal_nodes = cls._get_terminal_nodes(updated_graph)
            terminal_x_positions = [cls._node_position_value(node, 'x') for node in terminal_nodes]
            terminal_y_positions = [cls._node_position_value(node, 'y') for node in terminal_nodes]
            end_node = cls._build_scaffold_node(
                cls._END_NODE_TYPE,
                position_x=(max(terminal_x_positions) + cls._DEFAULT_HORIZONTAL_NODE_GAP) if terminal_x_positions else cls._DEFAULT_HORIZONTAL_NODE_GAP,
                position_y=(sum(terminal_y_positions) / len(terminal_y_positions)) if terminal_y_positions else 0,
            )
            updated_graph['nodes'].append(end_node)
            end_nodes = [end_node]
            if terminal_nodes:
                for terminal_node in terminal_nodes:
                    terminal_type = cls._get_node_type(terminal_node)
                    if terminal_type == cls._CONDITION_NODE_TYPE:
                        for condition_case in cls._get_condition_cases(terminal_node):
                            cls._append_graph_edge_if_missing(
                                updated_graph,
                                source_node=terminal_node,
                                target_node=end_node,
                                source_handle=condition_case['id'],
                            )
                        cls._append_graph_edge_if_missing(
                            updated_graph,
                            source_node=terminal_node,
                            target_node=end_node,
                            source_handle=cls._CONDITION_FALLBACK_HANDLE,
                        )
                    else:
                        cls._append_graph_edge_if_missing(updated_graph, source_node=terminal_node, target_node=end_node)

        return updated_graph

    @classmethod
    def _apply_node_initial_params(cls, node_payload: dict, initial_params: Optional[dict]) -> dict:
        if not initial_params:
            return node_payload
        updated_node = copy.deepcopy(node_payload)
        cls._patch_node_fields(updated_node, initial_params)
        return updated_node

    @classmethod
    def _patch_node_fields(cls, node: dict, updates: dict):
        if not isinstance(updates, dict) or not updates:
            cls._raise_workflow_error('Workflow node updates must be a non-empty JSON object')
        fields = cls._get_node_param_fields(node)
        missing_keys = []
        for key, value in updates.items():
            field_meta = fields.get(key)
            if field_meta is None:
                missing_keys.append(key)
                continue
            _group_name, field = field_meta
            field['value'] = cls._coerce_param_value(field, value)
        if missing_keys:
            available = ', '.join(fields.keys())
            raise NotFoundError(msg=f'Node params not found: {missing_keys}. Available params: {available}')

    @classmethod
    def _add_node_to_graph(cls,
                           graph_data: dict,
                           node_type: str,
                           *,
                           name: str = '',
                           position_x: float = 0,
                           position_y: float = 0,
                           node_id: Optional[str] = None,
                           initial_params: Optional[dict] = None) -> tuple[dict, str]:
        updated_graph = copy.deepcopy(graph_data)
        resolved_node_id = node_id or cls._next_graph_node_id(node_type)
        if any(node.get('id') == resolved_node_id for node in updated_graph.get('nodes', [])):
            cls._raise_workflow_error(f'Duplicate node id: {resolved_node_id}')

        node_payload = create_graph_node_payload(
            node_type,
            node_id=resolved_node_id,
            name=name,
            position_x=position_x,
            position_y=position_y,
        )
        if node_payload is None:
            raise NotFoundError(msg=f'Workflow node template not found: {node_type}')
        node_payload = cls._apply_node_initial_params(node_payload, initial_params)
        updated_graph.setdefault('nodes', []).append(node_payload)
        return updated_graph, resolved_node_id

    @classmethod
    def _remove_node_from_graph(cls, graph_data: dict, node_id: str, *, cascade: bool = True) -> dict:
        updated_graph = copy.deepcopy(graph_data)
        node_index = cls._find_node_index(updated_graph, node_id)
        related_edges = [
            edge for edge in updated_graph.get('edges', [])
            if edge.get('source') == node_id or edge.get('target') == node_id
        ]
        if related_edges and not cascade:
            cls._raise_workflow_error(f'Node {node_id} still has connected edges')
        updated_graph['nodes'].pop(node_index)
        if related_edges:
            updated_graph['edges'] = [
                edge for edge in updated_graph.get('edges', [])
                if edge.get('source') != node_id and edge.get('target') != node_id
            ]
        return updated_graph

    @classmethod
    def _connect_nodes_in_graph(cls,
                                graph_data: dict,
                                *,
                                source_node_id: str,
                                target_node_id: str,
                                source_handle: str,
                                target_handle: str,
                                edge_id: Optional[str] = None) -> tuple[dict, str]:
        updated_graph = copy.deepcopy(graph_data)
        source_node = cls._find_node(updated_graph, source_node_id)
        target_node = cls._find_node(updated_graph, target_node_id)
        if source_node_id == target_node_id:
            cls._raise_workflow_error('Workflow edge cannot connect a node to itself')
        if not source_handle:
            cls._raise_workflow_error('Workflow edge source_handle is required')
        if not target_handle:
            cls._raise_workflow_error('Workflow edge target_handle is required')

        for edge in updated_graph.get('edges', []):
            if (
                edge.get('source') == source_node_id and
                edge.get('target') == target_node_id and
                edge.get('sourceHandle') == source_handle and
                edge.get('targetHandle') == target_handle
            ):
                cls._raise_workflow_error('Duplicate workflow edge')

        resolved_edge_id = edge_id or cls._next_graph_edge_id()
        updated_graph.setdefault('edges', []).append({
            'id': resolved_edge_id,
            'source': source_node_id,
            'sourceHandle': source_handle,
            'sourceType': source_node.get('data', {}).get('type') or source_node.get('type', ''),
            'target': target_node_id,
            'targetHandle': target_handle,
            'targetType': target_node.get('data', {}).get('type') or target_node.get('type', ''),
        })
        return updated_graph, resolved_edge_id

    @classmethod
    def _disconnect_edge_from_graph(cls,
                                    graph_data: dict,
                                    *,
                                    edge_id: Optional[str] = None,
                                    source_node_id: str = '',
                                    target_node_id: str = '',
                                    source_handle: str = '',
                                    target_handle: str = '') -> tuple[dict, str]:
        updated_graph = copy.deepcopy(graph_data)
        removed_edge_id = edge_id or ''
        if edge_id:
            edge_index = cls._find_edge_index(updated_graph, edge_id)
            updated_graph['edges'].pop(edge_index)
            return updated_graph, edge_id

        matches = []
        for index, edge in enumerate(updated_graph.get('edges', [])):
            if source_node_id and edge.get('source') != source_node_id:
                continue
            if target_node_id and edge.get('target') != target_node_id:
                continue
            if source_handle and edge.get('sourceHandle') != source_handle:
                continue
            if target_handle and edge.get('targetHandle') != target_handle:
                continue
            matches.append((index, edge))

        if not matches:
            raise NotFoundError(msg='Workflow edge not found')
        if len(matches) > 1:
            cls._raise_workflow_error('Workflow edge selector is ambiguous')

        edge_index, edge = matches[0]
        removed_edge_id = edge.get('id', '')
        updated_graph['edges'].pop(edge_index)
        return updated_graph, removed_edge_id

    @classmethod
    def _patch_node_template(cls, graph_data: dict, node_id: str, updates: dict) -> dict:
        updated_graph = copy.deepcopy(graph_data)
        node = cls._find_node(updated_graph, node_id)
        cls._patch_node_fields(node, updates)
        return updated_graph

    @classmethod
    def _normalize_condition_cases(cls, condition_cases: list[dict]) -> list[dict]:
        if not isinstance(condition_cases, list):
            cls._raise_workflow_error('Condition node cases must be a list')
        normalized_cases = []
        seen_case_ids: set[str] = set()
        for index, raw_case in enumerate(condition_cases):
            if not isinstance(raw_case, dict):
                cls._raise_workflow_error(f'Condition case at index {index} must be an object')
            try:
                normalized_case = ConditionCases(**raw_case).model_dump()
            except Exception as exc:
                cls._raise_workflow_error(f'Invalid condition case at index {index}: {exc}')
            for condition in normalized_case.get('conditions') or []:
                right_value_type = condition.get('right_value_type')
                if right_value_type != 'ref':
                    condition['right_value_type'] = 'input'
            case_id = normalized_case['id']
            if case_id in seen_case_ids:
                cls._raise_workflow_error(f'Duplicate condition case id: {case_id}')
            seen_case_ids.add(case_id)
            normalized_cases.append(normalized_case)
        return normalized_cases

    @classmethod
    def _get_condition_cases(cls, node: dict) -> list[dict]:
        condition_field = cls._get_node_param_field(node, cls._CONDITION_PARAM_KEY)
        raw_value = condition_field.get('value') or []
        return cls._normalize_condition_cases(raw_value)

    @classmethod
    def _update_condition_cases_in_graph(cls, graph_data: dict, node_id: str, condition_cases: list[dict]) -> dict:
        updated_graph = copy.deepcopy(graph_data)
        node = cls._find_node(updated_graph, node_id)
        cls._assert_condition_node(node, node_id)
        condition_field = cls._get_node_param_field(node, cls._CONDITION_PARAM_KEY)
        condition_field['value'] = cls._normalize_condition_cases(condition_cases)
        return updated_graph

    @classmethod
    def _get_condition_outgoing_edges(cls, graph_data: dict, node_id: str) -> dict[str, list[dict[str, str]]]:
        routes: dict[str, list[dict[str, str]]] = {}
        for edge in graph_data.get('edges', []):
            if edge.get('source') != node_id:
                continue
            source_handle = edge.get('sourceHandle') or ''
            routes.setdefault(source_handle, []).append({
                'edge_id': edge.get('id', ''),
                'target_node_id': edge.get('target', ''),
                'target_handle': edge.get('targetHandle', ''),
            })
        return routes

    @classmethod
    async def _get_workflow_with_write_access(cls, login_user: UserPayload, flow_id: str) -> Flow:
        flow = await FlowDao.aget_flow_by_id(flow_id)
        if not flow:
            raise NotFoundError()
        if flow.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError()
        if not await login_user.async_access_check(flow.user_id, flow_id, AccessType.WORKFLOW_WRITE):
            raise UnAuthorizedError()
        return flow

    @classmethod
    async def _get_workflow_version(cls, flow_id: str, version_id: int) -> FlowVersion:
        version = await FlowVersionDao.aget_version_by_id(version_id)
        if not version or version.flow_id != flow_id:
            raise NotFoundVersionError()
        return version

    @classmethod
    def _create_workflow_draft_sync(cls,
                                    login_user: UserPayload,
                                    name: str,
                                    graph_data: dict,
                                    description: Optional[str] = None,
                                    guide_word: Optional[str] = None) -> tuple[Flow, FlowVersion]:
        cls._assert_workflow_name_available(login_user, name)
        graph_data = cls._ensure_create_graph_scaffold(graph_data)
        cls._validate_draft_graph(login_user, graph_data, flow_name=name)

        db_flow = Flow(
            name=name,
            user_id=login_user.user_id,
            description=description,
            data=graph_data,
            guide_word=guide_word,
            flow_type=FlowType.WORKFLOW.value,
            status=FlowStatus.OFFLINE.value,
        )
        db_flow = FlowDao.create_flow(db_flow, FlowType.WORKFLOW.value)
        current_version = FlowVersionDao.get_version_by_flow(db_flow.id)
        current_version.data = cls._mark_graph_as_draft(current_version.data)
        current_version = FlowVersionDao.update_version(current_version)
        FlowService.create_flow_hook(
            cls._internal_request(),
            login_user,
            db_flow,
            current_version.id,
            FlowType.WORKFLOW.value,
        )
        return db_flow, current_version

    @classmethod
    async def create_workflow_draft(cls,
                                    login_user: UserPayload,
                                    name: str,
                                    graph_data: dict,
                                    description: Optional[str] = None,
                                    guide_word: Optional[str] = None) -> tuple[Flow, FlowVersion]:
        return await asyncio.to_thread(
            cls._create_workflow_draft_sync,
            login_user,
            name,
            graph_data,
            description,
            guide_word,
        )

    @classmethod
    async def update_workflow_draft(cls,
                                    login_user: UserPayload,
                                    flow_id: str,
                                    graph_data: dict,
                                    name: Optional[str] = None,
                                    description: Optional[str] = None,
                                    guide_word: Optional[str] = None,
                                    expected_revision: Optional[int] = None) -> tuple[Flow, FlowVersion]:
        flow, editable_version = await cls._get_editable_version(login_user, flow_id)
        cls._assert_expected_revision(editable_version.data, expected_revision)
        has_flow_updates = any(value is not None for value in (name, description, guide_word))
        if has_flow_updates and flow.status == FlowStatus.ONLINE.value:
            raise WorkFlowOnlineEditError()
        if name is not None and name != flow.name:
            cls._assert_workflow_name_available(login_user, name, exclude_flow_id=flow.id)

        graph_data = cls._normalize_editor_node_types(copy.deepcopy(graph_data))
        if has_flow_updates:
            if name is not None:
                flow.name = name
            if description is not None:
                flow.description = description
            if guide_word is not None:
                flow.guide_word = guide_word
            flow = await FlowDao.aupdate_flow(flow)
            await FlowService.update_flow_hook(cls._internal_request(), login_user, flow)

        cls._validate_draft_graph(login_user, graph_data, flow_name=flow.name, flow_id=flow.id)
        editable_version.data = cls._mark_graph_as_draft(graph_data, in_place=True)
        editable_version = FlowVersionDao.update_version(editable_version)
        return flow, editable_version

    @classmethod
    async def list_workflow_nodes(cls,
                                  login_user: UserPayload,
                                  flow_id: str,
                                  version_id: Optional[int] = None) -> dict:
        _, version = await cls._get_editable_version(login_user, flow_id, version_id)
        nodes = []
        for node in version.data.get('nodes', []):
            node_type = node.get('data', {}).get('type') or node.get('type', '')
            try:
                param_keys = cls._get_editable_node_param_keys(node)
            except NotFoundError:
                param_keys = []
            nodes.append({
                'id': node.get('id', ''),
                'type': node_type,
                'name': node.get('data', {}).get('name') or node.get('data', {}).get('node', {}).get('display_name', ''),
                'param_keys': param_keys,
            })
        return {
            'flow_id': flow_id,
            'version_id': version.id,
            'draft_revision': cls.get_graph_revision(version.data),
            'nodes': nodes,
        }

    @classmethod
    async def get_workflow_node_params(cls,
                                       login_user: UserPayload,
                                       flow_id: str,
                                       node_id: str,
                                       version_id: Optional[int] = None) -> dict:
        _, version = await cls._get_editable_version(login_user, flow_id, version_id)
        node = cls._find_node(version.data, node_id)
        params = {}
        for key, (group_name, value) in cls._get_node_param_fields(node).items():
            params[key] = cls._build_param_payload(group_name, value)
        return {
            'flow_id': flow_id,
            'version_id': version.id,
            'draft_revision': cls.get_graph_revision(version.data),
            'node_id': node_id,
            'node_type': node.get('data', {}).get('type') or node.get('type', ''),
            'node_name': node.get('data', {}).get('name') or node.get('data', {}).get('node', {}).get('display_name', ''),
            'params': params,
        }

    @classmethod
    async def get_condition_node_config(cls,
                                        login_user: UserPayload,
                                        flow_id: str,
                                        node_id: str,
                                        version_id: Optional[int] = None) -> dict:
        _, version = await cls._get_editable_version(login_user, flow_id, version_id)
        node = cls._find_node(version.data, node_id)
        cls._assert_condition_node(node, node_id)
        condition_cases = cls._get_condition_cases(node)
        route_handles = [one['id'] for one in condition_cases]
        if cls._CONDITION_FALLBACK_HANDLE not in route_handles:
            route_handles.append(cls._CONDITION_FALLBACK_HANDLE)
        return {
            'flow_id': flow_id,
            'version_id': version.id,
            'draft_revision': cls.get_graph_revision(version.data),
            'node_id': node_id,
            'node_name': node.get('data', {}).get('name') or node.get('data', {}).get('node', {}).get('display_name', ''),
            'condition_cases': condition_cases,
            'route_handles': route_handles,
            'outgoing_edges': cls._get_condition_outgoing_edges(version.data, node_id),
        }

    @classmethod
    async def update_workflow_node_params(cls,
                                          login_user: UserPayload,
                                          flow_id: str,
                                          node_id: str,
                                          updates: dict,
                                          version_id: Optional[int] = None,
                                          expected_revision: Optional[int] = None) -> tuple[Flow, FlowVersion]:
        flow, editable_version = await cls._get_editable_version(login_user, flow_id, version_id)
        cls._assert_expected_revision(editable_version.data, expected_revision)
        graph_data = cls._patch_node_template(editable_version.data, node_id, updates)
        cls._validate_draft_graph(login_user, graph_data, flow_name=flow.name, flow_id=flow.id)
        editable_version.data = cls._mark_graph_as_draft(graph_data, in_place=True)
        editable_version = FlowVersionDao.update_version(editable_version)
        return flow, editable_version

    @classmethod
    async def update_condition_node(cls,
                                    login_user: UserPayload,
                                    flow_id: str,
                                    node_id: str,
                                    condition_cases: list[dict],
                                    version_id: Optional[int] = None,
                                    expected_revision: Optional[int] = None) -> tuple[Flow, FlowVersion]:
        flow, editable_version = await cls._get_editable_version(login_user, flow_id, version_id)
        cls._assert_expected_revision(editable_version.data, expected_revision)
        graph_data = cls._update_condition_cases_in_graph(editable_version.data, node_id, condition_cases)
        cls._validate_draft_graph(login_user, graph_data, flow_name=flow.name, flow_id=flow.id)
        editable_version.data = cls._mark_graph_as_draft(graph_data, in_place=True)
        editable_version = FlowVersionDao.update_version(editable_version)
        return flow, editable_version

    @classmethod
    async def add_workflow_node(cls,
                                login_user: UserPayload,
                                flow_id: str,
                                node_type: str,
                                name: str = '',
                                position_x: float = 0,
                                position_y: float = 0,
                                initial_params: Optional[dict] = None,
                                version_id: Optional[int] = None,
                                expected_revision: Optional[int] = None) -> tuple[Flow, FlowVersion, str]:
        flow, editable_version = await cls._get_editable_version(login_user, flow_id, version_id)
        cls._assert_expected_revision(editable_version.data, expected_revision)
        graph_data, node_id = cls._add_node_to_graph(
            editable_version.data,
            node_type,
            name=name,
            position_x=position_x,
            position_y=position_y,
            initial_params=initial_params,
        )
        cls._validate_draft_graph(login_user, graph_data, flow_name=flow.name, flow_id=flow.id)
        editable_version.data = cls._mark_graph_as_draft(graph_data, in_place=True)
        editable_version = FlowVersionDao.update_version(editable_version)
        return flow, editable_version, node_id

    @classmethod
    async def remove_workflow_node(cls,
                                   login_user: UserPayload,
                                   flow_id: str,
                                   node_id: str,
                                   *,
                                   cascade: bool = True,
                                   version_id: Optional[int] = None,
                                   expected_revision: Optional[int] = None) -> tuple[Flow, FlowVersion]:
        flow, editable_version = await cls._get_editable_version(login_user, flow_id, version_id)
        cls._assert_expected_revision(editable_version.data, expected_revision)
        graph_data = cls._remove_node_from_graph(editable_version.data, node_id, cascade=cascade)
        cls._validate_draft_graph(login_user, graph_data, flow_name=flow.name, flow_id=flow.id)
        editable_version.data = cls._mark_graph_as_draft(graph_data, in_place=True)
        editable_version = FlowVersionDao.update_version(editable_version)
        return flow, editable_version

    @classmethod
    async def connect_workflow_nodes(cls,
                                     login_user: UserPayload,
                                     flow_id: str,
                                     source_node_id: str,
                                     target_node_id: str,
                                     source_handle: str,
                                     target_handle: str,
                                     *,
                                     version_id: Optional[int] = None,
                                     expected_revision: Optional[int] = None) -> tuple[Flow, FlowVersion, str]:
        flow, editable_version = await cls._get_editable_version(login_user, flow_id, version_id)
        cls._assert_expected_revision(editable_version.data, expected_revision)
        graph_data, edge_id = cls._connect_nodes_in_graph(
            editable_version.data,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            source_handle=source_handle,
            target_handle=target_handle,
        )
        cls._validate_draft_graph(login_user, graph_data, flow_name=flow.name, flow_id=flow.id)
        editable_version.data = cls._mark_graph_as_draft(graph_data, in_place=True)
        editable_version = FlowVersionDao.update_version(editable_version)
        return flow, editable_version, edge_id

    @classmethod
    async def disconnect_workflow_edge(cls,
                                       login_user: UserPayload,
                                       flow_id: str,
                                       *,
                                       edge_id: str = '',
                                       source_node_id: str = '',
                                       target_node_id: str = '',
                                       source_handle: str = '',
                                       target_handle: str = '',
                                       version_id: Optional[int] = None,
                                       expected_revision: Optional[int] = None) -> tuple[Flow, FlowVersion, str]:
        flow, editable_version = await cls._get_editable_version(login_user, flow_id, version_id)
        cls._assert_expected_revision(editable_version.data, expected_revision)
        graph_data, removed_edge_id = cls._disconnect_edge_from_graph(
            editable_version.data,
            edge_id=edge_id or None,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            source_handle=source_handle,
            target_handle=target_handle,
        )
        cls._validate_draft_graph(login_user, graph_data, flow_name=flow.name, flow_id=flow.id)
        editable_version.data = cls._mark_graph_as_draft(graph_data, in_place=True)
        editable_version = FlowVersionDao.update_version(editable_version)
        return flow, editable_version, removed_edge_id

    @classmethod
    async def validate_workflow(cls, login_user: UserPayload, flow_id: str, version_id: int) -> tuple[Flow, FlowVersion]:
        flow = await cls._get_workflow_with_write_access(login_user, flow_id)
        version = await cls._get_workflow_version(flow_id, version_id)
        try:
            cls._validate_draft_graph(login_user, version.data, flow_name=flow.name, flow_id=flow_id)
        except Exception as exc:
            if isinstance(exc, WorkFlowInitError):
                raise exc
            raise WorkFlowInitError(exception=exc, msg=str(exc))
        return flow, version

    @classmethod
    async def publish_workflow(cls, login_user: UserPayload, flow_id: str, version_id: int) -> tuple[Flow, FlowVersion]:
        flow, version = await cls.validate_workflow(login_user, flow_id, version_id)
        draft_data = copy.deepcopy(version.data)
        version.data = cls._clear_graph_draft_marker(version.data)
        version = FlowVersionDao.update_version(version)
        try:
            await WorkFlowService.update_flow_status(login_user, flow_id, version_id, FlowStatus.ONLINE.value)
        except Exception:
            version.data = draft_data
            FlowVersionDao.update_version(version)
            raise
        flow = await FlowDao.aget_flow_by_id(flow_id)
        version = await cls._get_workflow_version(flow_id, version_id)
        return flow, version
