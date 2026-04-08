from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from bisheng.api.services.workflow_authoring import WorkflowAuthoringService
from bisheng.common.errcode.flow import WorkFlowInitError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models.flow import FlowStatus
from bisheng.workflow.authoring.registry import get_node_template_descriptor, list_node_type_descriptors


def make_graph():
    return {
        'nodes': [{
            'id': 'node-1',
            'data': {
                'id': 'node-1',
                'type': 'llm',
                'name': 'LLM Node',
                'tab': {
                    'value': 'single',
                    'options': [{'label': 'Single', 'key': 'single'}, {'label': 'Batch', 'key': 'batch'}],
                },
                'group_params': [{
                    'name': 'model',
                    'params': [{
                        'key': 'temperature',
                        'type': 'slide',
                        'required': True,
                        'scope': [0, 1],
                        'placeholder': '0.0 ~ 1.0',
                        'refresh': True,
                        'options': [{'key': 0.3, 'value': 0.3}, {'key': 0.7, 'value': 0.7}],
                        'value': 0.7,
                    }, {
                        'key': 'system_prompt',
                        'type': 'var_textarea',
                        'value': 'hello',
                    }],
                }],
            },
        }],
        'edges': [{
            'id': 'edge-1',
            'source': 'node-1',
            'sourceHandle': 'output',
            'target': 'node-2',
            'targetHandle': 'input',
        }],
    }


class TestWorkflowAuthoringRegistry(TestCase):
    def test_list_node_types_includes_dynamic_tool(self):
        node_types = {item.type: item for item in list_node_type_descriptors()}

        self.assertIn('llm', node_types)
        self.assertIn('condition', node_types)
        self.assertIn('tool', node_types)
        self.assertTrue(node_types['tool'].dynamic_template)

    def test_get_node_template_returns_normalized_llm_template(self):
        template = get_node_template_descriptor('llm')

        self.assertIsNotNone(template)
        self.assertEqual(template.node_type, 'llm')
        self.assertEqual(template.display_name, 'LLM')
        self.assertEqual(template.tab.value, 'single')
        self.assertIn('model_id', template.params)
        self.assertIn('temperature', template.params)
        self.assertIn('system_prompt', template.params)


class TestWorkflowAuthoringService(IsolatedAsyncioTestCase):
    async def test_list_workflows_filters_by_write_access(self):
        flows = [
            SimpleNamespace(id='flow-1', user_id=10, name='one', description='', status=FlowStatus.OFFLINE.value),
            SimpleNamespace(id='flow-2', user_id=11, name='two', description='', status=FlowStatus.ONLINE.value),
        ]
        login_user = SimpleNamespace(
            user_id=1,
            async_access_check=AsyncMock(side_effect=[True, False]),
        )

        with patch.object(WorkflowAuthoringService, '_list_candidate_workflows', AsyncMock(return_value=flows)), \
                patch.object(WorkflowAuthoringService, '_build_manifest', side_effect=lambda flow: flow.id):
            result = await WorkflowAuthoringService.list_workflows(login_user)

        self.assertEqual(result, ['flow-1'])

    async def test_get_workflow_graph_returns_normalized_graph(self):
        version = SimpleNamespace(id=11, data=make_graph())
        login_user = SimpleNamespace(user_id=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return SimpleNamespace(id=flow_id, name='demo', status=FlowStatus.OFFLINE.value), version

        with patch('bisheng.api.services.workflow_authoring.ExternalWorkflowService._get_editable_version',
                   side_effect=fake_get_editable_version):
            graph = await WorkflowAuthoringService.get_workflow_graph(login_user, 'flow-1')

        self.assertEqual(graph.flow_id, 'flow-1')
        self.assertEqual(graph.version_id, 11)
        self.assertEqual(len(graph.nodes), 1)
        self.assertEqual(graph.nodes[0].id, 'node-1')
        self.assertEqual(graph.nodes[0].type, 'llm')
        self.assertEqual(graph.nodes[0].tab.value, 'single')
        self.assertIn('temperature', graph.nodes[0].params)
        self.assertEqual(graph.edges[0]['source'], 'node-1')

    async def test_get_workflow_versions_marks_editable_draft(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        versions = [
            SimpleNamespace(id=11, name='v1', description='base', is_current=1, create_time=None, update_time=None),
            SimpleNamespace(id=12, name='draft', description='draft', is_current=0, create_time=None, update_time=None),
        ]
        detailed_versions = {
            11: SimpleNamespace(id=11, data=make_graph(), original_version_id=None),
            12: SimpleNamespace(
                id=12,
                data={'nodes': make_graph()['nodes'], 'edges': make_graph()['edges'],
                      '_external_workflow_meta': {'draft': True, 'revision': 3}},
                original_version_id=11,
            ),
        }

        with patch('bisheng.api.services.workflow_authoring.ExternalWorkflowService._get_workflow_with_write_access',
                   AsyncMock(return_value=flow)), \
                patch.object(WorkflowAuthoringService, '_editable_version_without_side_effect',
                             return_value=(detailed_versions[11], detailed_versions[12])), \
                patch('bisheng.api.services.workflow_authoring.FlowVersionDao.get_list_by_flow',
                      return_value=versions), \
                patch('bisheng.api.services.workflow_authoring.FlowVersionDao.get_version_by_id',
                      side_effect=lambda version_id: detailed_versions[version_id]):
            result = await WorkflowAuthoringService.get_workflow_versions(SimpleNamespace(user_id=1), 'flow-1')

        self.assertEqual(len(result), 2)
        self.assertTrue(result[1].is_editable)
        self.assertTrue(result[1].is_external_draft)
        self.assertEqual(result[1].draft_revision, 3)
        self.assertEqual(result[1].original_version_id, 11)

    def test_get_node_template_raises_for_unknown_type(self):
        with self.assertRaises(NotFoundError):
            WorkflowAuthoringService.get_node_template('missing')

    def test_diagnostics_from_exception_extracts_field_path(self):
        diagnostics = WorkflowAuthoringService.diagnostics_from_exception(
            WorkFlowInitError(msg='Param temperature must be within scope [0, 1]')
        )

        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].severity.value, 'error')
        self.assertEqual(diagnostics[0].field_path, 'temperature')
        self.assertEqual(diagnostics[0].suggested_fix, 'Review the parameter value and node template requirements.')
