import json
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from bisheng.common.errcode.flow import WorkFlowInitError
from bisheng.mcp_server.auth import McpAuthorizationMiddleware
from bisheng.mcp_server.workflow import create_workflow_mcp_server
from bisheng.workflow.authoring import WorkflowManifest


class TestWorkflowMcpE2E(IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = create_workflow_mcp_server()
        self.app = McpAuthorizationMiddleware(self.server.streamable_http_app())
        self._stack = AsyncExitStack()

    async def asyncTearDown(self):
        await self._stack.aclose()

    def _httpx_client_factory(self, headers=None, timeout=None, auth=None):
        @asynccontextmanager
        async def _factory():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url='http://testserver',
                headers=headers,
                timeout=timeout,
                auth=auth,
                follow_redirects=True,
            ) as client:
                yield client

        return _factory()

    @staticmethod
    def _decode_tool_result(result) -> dict:
        if not result.content:
            raise AssertionError('Tool result did not contain any MCP content payload')
        return json.loads(result.content[0].text)

    async def _open_session(self, scopes=('workflow.read', 'workflow.write')):
        login_user = SimpleNamespace(user_id=7, user_name='admin')
        auth_patch = patch(
            'bisheng.mcp_server.auth._validate_mcp_access_token',
            AsyncMock(return_value=(login_user, scopes)),
        )
        self.addCleanup(auth_patch.stop)
        auth_patch.start()
        await self._stack.enter_async_context(self.server.session_manager.run())
        streams = await self._stack.enter_async_context(
            streamablehttp_client(
                'http://testserver/',
                headers={'Authorization': 'Bearer test-token'},
                httpx_client_factory=self._httpx_client_factory,
            )
        )
        read_stream, write_stream, _ = streams
        session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return session

    async def test_http_rejects_missing_bearer_token(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url='http://testserver',
            follow_redirects=True,
        ) as client:
            response = await client.post(
                '/',
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'initialize',
                    'params': {
                        'protocolVersion': '2025-06-18',
                        'capabilities': {},
                        'clientInfo': {'name': 'pytest', 'version': '1.0.0'},
                    },
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'invalid_request')
        self.assertIn('Missing Bearer token', response.headers['WWW-Authenticate'])

    async def test_streamable_http_lists_expected_tools(self):
        session = await self._open_session()

        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}

        self.assertIn('ping', tool_names)
        self.assertIn('list_workflows', tool_names)
        self.assertIn('add_node', tool_names)
        self.assertIn('update_condition_node', tool_names)

        ping_result = await session.call_tool('ping', {})
        payload = self._decode_tool_result(ping_result)

        self.assertTrue(payload['ok'])
        self.assertTrue(payload['authenticated'])
        self.assertEqual(payload['user_id'], 7)
        self.assertEqual(payload['scopes'], [])

    async def test_streamable_http_list_workflows_returns_json_payload(self):
        session = await self._open_session()

        with patch(
            'bisheng.mcp_server.workflow.WorkflowAuthoringService.list_workflows',
            AsyncMock(return_value=[WorkflowManifest(flow_id='flow-1', name='demo')]),
        ):
            result = await session.call_tool('list_workflows', {})

        payload = self._decode_tool_result(result)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['workflows'][0]['flow_id'], 'flow-1')
        self.assertEqual(payload['workflows'][0]['name'], 'demo')

    async def test_streamable_http_add_node_returns_mutation_payload(self):
        session = await self._open_session(scopes=('workflow.read', 'workflow.write'))
        flow = SimpleNamespace(id='flow-1')
        version = SimpleNamespace(id=11, data={'nodes': [], 'edges': [], '_external_workflow_meta': {'revision': 3}})

        with patch(
            'bisheng.mcp_server.workflow.ExternalWorkflowService.add_workflow_node',
            AsyncMock(return_value=(flow, version, 'llm_1234')),
        ), patch(
            'bisheng.mcp_server.workflow.ExternalWorkflowService.get_graph_revision',
            return_value=3,
        ):
            result = await session.call_tool(
                'add_node',
                {
                    'flow_id': 'flow-1',
                    'node_type': 'llm',
                    'name': 'LLM Node',
                    'position_x': 120,
                    'position_y': 48,
                    'initial_params': {'temperature': 0.3},
                },
            )

        payload = self._decode_tool_result(result)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['flow_id'], 'flow-1')
        self.assertEqual(payload['version_id'], 11)
        self.assertEqual(payload['draft_revision'], 3)
        self.assertEqual(payload['node_id'], 'llm_1234')

    async def test_streamable_http_returns_structured_validation_error_payload(self):
        session = await self._open_session()

        with patch(
            'bisheng.mcp_server.workflow.ExternalWorkflowService.validate_workflow',
            AsyncMock(side_effect=WorkFlowInitError(msg='Param temperature must be within scope [0, 1]')),
        ):
            result = await session.call_tool(
                'validate_workflow',
                {'flow_id': 'flow-1', 'version_id': 11},
            )

        payload = self._decode_tool_result(result)
        self.assertFalse(payload['ok'])
        self.assertFalse(payload['valid'])
        self.assertEqual(payload['error_code'], 10526)
        self.assertEqual(payload['errors'], ['Param temperature must be within scope [0, 1]'])
        self.assertEqual(payload['diagnostics'][0]['field_path'], 'temperature')

    async def test_streamable_http_scope_failure_returns_wrapped_tool_payload(self):
        session = await self._open_session(scopes=('workflow.read',))

        result = await session.call_tool(
            'add_node',
            {
                'flow_id': 'flow-1',
                'node_type': 'llm',
            },
        )

        payload = self._decode_tool_result(result)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['error_code'], 403)
        self.assertIn('workflow.write', payload['message'])
