from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from bisheng.common.errcode.flow import WorkFlowInitError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.mcp_server.workflow import create_workflow_mcp_server
from bisheng.workflow.authoring import WorkflowManifest


def get_tool(name: str):
    mcp = create_workflow_mcp_server()
    return mcp._tool_manager._tools[name].fn


class TestWorkflowMcpTools(IsolatedAsyncioTestCase):
    async def test_ping_hides_scopes_but_whoami_returns_them(self):
        login_user = SimpleNamespace(user_id=7, user_name='admin')
        ping = get_tool('ping')
        whoami = get_tool('whoami')

        with patch('bisheng.mcp_server.workflow.get_login_user_from_mcp_token', AsyncMock(return_value=login_user)), \
                patch('bisheng.mcp_server.workflow.get_current_token_scopes',
                      return_value=('workflow.read', 'workflow.write')):
            ping_result = await ping()
            whoami_result = await whoami()

        self.assertTrue(ping_result.ok)
        self.assertEqual(ping_result.scopes, [])
        self.assertEqual(whoami_result.scopes, ['workflow.read', 'workflow.write'])

    async def test_list_workflows_enforces_read_scope_and_wraps_result(self):
        login_user = SimpleNamespace(user_id=7, user_name='admin')
        list_workflows = get_tool('list_workflows')
        workflow = WorkflowManifest(flow_id='flow-1', name='demo')

        with patch('bisheng.mcp_server.workflow.get_login_user_from_mcp_token', AsyncMock(return_value=login_user)), \
                patch('bisheng.mcp_server.workflow.require_mcp_scopes') as require_scopes, \
                patch('bisheng.mcp_server.workflow.WorkflowAuthoringService.list_workflows',
                      AsyncMock(return_value=[workflow])):
            result = await list_workflows()

        require_scopes.assert_called_once_with('workflow.read')
        self.assertTrue(result.ok)
        self.assertEqual(result.workflows, [workflow])

    async def test_add_node_wraps_service_error(self):
        login_user = SimpleNamespace(user_id=7, user_name='admin')
        add_node = get_tool('add_node')

        with patch('bisheng.mcp_server.workflow.get_login_user_from_mcp_token', AsyncMock(return_value=login_user)), \
                patch('bisheng.mcp_server.workflow.require_mcp_scopes'), \
                patch('bisheng.mcp_server.workflow.ExternalWorkflowService.add_workflow_node',
                      AsyncMock(side_effect=NotFoundError(msg='missing node template'))):
            result = await add_node(flow_id='flow-1', node_type='missing')

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, 404)
        self.assertEqual(result.message, 'missing node template')

    async def test_list_workflows_wraps_scope_error(self):
        login_user = SimpleNamespace(user_id=7, user_name='admin')
        list_workflows = get_tool('list_workflows')

        with patch('bisheng.mcp_server.workflow.get_login_user_from_mcp_token', AsyncMock(return_value=login_user)), \
                patch('bisheng.mcp_server.workflow.require_mcp_scopes',
                      side_effect=UnAuthorizedError(msg='forbidden')):
            result = await list_workflows()

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, 403)
        self.assertEqual(result.message, 'forbidden')

    async def test_get_condition_node_wraps_service_payload(self):
        login_user = SimpleNamespace(user_id=7, user_name='admin')
        get_condition_node = get_tool('get_condition_node')
        payload = {
            'flow_id': 'flow-1',
            'version_id': 11,
            'draft_revision': 2,
            'node_id': 'condition-1',
            'node_name': 'Condition Node',
            'condition_cases': [{'id': 'case_a', 'operator': 'and', 'conditions': [], 'variable_key_value': {}}],
            'route_handles': ['case_a', 'right_handle'],
            'outgoing_edges': {'case_a': [{'edge_id': 'edge-1', 'target_node_id': 'node-2', 'target_handle': 'input'}]},
        }

        with patch('bisheng.mcp_server.workflow.get_login_user_from_mcp_token', AsyncMock(return_value=login_user)), \
                patch('bisheng.mcp_server.workflow.require_mcp_scopes'), \
                patch('bisheng.mcp_server.workflow.ExternalWorkflowService.get_condition_node_config',
                      AsyncMock(return_value=payload)):
            result = await get_condition_node(flow_id='flow-1', node_id='condition-1')

        self.assertTrue(result.ok)
        self.assertEqual(result.node_id, 'condition-1')
        self.assertEqual(result.route_handles, ['case_a', 'right_handle'])

    async def test_validate_workflow_returns_structured_diagnostics_on_error(self):
        login_user = SimpleNamespace(user_id=7, user_name='admin')
        validate_workflow = get_tool('validate_workflow')

        with patch('bisheng.mcp_server.workflow.get_login_user_from_mcp_token', AsyncMock(return_value=login_user)), \
                patch('bisheng.mcp_server.workflow.require_mcp_scopes'), \
                patch('bisheng.mcp_server.workflow.ExternalWorkflowService.validate_workflow',
                      AsyncMock(side_effect=WorkFlowInitError(msg='Param temperature must be within scope [0, 1]'))):
            result = await validate_workflow(flow_id='flow-1', version_id=11)

        self.assertFalse(result.ok)
        self.assertFalse(result.valid)
        self.assertEqual(result.error_code, 10526)
        self.assertEqual(result.errors, ['Param temperature must be within scope [0, 1]'])
        self.assertEqual(result.diagnostics[0].field_path, 'temperature')

    async def test_ping_returns_connection_error_when_authentication_fails(self):
        ping = get_tool('ping')

        with patch('bisheng.mcp_server.workflow.get_login_user_from_mcp_token',
                   AsyncMock(side_effect=UnAuthorizedError(msg='missing token'))):
            result = await ping()

        self.assertFalse(result.ok)
        self.assertFalse(result.authenticated)
        self.assertEqual(result.error_code, 403)
        self.assertEqual(result.message, 'missing token')
