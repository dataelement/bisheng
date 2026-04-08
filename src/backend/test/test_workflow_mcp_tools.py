from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

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
