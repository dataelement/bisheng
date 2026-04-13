from copy import deepcopy
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from bisheng.api.services.flow import FlowService
from bisheng.api.services.external_workflow import ExternalWorkflowService
from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.errcode.flow import WorkFlowInitError, WorkFlowVersionUpdateError, WorkflowNameExistsError
from bisheng.database.models.flow import FlowDao, FlowStatus
from bisheng.database.models.flow_version import FlowVersionDao


def make_graph():
    return {
        'nodes': [{
            'id': 'node-1',
            'data': {
                'id': 'node-1',
                'type': 'llm',
                'name': 'LLM Node',
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
                    }, {
                        'key': 'openai_api_key',
                        'type': 'str',
                        'password': True,
                        'value': 'secret',
                    }, {
                        'key': 'hidden_internal',
                        'type': 'str',
                        'show': False,
                        'value': 'hidden',
                    }],
                }],
            },
        }],
        'edges': [],
    }


def make_condition_graph():
    return {
        'nodes': [{
            'id': 'condition-1',
            'data': {
                'id': 'condition-1',
                'type': 'condition',
                'name': 'Condition Node',
                'group_params': [{
                    'params': [{
                        'key': 'condition',
                        'type': 'condition',
                        'value': [{
                            'id': 'case_a',
                            'operator': 'and',
                            'conditions': [{
                                'id': 'rule_1',
                                'left_var': 'score',
                                'comparison_operation': 'greater_than',
                                'right_value_type': 'const',
                                'right_value': '80',
                                'variable_key_value': {},
                            }],
                            'variable_key_value': {},
                        }],
                    }],
                }],
            },
        }, {
            'id': 'node-2',
            'data': {
                'id': 'node-2',
                'type': 'output',
                'name': 'Output Node',
                'group_params': [],
            },
        }],
        'edges': [{
            'id': 'edge-1',
            'source': 'condition-1',
            'sourceHandle': 'case_a',
            'target': 'node-2',
            'targetHandle': 'input',
        }, {
            'id': 'edge-2',
            'source': 'condition-1',
            'sourceHandle': 'right_handle',
            'target': 'node-2',
            'targetHandle': 'input',
        }],
    }


def make_large_graph():
    nodes = [
        {
            'id': 'input-1',
            'data': {
                'id': 'input-1',
                'type': 'input',
                'name': 'Input Node',
                'group_params': [],
            },
        },
        {
            'id': 'llm-1',
            'data': {
                'id': 'llm-1',
                'type': 'llm',
                'name': 'Planner',
                'group_params': [{
                    'name': 'model',
                    'params': [{
                        'key': 'temperature',
                        'type': 'slide',
                        'required': True,
                        'scope': [0, 1],
                        'value': 0.7,
                    }],
                }],
            },
        },
        {
            'id': 'condition-1',
            'data': {
                'id': 'condition-1',
                'type': 'condition',
                'name': 'Route',
                'group_params': [{
                    'params': [{
                        'key': 'condition',
                        'type': 'condition',
                        'value': [{
                            'id': 'case_a',
                            'operator': 'and',
                            'conditions': [{
                                'id': 'rule_1',
                                'left_var': 'score',
                                'comparison_operation': 'greater_than',
                                'right_value_type': 'const',
                                'right_value': '80',
                                'variable_key_value': {},
                            }],
                            'variable_key_value': {},
                        }],
                    }],
                }],
            },
        },
    ]
    for index, node_type in enumerate(
        ['tool', 'tool', 'code', 'agent', 'tool', 'tool', 'output', 'output', 'output'],
        start=1,
    ):
        node_id = f'node-{index + 3}'
        nodes.append({
            'id': node_id,
            'data': {
                'id': node_id,
                'type': node_type,
                'name': f'{node_type}-{index}',
                'group_params': [],
            },
        })

    edges = [
        {'id': 'edge-1', 'source': 'input-1', 'sourceHandle': 'output', 'target': 'llm-1', 'targetHandle': 'input'},
        {'id': 'edge-2', 'source': 'llm-1', 'sourceHandle': 'output', 'target': 'condition-1', 'targetHandle': 'input'},
        {'id': 'edge-3', 'source': 'condition-1', 'sourceHandle': 'case_a', 'target': 'node-4', 'targetHandle': 'input'},
        {'id': 'edge-4', 'source': 'condition-1', 'sourceHandle': 'right_handle', 'target': 'node-5', 'targetHandle': 'input'},
        {'id': 'edge-5', 'source': 'node-4', 'sourceHandle': 'output', 'target': 'node-6', 'targetHandle': 'input'},
        {'id': 'edge-6', 'source': 'node-5', 'sourceHandle': 'output', 'target': 'node-7', 'targetHandle': 'input'},
        {'id': 'edge-7', 'source': 'node-6', 'sourceHandle': 'output', 'target': 'node-8', 'targetHandle': 'input'},
        {'id': 'edge-8', 'source': 'node-7', 'sourceHandle': 'output', 'target': 'node-9', 'targetHandle': 'input'},
        {'id': 'edge-9', 'source': 'node-8', 'sourceHandle': 'output', 'target': 'node-10', 'targetHandle': 'input'},
        {'id': 'edge-10', 'source': 'node-9', 'sourceHandle': 'output', 'target': 'node-11', 'targetHandle': 'input'},
        {'id': 'edge-11', 'source': 'node-10', 'sourceHandle': 'output', 'target': 'node-12', 'targetHandle': 'input'},
    ]
    return {'nodes': nodes, 'edges': edges}


