import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.database.models.flow import FlowType


def _load_workflow_service_module():
    service_dir = Path(__file__).resolve().parents[1] / 'bisheng' / 'api' / 'services'
    stubbed = [
        'bisheng.api',
        'bisheng.api.services',
        'bisheng.api.v1.schema.workflow',
        'bisheng.api.v1.schemas',
        'bisheng.common.chat.utils',
        'bisheng.common.constants.enums.telemetry',
        'bisheng.common.dependencies.user_deps',
        'bisheng.common.errcode.flow',
        'bisheng.common.errcode.http_error',
        'bisheng.common.services',
        'bisheng.common.services.base',
        'bisheng.core.logger',
        'bisheng.database.models.flow',
        'bisheng.database.models.flow_version',
        'bisheng.database.models.group_resource',
        'bisheng.database.models.role_access',
        'bisheng.database.models.tag',
        'bisheng.database.models.user_link',
        'bisheng.user.domain.models.user',
        'bisheng.utils',
        'bisheng.workflow.callback.base_callback',
        'bisheng.workflow.common.node',
        'bisheng.workflow.graph.graph_state',
        'bisheng.workflow.graph.workflow',
        'bisheng.workflow.nodes.node_manage',
        'bisheng.permission.domain.services.application_permission_service',
    ]
    original = {name: sys.modules.get(name) for name in stubbed}

    try:
        api_package = ModuleType('bisheng.api')
        api_package.__path__ = [str(service_dir.parent)]
        sys.modules['bisheng.api'] = api_package

        services_package = ModuleType('bisheng.api.services')
        services_package.__path__ = [str(service_dir)]
        sys.modules['bisheng.api.services'] = services_package

        workflow_schema_module = ModuleType('bisheng.api.v1.schema.workflow')
        dummy = SimpleNamespace
        workflow_schema_module.WorkflowEvent = dummy
        workflow_schema_module.WorkflowEventType = dummy
        workflow_schema_module.WorkflowInputSchema = dummy
        workflow_schema_module.WorkflowInputItem = dummy
        workflow_schema_module.WorkflowOutputSchema = dummy
        sys.modules['bisheng.api.v1.schema.workflow'] = workflow_schema_module

        schemas_module = ModuleType('bisheng.api.v1.schemas')
        schemas_module.ChatResponse = SimpleNamespace
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

        chat_utils_module = ModuleType('bisheng.common.chat.utils')
        chat_utils_module.SourceType = SimpleNamespace
        sys.modules['bisheng.common.chat.utils'] = chat_utils_module

        telemetry_module = ModuleType('bisheng.common.constants.enums.telemetry')
        telemetry_module.BaseTelemetryTypeEnum = SimpleNamespace(EDIT_APPLICATION='edit_application')
        sys.modules['bisheng.common.constants.enums.telemetry'] = telemetry_module

        user_deps_module = ModuleType('bisheng.common.dependencies.user_deps')
        user_deps_module.UserPayload = SimpleNamespace
        sys.modules['bisheng.common.dependencies.user_deps'] = user_deps_module

        flow_error_module = ModuleType('bisheng.common.errcode.flow')
        flow_error_module.WorkFlowInitError = Exception
        sys.modules['bisheng.common.errcode.flow'] = flow_error_module

        http_error_module = ModuleType('bisheng.common.errcode.http_error')
        http_error_module.NotFoundError = Exception
        http_error_module.UnAuthorizedError = Exception
        sys.modules['bisheng.common.errcode.http_error'] = http_error_module

        common_services_module = ModuleType('bisheng.common.services')
        common_services_module.telemetry_service = SimpleNamespace(log_event=AsyncMock())
        sys.modules['bisheng.common.services'] = common_services_module

        base_service_module = ModuleType('bisheng.common.services.base')
        base_service_module.BaseService = object
        sys.modules['bisheng.common.services.base'] = base_service_module

        logger_module = ModuleType('bisheng.core.logger')
        logger_module.trace_id_var = SimpleNamespace(get=lambda: 'trace')
        sys.modules['bisheng.core.logger'] = logger_module

        flow_module = ModuleType('bisheng.database.models.flow')
        flow_module.FlowDao = SimpleNamespace(aget_all_apps=AsyncMock(), get_all_apps=MagicMock())
        flow_module.FlowStatus = SimpleNamespace(ONLINE=SimpleNamespace(value=2))
        flow_module.FlowType = FlowType
        flow_module.Flow = SimpleNamespace
        flow_module.UserLinkType = SimpleNamespace
        sys.modules['bisheng.database.models.flow'] = flow_module

        flow_version_module = ModuleType('bisheng.database.models.flow_version')
        flow_version_module.FlowVersionDao = SimpleNamespace(get_list_by_flow_ids=lambda ids: [])
        sys.modules['bisheng.database.models.flow_version'] = flow_version_module

        group_resource_module = ModuleType('bisheng.database.models.group_resource')
        group_resource_module.ResourceTypeEnum = SimpleNamespace(WORK_FLOW='workflow', ASSISTANT='assistant')
        sys.modules['bisheng.database.models.group_resource'] = group_resource_module

        role_access_module = ModuleType('bisheng.database.models.role_access')
        from bisheng.database.models.role_access import AccessType
        role_access_module.AccessType = AccessType
        sys.modules['bisheng.database.models.role_access'] = role_access_module

        tag_module = ModuleType('bisheng.database.models.tag')
        tag_module.TagDao = SimpleNamespace(
            get_resources_by_tags_batch=lambda *args, **kwargs: [],
            get_tags_by_resource=lambda *args, **kwargs: {},
        )
        tag_module.TagBusinessTypeEnum = SimpleNamespace(
            APPLICATION=SimpleNamespace(value='application'),
        )
        sys.modules['bisheng.database.models.tag'] = tag_module

        user_link_module = ModuleType('bisheng.database.models.user_link')
        user_link_module.UserLinkDao = SimpleNamespace()
        sys.modules['bisheng.database.models.user_link'] = user_link_module

        user_module = ModuleType('bisheng.user.domain.models.user')
        user_module.UserDao = SimpleNamespace(get_user_by_ids=lambda ids: [])
        sys.modules['bisheng.user.domain.models.user'] = user_module

        utils_module = ModuleType('bisheng.utils')
        utils_module.generate_uuid = lambda: 'uuid'
        sys.modules['bisheng.utils'] = utils_module

        callback_module = ModuleType('bisheng.workflow.callback.base_callback')
        callback_module.BaseCallback = SimpleNamespace
        sys.modules['bisheng.workflow.callback.base_callback'] = callback_module

        node_module = ModuleType('bisheng.workflow.common.node')
        node_module.BaseNodeData = SimpleNamespace
        node_module.NodeType = SimpleNamespace(
            CODE=SimpleNamespace(value='code'),
            TOOL=SimpleNamespace(value='tool'),
            QA_RETRIEVER=SimpleNamespace(value='qa'),
            RAG=SimpleNamespace(value='rag'),
            LLM=SimpleNamespace(value='llm'),
            AGENT=SimpleNamespace(value='agent'),
        )
        sys.modules['bisheng.workflow.common.node'] = node_module

        graph_state_module = ModuleType('bisheng.workflow.graph.graph_state')
        graph_state_module.GraphState = SimpleNamespace
        sys.modules['bisheng.workflow.graph.graph_state'] = graph_state_module

        workflow_graph_module = ModuleType('bisheng.workflow.graph.workflow')
        workflow_graph_module.Workflow = SimpleNamespace
        sys.modules['bisheng.workflow.graph.workflow'] = workflow_graph_module

        node_manage_module = ModuleType('bisheng.workflow.nodes.node_manage')
        node_manage_module.NodeFactory = SimpleNamespace(instance_node=lambda **kwargs: None)
        sys.modules['bisheng.workflow.nodes.node_manage'] = node_manage_module

        app_permission_module = ModuleType('bisheng.permission.domain.services.application_permission_service')

        class _DummyApplicationPermissionService:
            @staticmethod
            async def get_app_permission_map_async(login_user, rows, permission_ids):
                return {}

        app_permission_module.ApplicationPermissionService = _DummyApplicationPermissionService
        sys.modules['bisheng.permission.domain.services.application_permission_service'] = app_permission_module

        module_name = 'bisheng.api.services.workflow'
        if module_name in sys.modules:
            sys.modules.pop(module_name)
        spec = importlib.util.spec_from_file_location(module_name, service_dir / 'workflow.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, module in original.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@pytest.mark.asyncio
async def test_get_all_flows_filters_by_use_app_and_sets_write_from_edit_app():
    workflow_module = _load_workflow_service_module()
    WorkFlowService = workflow_module.WorkFlowService

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['wf-1', 'asst-1']),
        access_check=MagicMock(side_effect=AssertionError('legacy access_check should not drive write flag')),
    )

    app_rows = [
        {'id': 'wf-1', 'flow_type': FlowType.WORKFLOW.value, 'user_id': 9, 'logo': '', 'name': 'wf'},
        {'id': 'asst-1', 'flow_type': FlowType.ASSISTANT.value, 'user_id': 10, 'logo': '', 'name': 'asst'},
    ]

    permission_map = {
        'wf-1': {'view_app'},
        'asst-1': {'use_app', 'edit_app'},
    }

    with patch.object(
        workflow_module.FlowDao,
        'aget_all_apps',
        new_callable=AsyncMock,
        return_value=(app_rows, 2),
    ), patch.object(
        workflow_module.ApplicationPermissionService,
        'get_app_permission_map_async',
        new_callable=AsyncMock,
        return_value=permission_map,
    ), patch.object(
        WorkFlowService,
        'get_logo_share_link',
        return_value='logo-url',
        create=True,
    ), patch.object(
        WorkFlowService,
        'aenrich_apps_can_share',
        new_callable=AsyncMock,
        side_effect=lambda _user, data, managed=False: data,
        create=True,
    ):
        data, total = await WorkFlowService.get_all_flows(
            user=login_user,
            name='',
            status=None,
            tag_id=None,
            flow_type=FlowType.ASSISTANT.value,
            page=1,
            page_size=10,
            managed=False,
        )

    assert total == 1
    assert [one['id'] for one in data] == ['asst-1']
    assert data[0]['write'] is True


