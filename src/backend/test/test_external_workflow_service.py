from copy import deepcopy
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from bisheng.api.services.external_workflow import ExternalWorkflowService
from bisheng.api.services.workflow import WorkFlowService
from bisheng.common.errcode.flow import WorkFlowInitError, WorkFlowVersionUpdateError, WorkflowNameExistsError
from bisheng.database.models.flow import FlowStatus
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


class TestExternalWorkflowService(IsolatedAsyncioTestCase):
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