class TestExternalWorkflowService(IsolatedAsyncioTestCase):
    def test_ensure_create_graph_scaffold_builds_minimal_start_end_graph(self):
        graph = ExternalWorkflowService._ensure_create_graph_scaffold({'nodes': [], 'edges': []})

        self.assertEqual([node['data']['type'] for node in graph['nodes']], ['start', 'end'])
        self.assertEqual([node['type'] for node in graph['nodes']], ['flowNode', 'flowNode'])
        self.assertEqual(len(graph['edges']), 1)
        self.assertEqual(graph['edges'][0]['source'], graph['nodes'][0]['id'])
        self.assertEqual(graph['edges'][0]['target'], graph['nodes'][1]['id'])
        self.assertEqual(graph['edges'][0]['sourceHandle'], 'right_handle')
        self.assertEqual(graph['edges'][0]['targetHandle'], 'left_handle')

    def test_ensure_create_graph_scaffold_wraps_initial_node_with_start_and_end(self):
        graph = ExternalWorkflowService._ensure_create_graph_scaffold({
            'nodes': [{
                'id': 'input-1',
                'position': {'x': 240, 'y': 32},
                'data': {
                    'id': 'input-1',
                    'type': 'input',
                    'name': 'Input Node',
                    'group_params': [],
                },
            }],
            'edges': [],
        })

        node_types = {node['id']: node['data']['type'] for node in graph['nodes']}
        start_id = next(node_id for node_id, node_type in node_types.items() if node_type == 'start')
        end_id = next(node_id for node_id, node_type in node_types.items() if node_type == 'end')

        self.assertEqual(len(graph['nodes']), 3)
        self.assertEqual([node['type'] for node in graph['nodes']], ['flowNode', 'flowNode', 'flowNode'])
        self.assertEqual(len(graph['edges']), 2)
        self.assertTrue(any(edge['source'] == start_id and edge['target'] == 'input-1' for edge in graph['edges']))
        self.assertTrue(any(edge['source'] == 'input-1' and edge['target'] == end_id for edge in graph['edges']))

    def test_ensure_create_graph_scaffold_adds_condition_routes_to_end(self):
        graph = ExternalWorkflowService._ensure_create_graph_scaffold({
            'nodes': [{
                'id': 'condition-1',
                'position': {'x': 120, 'y': 48},
                'data': {
                    'id': 'condition-1',
                    'type': 'condition',
                    'name': 'Condition Node',
                    'group_params': [{
                        'params': [{
                            'key': 'condition',
                            'type': 'condition',
                            'value': [{
                                'id': 'case_a',
                                'operator': 'and',
                                'conditions': [],
                                'variable_key_value': {},
                            }],
                        }],
                    }],
                },
            }],
            'edges': [],
        })

        node_types = {node['id']: node['data']['type'] for node in graph['nodes']}
        start_id = next(node_id for node_id, node_type in node_types.items() if node_type == 'start')
        end_id = next(node_id for node_id, node_type in node_types.items() if node_type == 'end')

        self.assertEqual([node['type'] for node in graph['nodes']], ['flowNode', 'flowNode', 'flowNode'])
        self.assertTrue(any(edge['source'] == start_id and edge['target'] == 'condition-1' for edge in graph['edges']))
        self.assertTrue(
            any(
                edge['source'] == 'condition-1' and edge['target'] == end_id and edge['sourceHandle'] == 'case_a'
                for edge in graph['edges']
            )
        )
        self.assertTrue(
            any(
                edge['source'] == 'condition-1' and edge['target'] == end_id and edge['sourceHandle'] == 'right_handle'
                for edge in graph['edges']
            )
        )

    def test_create_workflow_draft_sync_accepts_normalized_graph_descriptor(self):
        captured = {}

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            captured['graph_data'] = deepcopy(graph_data)

        def fake_create_flow(flow_info, flow_type):
            flow_info.id = 'flow-1'
            return flow_info

        def fake_get_current_version(flow_id):
            return SimpleNamespace(id=11, data=deepcopy(captured['graph_data']))

        with patch.object(ExternalWorkflowService, '_assert_workflow_name_available'), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowDao, 'create_flow', side_effect=fake_create_flow), \
                patch.object(FlowVersionDao, 'get_version_by_flow', side_effect=fake_get_current_version), \
                patch.object(FlowVersionDao, 'update_version', side_effect=lambda version: version), \
                patch.object(FlowService, 'create_flow_hook'):
            flow, version = ExternalWorkflowService._create_workflow_draft_sync(
                login_user=SimpleNamespace(user_id=1),
                name='demo',
                graph_data={
                    'nodes': [{
                        'id': 'input-1',
                        'type': 'input',
                        'name': 'Ticket Input',
                        'params': {},
                    }],
                    'edges': [],
                },
            )

        self.assertEqual(flow.id, 'flow-1')
        self.assertEqual(version.id, 11)
        node_ids = {node['id'] for node in captured['graph_data']['nodes']}
        self.assertIn('input-1', node_ids)
        input_node = next(node for node in captured['graph_data']['nodes'] if node['id'] == 'input-1')
        self.assertEqual(input_node['type'], 'flowNode')
        self.assertEqual(input_node['data']['type'], 'input')
        self.assertEqual(input_node['data']['name'], 'Ticket Input')
        self.assertEqual(input_node['position'], {'x': 0.0, 'y': 0.0})

    async def test_update_workflow_draft_accepts_normalized_graph_descriptor(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value, description='', guide_word='')
        version_graph = make_graph()
        version_graph['nodes'][0]['type'] = 'flowNode'
        version_graph['nodes'][0]['position'] = {'x': 128, 'y': 64}
        version = SimpleNamespace(id=11, data=version_graph, is_current=1)
        validate_calls = []
        persisted = []

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            validate_calls.append(deepcopy(graph_data))

        def fake_update_version(version_info):
            persisted.append(deepcopy(version_info.data))
            return version_info

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version):
            _, updated_version = await ExternalWorkflowService.update_workflow_draft(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                graph_data={
                    'nodes': [{
                        'id': 'node-1',
                        'type': 'llm',
                        'name': 'Router',
                        'params': {
                            'temperature': {'value': 0.3},
                            'system_prompt': {'value': 'route tickets'},
                        },
                    }],
                    'edges': [],
                },
            )

        self.assertEqual(updated_version.id, 11)
        self.assertEqual(len(validate_calls), 1)
        rebuilt_node = validate_calls[0]['nodes'][0]
        self.assertEqual(rebuilt_node['type'], 'flowNode')
        self.assertEqual(rebuilt_node['position'], {'x': 128.0, 'y': 64.0})
        self.assertEqual(rebuilt_node['data']['name'], 'Router')
        params = rebuilt_node['data']['group_params'][0]['params']
        self.assertEqual(params[0]['value'], 0.3)
        self.assertEqual(params[1]['value'], 'route tickets')
        self.assertEqual(params[2]['value'], 'secret')
        self.assertEqual(len(persisted), 1)

    async def test_create_workflow_draft_uses_async_thread_wrapper(self):
        expected_flow = SimpleNamespace(id='flow-1')
        expected_version = SimpleNamespace(id=11, data=make_graph())

        async_to_thread = AsyncMock(return_value=(expected_flow, expected_version))
        with patch('bisheng.api.services.external_workflow.asyncio.to_thread', async_to_thread):
            flow, version = await ExternalWorkflowService.create_workflow_draft(
                login_user=SimpleNamespace(user_id=1),
                name='demo',
                graph_data=make_graph(),
            )

        self.assertEqual(flow.id, 'flow-1')
        self.assertEqual(version.id, 11)
        args = async_to_thread.await_args.args
        self.assertIs(args[0].__func__, ExternalWorkflowService._create_workflow_draft_sync.__func__)
        self.assertEqual(args[2], 'demo')

    def test_create_workflow_draft_sync_validates_scaffolded_initial_graph(self):
        captured = {}

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            captured['graph_data'] = deepcopy(graph_data)

        def fake_create_flow(flow_info, flow_type):
            flow_info.id = 'flow-1'
            return flow_info

        def fake_get_current_version(flow_id):
            return SimpleNamespace(id=11, data=deepcopy(captured['graph_data']))

        with patch.object(ExternalWorkflowService, '_assert_workflow_name_available'), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowDao, 'create_flow', side_effect=fake_create_flow), \
                patch.object(FlowVersionDao, 'get_version_by_flow', side_effect=fake_get_current_version), \
                patch.object(FlowVersionDao, 'update_version', side_effect=lambda version: version), \
                patch.object(FlowService, 'create_flow_hook'):
            flow, version = ExternalWorkflowService._create_workflow_draft_sync(
                login_user=SimpleNamespace(user_id=1),
                name='demo',
                graph_data={'nodes': [], 'edges': []},
            )

        self.assertEqual(flow.id, 'flow-1')
        self.assertEqual(version.id, 11)
        scaffold_types = [node['data']['type'] for node in captured['graph_data']['nodes']]
        self.assertEqual(scaffold_types, ['start', 'end'])
        self.assertEqual([node['type'] for node in captured['graph_data']['nodes']], ['flowNode', 'flowNode'])
        self.assertEqual(len(captured['graph_data']['edges']), 1)

    def test_normalize_workflow_editor_graph_rewrites_legacy_node_types(self):
        graph = {
            'nodes': [{
                'id': 'start-1',
                'type': 'start',
                'position': {'x': 0, 'y': 0},
                'data': {
                    'id': 'start-1',
                    'type': 'start',
                    'name': 'Start',
                    'group_params': [],
                },
            }, {
                'id': 'end-1',
                'type': 'end',
                'position': {'x': 320, 'y': 0},
                'data': {
                    'id': 'end-1',
                    'type': 'end',
                    'name': 'End',
                    'group_params': [],
                },
            }, {
                'id': 'condition-1',
                'type': 'condition',
                'position': {'x': 160, 'y': 0},
                'data': {
                    'id': 'condition-1',
                    'type': 'condition',
                    'name': 'Condition',
                    'group_params': [{
                        'params': [{
                            'key': 'condition',
                            'type': 'condition',
                            'value': [{
                                'id': 'case_a',
                                'operator': 'and',
                                'conditions': [{
                                    'id': 'rule_1',
                                    'left_var': 'code_1.score',
                                    'comparison_operation': 'greater_than',
                                    'right_value_type': 'const',
                                    'right_value': '80',
                                }],
                            }],
                        }],
                    }],
                },
            }],
            'edges': [],
        }

        normalized = FlowService._normalize_workflow_editor_graph(graph)

        self.assertEqual([node['type'] for node in normalized['nodes']], ['flowNode', 'flowNode', 'flowNode'])
        self.assertEqual([node['data']['type'] for node in normalized['nodes']], ['start', 'end', 'condition'])
        self.assertEqual([node['type'] for node in graph['nodes']], ['start', 'end', 'condition'])
        condition_item = normalized['nodes'][2]['data']['group_params'][0]['params'][0]['value'][0]['conditions'][0]
        self.assertEqual(condition_item['right_value_type'], 'input')
        self.assertEqual(condition_item['left_label'], '')
        self.assertEqual(condition_item['right_label'], '')

    def test_normalize_condition_cases_keeps_editor_friendly_shape(self):
        normalized = ExternalWorkflowService._normalize_condition_cases([{
            'id': 'case_a',
            'operator': 'and',
            'conditions': [{
                'id': 'rule_1',
                'left_var': 'code_1.score',
                'left_label': 'Score/priority_score',
                'comparison_operation': 'greater_than_or_equal',
                'right_value_type': 'const',
                'right_value': '90',
                'right_label': '',
                'variable_key_value': {},
            }],
            'variable_key_value': {},
        }])

        condition_item = normalized[0]['conditions'][0]
        self.assertEqual(condition_item['left_label'], 'Score/priority_score')
        self.assertEqual(condition_item['right_label'], '')
        self.assertEqual(condition_item['right_value_type'], 'input')

    def test_normalize_workflow_editor_graph_hydrates_condition_labels(self):
        graph = {
            'nodes': [{
                'id': 'code-1',
                'type': 'flowNode',
                'position': {'x': 0, 'y': 0},
                'data': {
                    'id': 'code-1',
                    'type': 'code',
                    'name': 'Score Priority',
                    'group_params': [{
                        'name': '出参',
                        'params': [{
                            'key': 'code_output',
                            'type': 'code_output',
                            'global': 'code:value.map(el => ({ label: el.key, value: el.key }))',
                            'value': [{'key': 'priority_score', 'type': 'str'}],
                        }],
                    }],
                },
            }, {
                'id': 'condition-1',
                'type': 'flowNode',
                'position': {'x': 320, 'y': 0},
                'data': {
                    'id': 'condition-1',
                    'type': 'condition',
                    'name': 'Condition',
                    'group_params': [{
                        'params': [{
                            'key': 'condition',
                            'type': 'condition',
                            'value': [{
                                'id': 'case_a',
                                'operator': 'and',
                                'conditions': [{
                                    'id': 'rule_1',
                                    'left_var': 'code-1.priority_score',
                                    'comparison_operation': 'greater_than_or_equal',
                                    'right_value_type': 'const',
                                    'right_value': '90',
                                }],
                            }],
                        }],
                    }],
                },
            }],
            'edges': [],
        }

        normalized = FlowService._normalize_workflow_editor_graph(graph)
        condition_item = normalized['nodes'][1]['data']['group_params'][0]['params'][0]['value'][0]['conditions'][0]

        self.assertEqual(condition_item['left_label'], 'Score Priority/priority_score')
        self.assertEqual(condition_item['right_label'], '')
        self.assertEqual(condition_item['right_value_type'], 'input')

    def test_get_existing_external_draft_version_limits_recent_versions(self):
        captured = {'statements': []}

        class FakeResult:
            def __init__(self, versions):
                self._versions = versions

            def all(self):
                return self._versions

        class FakeSession:
            def __init__(self):
                self.calls = 0

            def exec(self, statement):
                captured['statements'].append(statement)
                self.calls += 1
                if self.calls == 1:
                    versions = [SimpleNamespace(data={'nodes': [], 'edges': []}) for _ in range(
                        ExternalWorkflowService._MAX_EXTERNAL_DRAFT_SCAN)]
                    return FakeResult(versions)
                return FakeResult([
                    SimpleNamespace(data=ExternalWorkflowService._mark_graph_as_draft({'nodes': [], 'edges': []}))
                ])

        class FakeContext:
            def __enter__(self):
                if 'session' not in captured:
                    captured['session'] = FakeSession()
                return captured['session']

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch('bisheng.api.services.external_workflow.get_sync_db_session', return_value=FakeContext()):
            result = ExternalWorkflowService._get_existing_external_draft_version('flow-1')

        self.assertIsNotNone(result)
        self.assertEqual(len(captured['statements']), 2)
        self.assertIsNotNone(captured['statements'][0]._limit_clause)
        self.assertEqual(captured['statements'][0]._limit_clause.value, ExternalWorkflowService._MAX_EXTERNAL_DRAFT_SCAN)
        self.assertEqual(captured['statements'][1]._offset_clause.value, ExternalWorkflowService._MAX_EXTERNAL_DRAFT_SCAN)

    async def test_get_workflow_node_params_returns_extended_metadata(self):
        version = SimpleNamespace(id=11, data=make_graph())

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return SimpleNamespace(id=flow_id, name='demo', status=FlowStatus.OFFLINE.value), version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            result = await ExternalWorkflowService.get_workflow_node_params(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_id='node-1',
            )

        temperature = result['params']['temperature']
        self.assertEqual(temperature['group_name'], 'model')
        self.assertEqual(temperature['scope'], [0, 1])
        self.assertEqual(temperature['placeholder'], '0.0 ~ 1.0')
        self.assertTrue(temperature['refresh'])
        self.assertEqual(temperature['options'], [{'key': 0.3, 'value': 0.3}, {'key': 0.7, 'value': 0.7}])
        self.assertNotIn('openai_api_key', result['params'])
        self.assertNotIn('hidden_internal', result['params'])

    async def test_update_workflow_node_params_revalidates_before_persist(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=make_graph(), is_current=1)
        validate_calls = []
        persisted = []

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            validate_calls.append((flow_name, flow_id, deepcopy(graph_data)))

        def fake_update_version(version_info):
            persisted.append(deepcopy(version_info.data))
            return version_info

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version):
            _, updated_version = await ExternalWorkflowService.update_workflow_node_params(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_id='node-1',
                updates={'temperature': 0.3},
            )

        self.assertEqual(updated_version.id, 11)
        self.assertEqual(len(validate_calls), 1)
        self.assertEqual(validate_calls[0][0], 'demo')
        self.assertEqual(validate_calls[0][1], 'flow-1')
        self.assertEqual(validate_calls[0][2]['nodes'][0]['data']['group_params'][0]['params'][0]['value'], 0.3)
        self.assertEqual(len(persisted), 1)
        self.assertTrue(persisted[0]['_external_workflow_meta']['draft'])
        self.assertEqual(persisted[0]['nodes'][0]['data']['group_params'][0]['params'][0]['value'], 0.3)
        self.assertEqual(persisted[0]['_external_workflow_meta']['revision'], 1)

    async def test_update_workflow_node_params_rejects_revision_mismatch(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=ExternalWorkflowService._mark_graph_as_draft(make_graph()), is_current=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            with self.assertRaises(WorkFlowVersionUpdateError):
                await ExternalWorkflowService.update_workflow_node_params(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    node_id='node-1',
                    updates={'temperature': 0.3},
                    expected_revision=999,
                )

    async def test_update_workflow_node_params_rejects_invalid_graph_before_persist(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=make_graph(), is_current=1)
        persist_calls = []

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            raise WorkFlowInitError(msg='invalid graph')

        def fake_update_version(version_info):
            persist_calls.append(version_info)
            return version_info

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version):
            with self.assertRaises(WorkFlowInitError):
                await ExternalWorkflowService.update_workflow_node_params(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    node_id='node-1',
                    updates={'temperature': 0.3},
                )

        self.assertEqual(persist_calls, [])

    async def test_update_workflow_draft_rejects_duplicate_name(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value, description='', guide_word='')
        version = SimpleNamespace(id=11, data=make_graph(), is_current=1)
        update_flow = AsyncMock()

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_assert_workflow_name_available(login_user, name, exclude_flow_id=None):
            raise WorkflowNameExistsError()

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_assert_workflow_name_available',
                             side_effect=fake_assert_workflow_name_available), \
                patch('bisheng.api.services.external_workflow.FlowDao.aupdate_flow', update_flow):
            with self.assertRaises(WorkflowNameExistsError):
                await ExternalWorkflowService.update_workflow_draft(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    graph_data=make_graph(),
                    name='duplicate',
                )

        update_flow.assert_not_called()

    async def test_publish_workflow_restores_draft_marker_on_failure(self):
        draft_graph = ExternalWorkflowService._mark_graph_as_draft(make_graph())
        flow = SimpleNamespace(id='flow-1')
        version = SimpleNamespace(id=11, data=deepcopy(draft_graph), is_current=1)
        updated_payloads = []

        async def fake_validate_workflow(login_user, flow_id, version_id):
            return flow, version

        async def fake_update_flow_status(login_user, flow_id, version_id, status):
            raise RuntimeError('publish failed')

        def fake_update_version(version_info):
            updated_payloads.append(deepcopy(version_info.data))
            return version_info

        with patch.object(ExternalWorkflowService, 'validate_workflow', side_effect=fake_validate_workflow), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version), \
                patch.object(WorkFlowService, 'update_flow_status', side_effect=fake_update_flow_status):
            with self.assertRaises(RuntimeError):
                await ExternalWorkflowService.publish_workflow(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    version_id=11,
                )

        self.assertEqual(len(updated_payloads), 2)
        self.assertNotIn('_external_workflow_meta', updated_payloads[0])
        self.assertTrue(updated_payloads[1]['_external_workflow_meta']['draft'])

    async def test_add_workflow_node_revalidates_before_persist(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=make_graph(), is_current=1)
        persisted = []

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            return None

        def fake_update_version(version_info):
            persisted.append(deepcopy(version_info.data))
            return version_info

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version):
            _, updated_version, node_id = await ExternalWorkflowService.add_workflow_node(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_type='code',
                name='Code Node',
                position_x=120,
                position_y=260,
            )

        self.assertEqual(updated_version.id, 11)
        self.assertTrue(node_id.startswith('code_'))
        self.assertEqual(len(persisted), 1)
        self.assertEqual(len(persisted[0]['nodes']), 2)
        self.assertEqual(persisted[0]['nodes'][1]['id'], node_id)
        self.assertEqual(persisted[0]['nodes'][1]['type'], 'flowNode')
        self.assertEqual(persisted[0]['nodes'][1]['position'], {'x': 120, 'y': 260})
        self.assertEqual(persisted[0]['nodes'][1]['data']['type'], 'code')
        self.assertEqual(persisted[0]['nodes'][1]['data']['name'], 'Code Node')
        self.assertTrue(persisted[0]['_external_workflow_meta']['draft'])

    async def test_remove_workflow_node_cascades_related_edges(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        graph = make_graph()
        graph['nodes'].append({
            'id': 'node-2',
            'data': {
                'id': 'node-2',
                'type': 'output',
                'name': 'Output Node',
                'group_params': [],
            },
        })
        graph['edges'].append({
            'id': 'edge-1',
            'source': 'node-1',
            'sourceHandle': 'output',
            'target': 'node-2',
            'targetHandle': 'input',
        })
        version = SimpleNamespace(id=11, data=graph, is_current=1)
        persisted = []

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            return None

        def fake_update_version(version_info):
            persisted.append(deepcopy(version_info.data))
            return version_info

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version):
            await ExternalWorkflowService.remove_workflow_node(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_id='node-2',
            )

        self.assertEqual(len(persisted), 1)
        self.assertEqual(len(persisted[0]['nodes']), 1)
        self.assertEqual(persisted[0]['nodes'][0]['id'], 'node-1')
        self.assertEqual(persisted[0]['edges'], [])

    async def test_remove_workflow_node_rejects_connected_node_when_cascade_disabled(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        graph = make_graph()
        graph['nodes'].append({
            'id': 'node-2',
            'data': {
                'id': 'node-2',
                'type': 'output',
                'name': 'Output Node',
                'group_params': [],
            },
        })
        graph['edges'].append({
            'id': 'edge-1',
            'source': 'node-1',
            'sourceHandle': 'output',
            'target': 'node-2',
            'targetHandle': 'input',
        })
        version = SimpleNamespace(id=11, data=graph, is_current=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            with self.assertRaises(WorkFlowInitError):
                await ExternalWorkflowService.remove_workflow_node(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    node_id='node-2',
                    cascade=False,
                )

    async def test_connect_and_disconnect_workflow_nodes_persist_edge_updates(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        graph = make_graph()
        graph['nodes'].append({
            'id': 'node-2',
            'data': {
                'id': 'node-2',
                'type': 'output',
                'name': 'Output Node',
                'group_params': [],
            },
        })
        version = SimpleNamespace(id=11, data=graph, is_current=1)
        persisted = []

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            return None

        def fake_update_version(version_info):
            persisted.append(deepcopy(version_info.data))
            version.data = deepcopy(version_info.data)
            return version_info

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version):
            _, _, edge_id = await ExternalWorkflowService.connect_workflow_nodes(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                source_node_id='node-1',
                target_node_id='node-2',
                source_handle='output',
                target_handle='input',
            )
            _, _, removed_edge_id = await ExternalWorkflowService.disconnect_workflow_edge(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                edge_id=edge_id,
            )

        self.assertEqual(edge_id, removed_edge_id)
        self.assertEqual(len(persisted), 2)
        self.assertEqual(len(persisted[0]['edges']), 1)
        self.assertEqual(persisted[0]['edges'][0]['id'], edge_id)
        self.assertEqual(persisted[0]['edges'][0]['sourceType'], 'llm')
        self.assertEqual(persisted[0]['edges'][0]['targetType'], 'output')
        self.assertEqual(persisted[1]['edges'], [])

    async def test_connect_workflow_nodes_rejects_duplicate_edge(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        graph = make_graph()
        graph['nodes'].append({
            'id': 'node-2',
            'data': {
                'id': 'node-2',
                'type': 'output',
                'name': 'Output Node',
                'group_params': [],
            },
        })
        graph['edges'].append({
            'id': 'edge-1',
            'source': 'node-1',
            'sourceHandle': 'output',
            'target': 'node-2',
            'targetHandle': 'input',
        })
        version = SimpleNamespace(id=11, data=graph, is_current=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            with self.assertRaises(WorkFlowInitError):
                await ExternalWorkflowService.connect_workflow_nodes(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    source_node_id='node-1',
                    target_node_id='node-2',
                    source_handle='output',
                    target_handle='input',
                )

    async def test_disconnect_workflow_edge_rejects_ambiguous_selector(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        graph = make_graph()
        graph['nodes'].append({
            'id': 'node-2',
            'data': {
                'id': 'node-2',
                'type': 'output',
                'name': 'Output Node',
                'group_params': [],
            },
        })
        graph['nodes'].append({
            'id': 'node-3',
            'data': {
                'id': 'node-3',
                'type': 'output',
                'name': 'Output Node 2',
                'group_params': [],
            },
        })
        graph['edges'].extend([{
            'id': 'edge-1',
            'source': 'node-1',
            'sourceHandle': 'output',
            'target': 'node-2',
            'targetHandle': 'input',
        }, {
            'id': 'edge-2',
            'source': 'node-1',
            'sourceHandle': 'output',
            'target': 'node-3',
            'targetHandle': 'input',
        }])
        version = SimpleNamespace(id=11, data=graph, is_current=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            with self.assertRaises(WorkFlowInitError):
                await ExternalWorkflowService.disconnect_workflow_edge(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    source_node_id='node-1',
                    source_handle='output',
                )

    async def test_get_condition_node_config_returns_cases_and_routes(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=make_condition_graph(), is_current=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            result = await ExternalWorkflowService.get_condition_node_config(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_id='condition-1',
            )

        self.assertEqual(result['node_id'], 'condition-1')
        self.assertEqual(result['condition_cases'][0]['id'], 'case_a')
        self.assertIn('case_a', result['route_handles'])
        self.assertIn('right_handle', result['route_handles'])
        self.assertEqual(result['outgoing_edges']['case_a'][0]['edge_id'], 'edge-1')

    async def test_get_condition_node_config_rejects_non_condition_node(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=make_graph(), is_current=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            with self.assertRaises(WorkFlowInitError):
                await ExternalWorkflowService.get_condition_node_config(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    node_id='node-1',
                )

    async def test_update_condition_node_persists_structured_cases(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=make_condition_graph(), is_current=1)
        persisted = []

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_validate(login_user, graph_data, flow_name, flow_id=None):
            return None

        def fake_update_version(version_info):
            persisted.append(deepcopy(version_info.data))
            return version_info

        new_cases = [{
            'id': 'case_b',
            'operator': 'or',
            'conditions': [{
                'id': 'rule_2',
                'left_var': 'intent',
                'comparison_operation': 'equals',
                'right_value_type': 'const',
                'right_value': 'vip',
                'variable_key_value': {},
            }],
            'variable_key_value': {},
        }]

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph', side_effect=fake_validate), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version):
            _, updated_version = await ExternalWorkflowService.update_condition_node(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_id='condition-1',
                condition_cases=new_cases,
            )

        self.assertEqual(updated_version.id, 11)
        self.assertEqual(persisted[0]['nodes'][0]['data']['group_params'][0]['params'][0]['value'][0]['id'], 'case_b')
        self.assertTrue(persisted[0]['_external_workflow_meta']['draft'])

    async def test_update_condition_node_rejects_case_id_without_matching_edge(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=make_condition_graph(), is_current=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            with self.assertRaises(WorkFlowInitError):
                await ExternalWorkflowService.update_condition_node(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    node_id='condition-1',
                    condition_cases=[{
                        'id': 'case_renamed',
                        'operator': 'and',
                        'conditions': [{
                            'id': 'rule_1',
                            'left_var': 'score',
                            'comparison_operation': 'greater_than',
                            'right_value_type': 'const',
                            'right_value': '80',
                            'variable_key_value': {},
                        }],
                        'variable_key_value': {},
                    }],
                )

    async def test_update_condition_node_rejects_duplicate_case_ids(self):
        flow = SimpleNamespace(id='flow-1', name='demo', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(id=11, data=make_condition_graph(), is_current=1)

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version):
            with self.assertRaises(WorkFlowInitError):
                await ExternalWorkflowService.update_condition_node(
                    login_user=SimpleNamespace(user_id=1),
                    flow_id='flow-1',
                    node_id='condition-1',
                    condition_cases=[{
                        'id': 'case_a',
                        'operator': 'and',
                        'conditions': [],
                        'variable_key_value': {},
                    }, {
                        'id': 'case_a',
                        'operator': 'or',
                        'conditions': [],
                        'variable_key_value': {},
                    }],
                )

    def test_validate_condition_node_routes_rejects_missing_fallback_edge(self):
        graph = make_condition_graph()
        graph['edges'] = [edge for edge in graph['edges'] if edge['sourceHandle'] != 'right_handle']

        with self.assertRaises(WorkFlowInitError):
            ExternalWorkflowService._validate_special_node_routes(graph)

    async def test_large_graph_editing_scenario_supports_sequential_mutations(self):
        flow = SimpleNamespace(id='flow-1', name='complex-flow', status=FlowStatus.OFFLINE.value)
        version = SimpleNamespace(
            id=21,
            data=ExternalWorkflowService._mark_graph_as_draft(make_large_graph()),
            is_current=1,
        )

        async def fake_get_editable_version(login_user, flow_id, version_id=None):
            return flow, version

        def fake_update_version(version_info):
            version.data = deepcopy(version_info.data)
            return version_info

        with patch.object(ExternalWorkflowService, '_get_editable_version', side_effect=fake_get_editable_version), \
                patch.object(ExternalWorkflowService, '_validate_draft_graph'), \
                patch.object(FlowVersionDao, 'update_version', side_effect=fake_update_version):
            _, updated_version, added_node_id = await ExternalWorkflowService.add_workflow_node(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_type='tool',
                name='Late Tool',
                position_x=640,
                position_y=240,
                expected_revision=1,
            )
            self.assertEqual(updated_version.id, 21)
            self.assertEqual(ExternalWorkflowService.get_graph_revision(version.data), 2)
            self.assertTrue(any(node['id'] == added_node_id for node in version.data['nodes']))

            _, _, added_edge_id = await ExternalWorkflowService.connect_workflow_nodes(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                source_node_id='node-8',
                target_node_id=added_node_id,
                source_handle='output',
                target_handle='input',
                expected_revision=2,
            )
            self.assertEqual(ExternalWorkflowService.get_graph_revision(version.data), 3)
            self.assertTrue(any(edge['id'] == added_edge_id for edge in version.data['edges']))

            await ExternalWorkflowService.update_workflow_node_params(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_id='llm-1',
                updates={'temperature': 0.2},
                expected_revision=3,
            )
            llm_node = next(node for node in version.data['nodes'] if node['id'] == 'llm-1')
            self.assertEqual(llm_node['data']['group_params'][0]['params'][0]['value'], 0.2)
            self.assertEqual(ExternalWorkflowService.get_graph_revision(version.data), 4)

            await ExternalWorkflowService.update_condition_node(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_id='condition-1',
                condition_cases=[{
                    'id': 'case_a',
                    'operator': 'and',
                    'conditions': [{
                        'id': 'rule_1',
                        'left_var': 'score',
                        'comparison_operation': 'greater_than_or_equal',
                        'right_value_type': 'const',
                        'right_value': '90',
                        'variable_key_value': {},
                    }],
                    'variable_key_value': {},
                }],
                expected_revision=4,
            )
            condition_payload = next(
                param for param in next(node for node in version.data['nodes'] if node['id'] == 'condition-1')['data'][
                    'group_params'][0]['params']
                if param['key'] == 'condition'
            )
            self.assertEqual(condition_payload['value'][0]['conditions'][0]['right_value'], '90')
            self.assertEqual(ExternalWorkflowService.get_graph_revision(version.data), 5)

            await ExternalWorkflowService.disconnect_workflow_edge(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                edge_id=added_edge_id,
                expected_revision=5,
            )
            self.assertEqual(ExternalWorkflowService.get_graph_revision(version.data), 6)

            await ExternalWorkflowService.remove_workflow_node(
                login_user=SimpleNamespace(user_id=1),
                flow_id='flow-1',
                node_id=added_node_id,
                expected_revision=6,
            )
            self.assertFalse(any(node['id'] == added_node_id for node in version.data['nodes']))
            self.assertEqual(ExternalWorkflowService.get_graph_revision(version.data), 7)