@pytest.mark.asyncio
async def test_get_all_flows_specific_type_repaginates_after_permission_filter():
    workflow_module = _load_workflow_service_module()
    WorkFlowService = workflow_module.WorkFlowService

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['asst-1', 'asst-2', 'asst-3']),
        access_check=MagicMock(side_effect=AssertionError('legacy access_check should not drive write flag')),
    )

    app_rows = [
        {'id': 'asst-1', 'flow_type': FlowType.ASSISTANT.value, 'user_id': 10, 'logo': '', 'name': 'asst-1'},
        {'id': 'asst-2', 'flow_type': FlowType.ASSISTANT.value, 'user_id': 11, 'logo': '', 'name': 'asst-2'},
        {'id': 'asst-3', 'flow_type': FlowType.ASSISTANT.value, 'user_id': 12, 'logo': '', 'name': 'asst-3'},
    ]

    permission_map = {
        'asst-1': {'use_app'},
        'asst-2': {'use_app'},
        'asst-3': {'view_app'},
    }

    with patch.object(
        workflow_module.FlowDao,
        'aget_all_apps',
        new_callable=AsyncMock,
        return_value=(app_rows, 3),
    ) as mock_aget_all_apps, patch.object(
        workflow_module.ApplicationPermissionService,
        'get_app_permission_map_async',
        new_callable=AsyncMock,
        return_value=permission_map,
    ), patch.object(
        WorkFlowService,
        'get_logo_share_link',
        return_value='logo-url',
        create=True,
    ), patch.object(
        WorkFlowService,
        'aenrich_apps_can_share',
        new_callable=AsyncMock,
        side_effect=lambda _user, data, managed=False: data,
        create=True,
    ):
        data, total = await WorkFlowService.get_all_flows(
            user=login_user,
            name='',
            status=None,
            tag_id=None,
            flow_type=FlowType.ASSISTANT.value,
            page=2,
            page_size=1,
            managed=False,
        )

    assert mock_aget_all_apps.await_args.args[7] == 0
    assert mock_aget_all_apps.await_args.args[8] == 0
    assert total == 2
    assert [one['id'] for one in data] == ['asst-2']


@pytest.mark.asyncio
async def test_get_all_flows_recomputes_total_for_combined_listing_after_permission_filter():
    workflow_module = _load_workflow_service_module()
    WorkFlowService = workflow_module.WorkFlowService

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['wf-1', 'asst-1']),
        access_check=MagicMock(side_effect=AssertionError('legacy access_check should not be used')),
    )

    app_rows = [
        {'id': 'wf-1', 'flow_type': FlowType.WORKFLOW.value, 'user_id': 9, 'logo': '', 'name': 'wf'},
        {'id': 'asst-1', 'flow_type': FlowType.ASSISTANT.value, 'user_id': 10, 'logo': '', 'name': 'asst'},
    ]

    permission_map = {
        'wf-1': {'view_app'},
        'asst-1': {'use_app', 'edit_app'},
    }

    with patch.object(
        workflow_module.FlowDao,
        'aget_all_apps',
        new_callable=AsyncMock,
        return_value=(app_rows, 2),
    ), patch.object(
        workflow_module.ApplicationPermissionService,
        'get_app_permission_map_async',
        new_callable=AsyncMock,
        return_value=permission_map,
    ), patch.object(
        WorkFlowService,
        'get_logo_share_link',
        return_value='logo-url',
        create=True,
    ), patch.object(
        WorkFlowService,
        'aenrich_apps_can_share',
        new_callable=AsyncMock,
        side_effect=lambda _user, data, managed=False: data,
        create=True,
    ):
        data, total = await WorkFlowService.get_all_flows(
            user=login_user,
            name='',
            status=None,
            tag_id=None,
            flow_type=None,
            page=1,
            page_size=10,
            managed=False,
        )

    assert total == 1
    assert [one['id'] for one in data] == ['asst-1']


@pytest.mark.asyncio
async def test_get_all_flows_can_filter_by_view_app():
    workflow_module = _load_workflow_service_module()
    WorkFlowService = workflow_module.WorkFlowService

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['wf-1', 'asst-1']),
        access_check=MagicMock(side_effect=AssertionError('legacy access_check should not be used')),
    )

    app_rows = [
        {'id': 'wf-1', 'flow_type': FlowType.WORKFLOW.value, 'user_id': 9, 'logo': '', 'name': 'wf'},
        {'id': 'asst-1', 'flow_type': FlowType.ASSISTANT.value, 'user_id': 10, 'logo': '', 'name': 'asst'},
    ]

    permission_map = {
        'wf-1': {'view_app'},
        'asst-1': {'use_app'},
    }

    with patch.object(
        workflow_module.FlowDao,
        'aget_all_apps',
        new_callable=AsyncMock,
        return_value=(app_rows, 2),
    ), patch.object(
        workflow_module.ApplicationPermissionService,
        'get_app_permission_map_async',
        new_callable=AsyncMock,
        return_value=permission_map,
    ), patch.object(
        WorkFlowService,
        'get_logo_share_link',
        return_value='logo-url',
        create=True,
    ), patch.object(
        WorkFlowService,
        'aenrich_apps_can_share',
        new_callable=AsyncMock,
        side_effect=lambda _user, data, managed=False: data,
        create=True,
    ):
        data, total = await WorkFlowService.get_all_flows(
            user=login_user,
            name='',
            status=None,
            tag_id=None,
            flow_type=None,
            page=1,
            page_size=10,
            managed=False,
            permission_id='view_app',
        )

    assert total == 1
    assert [one['id'] for one in data] == ['wf-1']


@pytest.mark.asyncio
async def test_get_all_flows_managed_listing_requires_edit_app_permission():
    workflow_module = _load_workflow_service_module()
    WorkFlowService = workflow_module.WorkFlowService

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['asst-1']),
        access_check=MagicMock(side_effect=AssertionError('legacy access_check should not drive write flag')),
    )

    app_rows = [
        {'id': 'asst-1', 'flow_type': FlowType.ASSISTANT.value, 'user_id': 10, 'logo': '', 'name': 'asst'},
    ]

    with patch.object(
        workflow_module.FlowDao,
        'aget_all_apps',
        new_callable=AsyncMock,
        return_value=(app_rows, 1),
    ), patch.object(
        workflow_module.ApplicationPermissionService,
        'get_app_permission_map_async',
        new_callable=AsyncMock,
        return_value={'asst-1': {'edit_app'}},
    ) as mock_permission_map, patch.object(
        WorkFlowService,
        'get_logo_share_link',
        return_value='logo-url',
        create=True,
    ):
        data, total = await WorkFlowService.get_all_flows(
            user=login_user,
            name='',
            status=None,
            tag_id=None,
            flow_type=FlowType.ASSISTANT.value,
            page=1,
            page_size=10,
            managed=True,
        )

    mock_permission_map.assert_awaited_once()
    assert total == 1
    assert [one['id'] for one in data] == ['asst-1']
    assert data[0]['write'] is True


@pytest.mark.asyncio
async def test_update_flow_status_uses_publish_and_unpublish_permissions():
    workflow_module = _load_workflow_service_module()
    WorkFlowService = workflow_module.WorkFlowService

    login_user = SimpleNamespace(user_id=7)
    db_flow = SimpleNamespace(id='wf-9', user_id=10, name='wf', status=0)
    version_info = SimpleNamespace(flow_id='wf-9')

    with patch.object(
        workflow_module.FlowDao,
        'aget_flow_by_id',
        new_callable=AsyncMock,
        return_value=db_flow,
        create=True,
    ), patch.object(
        workflow_module.ApplicationPermissionService,
        'has_any_permission_async',
        new_callable=AsyncMock,
        return_value=True,
        create=True,
    ) as mock_has_permission, patch.object(
        workflow_module.FlowVersionDao,
        'aget_version_by_id',
        new_callable=AsyncMock,
        return_value=version_info,
        create=True,
    ), patch.object(
        workflow_module.FlowDao,
        'aupdate_flow',
        new_callable=AsyncMock,
        create=True,
    ):
        await WorkFlowService.update_flow_status(login_user, 'wf-9', 1, 0)

    mock_has_permission.assert_awaited_once_with(
        login_user,
        'workflow',
        'wf-9',
        ['unpublish_app'],
    )


@pytest.mark.asyncio
async def test_get_frequently_used_flows_filters_by_use_app_permission_id():
    workflow_module = _load_workflow_service_module()
    WorkFlowService = workflow_module.WorkFlowService
    workflow_module.UserLinkType = SimpleNamespace(
        app=SimpleNamespace(value=[SimpleNamespace(value='app')]),
    )

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['asst-1']),
        get_merged_rebac_app_resource_ids=MagicMock(
            side_effect=AssertionError('sync helper should not be used in async flow lists'),
        ),
    )

    app_rows = [
        {'id': 'asst-1', 'flow_type': FlowType.ASSISTANT.value, 'user_id': 10, 'logo': '', 'name': 'asst'},
    ]

    with patch.object(
        workflow_module.UserLinkDao,
        'get_user_link',
        return_value=[SimpleNamespace(type_detail='asst-1')],
        create=True,
    ), patch.object(
        workflow_module.FlowDao,
        'get_all_apps',
        return_value=(app_rows, 1),
    ) as mock_get_all_apps, patch.object(
        WorkFlowService,
        'add_extra_field',
        return_value=app_rows,
        create=True,
    ), patch.object(
        WorkFlowService,
        'aenrich_apps_can_share',
        new_callable=AsyncMock,
        return_value=app_rows,
        create=True,
    ), patch.object(
        workflow_module.ApplicationPermissionService,
        'get_app_permission_map_async',
        new_callable=AsyncMock,
        return_value={'asst-1': {'use_app'}},
    ):
        data, total = await WorkFlowService.get_frequently_used_flows(login_user, 'app', 1, 8)

    login_user.aget_merged_rebac_app_resource_ids.assert_not_awaited()
    login_user.get_merged_rebac_app_resource_ids.assert_not_called()
    assert 'id_extra' not in mock_get_all_apps.call_args.kwargs
    assert total == 1
    assert data == app_rows


@pytest.mark.asyncio
async def test_get_uncategorized_flows_filters_by_use_app_permission_id():
    workflow_module = _load_workflow_service_module()
    WorkFlowService = workflow_module.WorkFlowService

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['wf-1']),
        get_merged_rebac_app_resource_ids=MagicMock(
            side_effect=AssertionError('sync helper should not be used in async flow lists'),
        ),
    )

    app_rows = [
        {'id': 'wf-1', 'flow_type': FlowType.WORKFLOW.value, 'user_id': 10, 'logo': '/logo.png', 'name': 'wf'},
    ]

    with patch.object(
        workflow_module.TagDao,
        'search_tags',
        return_value=[],
        create=True,
    ), patch.object(
        workflow_module.FlowDao,
        'get_all_apps',
        return_value=(app_rows, 1),
    ) as mock_get_all_apps, patch.object(
        WorkFlowService,
        'get_logo_share_link',
        return_value='logo-url',
        create=True,
    ), patch.object(
        WorkFlowService,
        'aenrich_apps_can_share',
        new_callable=AsyncMock,
        return_value=[{
            'id': 'wf-1',
            'flow_type': FlowType.WORKFLOW.value,
            'user_id': 10,
            'logo': 'logo-url',
            'name': 'wf',
        }],
        create=True,
    ), patch.object(
        workflow_module.ApplicationPermissionService,
        'get_app_permission_map_async',
        new_callable=AsyncMock,
        return_value={'wf-1': {'use_app'}},
    ):
        data, total = await WorkFlowService.get_uncategorized_flows(login_user, 1, 8, None)

    login_user.aget_merged_rebac_app_resource_ids.assert_not_awaited()
    login_user.get_merged_rebac_app_resource_ids.assert_not_called()
    assert mock_get_all_apps.call_args.args[4] is None
    assert mock_get_all_apps.call_args.args[5] is None
    assert total == 1
    assert data[0]['logo'] == 'logo-url'
