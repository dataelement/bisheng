import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load_assistant_service_module():
    service_dir = Path(__file__).resolve().parents[1] / 'bisheng' / 'api' / 'services'
    stubbed = [
        'bisheng.api',
        'bisheng.api.services',
        'bisheng.api.services.assistant_agent',
        'bisheng.api.services.assistant_base',
        'bisheng.api.services.audit_log',
        'bisheng.api.v1.schemas',
        'bisheng.common.constants.enums.telemetry',
        'bisheng.common.dependencies.user_deps',
        'bisheng.common.errcode.assistant',
        'bisheng.common.errcode.http_error',
        'bisheng.common.schemas.telemetry.event_data_schema',
        'bisheng.common.services',
        'bisheng.common.services.base',
        'bisheng.core.cache',
        'bisheng.core.logger',
        'bisheng.database.models.assistant',
        'bisheng.database.models.flow',
        'bisheng.database.models.group_resource',
        'bisheng.database.models.role_access',
        'bisheng.database.models.session',
        'bisheng.database.models.tag',
        'bisheng.knowledge.domain.models.knowledge',
        'bisheng.llm.domain.services',
        'bisheng.permission.domain.services.application_permission_service',
        'bisheng.share_link.domain.models.share_link',
        'bisheng.tool.domain.models.gpts_tools',
        'bisheng.user.domain.models.user',
        'bisheng.utils',
    ]
    original = {name: sys.modules.get(name) for name in stubbed}

    try:
        api_package = ModuleType('bisheng.api')
        api_package.__path__ = [str(service_dir.parent)]
        sys.modules['bisheng.api'] = api_package

        services_package = ModuleType('bisheng.api.services')
        services_package.__path__ = [str(service_dir)]
        sys.modules['bisheng.api.services'] = services_package

        assistant_agent_module = ModuleType('bisheng.api.services.assistant_agent')
        assistant_agent_module.AssistantAgent = SimpleNamespace
        sys.modules['bisheng.api.services.assistant_agent'] = assistant_agent_module

        assistant_base_module = ModuleType('bisheng.api.services.assistant_base')
        assistant_base_module.AssistantUtils = type('AssistantUtils', (), {})
        sys.modules['bisheng.api.services.assistant_base'] = assistant_base_module

        audit_log_module = ModuleType('bisheng.api.services.audit_log')
        audit_log_module.AuditLogService = SimpleNamespace(
            create_build_assistant=lambda *args, **kwargs: None,
            delete_build_assistant=lambda *args, **kwargs: None,
            update_build_assistant=lambda *args, **kwargs: None,
        )
        sys.modules['bisheng.api.services.audit_log'] = audit_log_module

        schemas_module = ModuleType('bisheng.api.v1.schemas')

        class _DummySchema:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        schemas_module.AssistantInfo = _DummySchema
        schemas_module.AssistantSimpleInfo = _DummySchema
        schemas_module.AssistantUpdateReq = _DummySchema
        schemas_module.StreamData = _DummySchema
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

        telemetry_module = ModuleType('bisheng.common.constants.enums.telemetry')
        telemetry_module.BaseTelemetryTypeEnum = SimpleNamespace(NEW_APPLICATION='new_app', DELETE_APPLICATION='delete_app', EDIT_APPLICATION='edit_application')
        telemetry_module.ApplicationTypeEnum = SimpleNamespace(ASSISTANT='assistant')
        sys.modules['bisheng.common.constants.enums.telemetry'] = telemetry_module

        user_deps_module = ModuleType('bisheng.common.dependencies.user_deps')
        user_deps_module.UserPayload = SimpleNamespace
        sys.modules['bisheng.common.dependencies.user_deps'] = user_deps_module

        assistant_error_module = ModuleType('bisheng.common.errcode.assistant')
        assistant_error_module.AssistantInitError = Exception
        assistant_error_module.AssistantNameRepeatError = Exception
        assistant_error_module.AssistantNotEditError = Exception
        assistant_error_module.AssistantNotExistsError = Exception
        sys.modules['bisheng.common.errcode.assistant'] = assistant_error_module

        http_error_module = ModuleType('bisheng.common.errcode.http_error')
        http_error_module.UnAuthorizedError = Exception
        sys.modules['bisheng.common.errcode.http_error'] = http_error_module

        event_schema_module = ModuleType('bisheng.common.schemas.telemetry.event_data_schema')
        event_schema_module.NewApplicationEventData = SimpleNamespace
        sys.modules['bisheng.common.schemas.telemetry.event_data_schema'] = event_schema_module

        common_services_module = ModuleType('bisheng.common.services')
        common_services_module.telemetry_service = SimpleNamespace(log_event=AsyncMock(), log_event_sync=lambda *args, **kwargs: None)
        sys.modules['bisheng.common.services'] = common_services_module

        base_service_module = ModuleType('bisheng.common.services.base')
        base_service_module.BaseService = type('BaseService', (), {})
        sys.modules['bisheng.common.services.base'] = base_service_module

        cache_module = ModuleType('bisheng.core.cache')
        cache_module.InMemoryCache = lambda: SimpleNamespace(get=lambda *args, **kwargs: None, set=lambda *args, **kwargs: None)
        sys.modules['bisheng.core.cache'] = cache_module

        logger_module = ModuleType('bisheng.core.logger')
        logger_module.trace_id_var = SimpleNamespace(get=lambda: 'trace')
        sys.modules['bisheng.core.logger'] = logger_module

        assistant_model_module = ModuleType('bisheng.database.models.assistant')
        assistant_model_module.Assistant = SimpleNamespace
        assistant_model_module.AssistantDao = SimpleNamespace(
            get_all_assistants=lambda *args, **kwargs: ([], 0),
            get_assistants=lambda *args, **kwargs: ([], 0),
            aget_one_assistant=AsyncMock(),
        )
        assistant_model_module.AssistantLinkDao = SimpleNamespace(get_assistant_link=AsyncMock(return_value=[]))
        assistant_model_module.AssistantStatus = SimpleNamespace(ONLINE=SimpleNamespace(value=1))
        sys.modules['bisheng.database.models.assistant'] = assistant_model_module

        flow_module = ModuleType('bisheng.database.models.flow')
        flow_module.Flow = SimpleNamespace
        flow_module.FlowDao = SimpleNamespace(get_flow_by_ids=lambda ids: [])
        flow_module.FlowType = SimpleNamespace(ASSISTANT=SimpleNamespace(value=5), WORKFLOW=SimpleNamespace(value=10))
        sys.modules['bisheng.database.models.flow'] = flow_module

        group_resource_module = ModuleType('bisheng.database.models.group_resource')
        group_resource_module.ResourceTypeEnum = SimpleNamespace(ASSISTANT='assistant')
        sys.modules['bisheng.database.models.group_resource'] = group_resource_module

        role_access_module = ModuleType('bisheng.database.models.role_access')
        from bisheng.database.models.role_access import AccessType
        role_access_module.AccessType = AccessType
        sys.modules['bisheng.database.models.role_access'] = role_access_module

        session_module = ModuleType('bisheng.database.models.session')
        session_module.MessageSessionDao = SimpleNamespace(update_session_info_by_flow=lambda *args, **kwargs: None)
        sys.modules['bisheng.database.models.session'] = session_module

        tag_module = ModuleType('bisheng.database.models.tag')
        tag_module.TagDao = SimpleNamespace(
            get_resources_by_tags=lambda *args, **kwargs: [],
            get_tags_by_resource=lambda *args, **kwargs: {},
        )
        sys.modules['bisheng.database.models.tag'] = tag_module

        knowledge_module = ModuleType('bisheng.knowledge.domain.models.knowledge')
        knowledge_module.KnowledgeDao = SimpleNamespace(get_list_by_ids=lambda ids: [])
        sys.modules['bisheng.knowledge.domain.models.knowledge'] = knowledge_module

        llm_services_module = ModuleType('bisheng.llm.domain.services')
        llm_services_module.LLMService = SimpleNamespace(get_assistant_llm=AsyncMock())
        sys.modules['bisheng.llm.domain.services'] = llm_services_module

        app_permission_module = ModuleType('bisheng.permission.domain.services.application_permission_service')

        class _DummyApplicationPermissionService:
            @staticmethod
            def filter_object_ids_by_permission_sync(login_user, object_type, object_ids, permission_id):
                return object_ids

            @staticmethod
            async def has_any_permission_async(login_user, object_type, object_id, permission_ids):
                return True

        app_permission_module.ApplicationPermissionService = _DummyApplicationPermissionService
        sys.modules['bisheng.permission.domain.services.application_permission_service'] = app_permission_module

        share_link_module = ModuleType('bisheng.share_link.domain.models.share_link')
        share_link_module.ShareLink = SimpleNamespace
        sys.modules['bisheng.share_link.domain.models.share_link'] = share_link_module

        tool_module = ModuleType('bisheng.tool.domain.models.gpts_tools')
        tool_module.GptsToolsDao = SimpleNamespace(get_list_by_ids=lambda ids: [])
        tool_module.GptsTools = SimpleNamespace
        sys.modules['bisheng.tool.domain.models.gpts_tools'] = tool_module

        user_module = ModuleType('bisheng.user.domain.models.user')
        user_module.UserDao = SimpleNamespace(get_user_by_ids=lambda ids: [], get_user=lambda user_id: None)
        sys.modules['bisheng.user.domain.models.user'] = user_module

        utils_module = ModuleType('bisheng.utils')
        utils_module.get_request_ip = lambda request: '127.0.0.1'
        sys.modules['bisheng.utils'] = utils_module

        module_name = 'bisheng.api.services.assistant'
        if module_name in sys.modules:
            sys.modules.pop(module_name)
        spec = importlib.util.spec_from_file_location(module_name, service_dir / 'assistant.py')
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


def test_get_assistant_filters_by_use_app_and_sets_write_from_edit_app():
    assistant_module = _load_assistant_service_module()
    AssistantService = assistant_module.AssistantService

    user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        get_user_access_resource_ids=MagicMock(return_value=['asst-1', 'asst-2']),
    )

    assistant_one = SimpleNamespace(id='asst-1', user_id=9, logo='', model_dump=lambda include=None: {'id': 'asst-1'})
    assistant_two = SimpleNamespace(id='asst-2', user_id=10, logo='', model_dump=lambda include=None: {'id': 'asst-2'})

    with patch.object(
        assistant_module.ApplicationPermissionService,
        'filter_object_ids_by_permission_sync',
        side_effect=[['asst-2'], ['asst-2']],
    ) as mock_filter_ids, patch.object(
        assistant_module.AssistantDao,
        'get_assistants',
        return_value=([assistant_one, assistant_two], 2),
    ), patch.object(
        AssistantService,
        'return_simple_assistant_info',
        side_effect=[SimpleNamespace(id='asst-1'), SimpleNamespace(id='asst-2')],
    ), patch.object(
        AssistantService,
        'get_logo_share_link',
        return_value='logo-url',
        create=True,
    ):
        data, total = AssistantService.get_assistant(user, page=1, limit=20)

    assert total == 2
    assert [item.id for item in data] == ['asst-1', 'asst-2']
    assert getattr(data[0], 'write', False) is False
    assert data[1].write is True
    assert mock_filter_ids.call_args_list[0].args[3] == 'use_app'
    assert mock_filter_ids.call_args_list[1].args[3] == 'edit_app'


@pytest.mark.asyncio
async def test_get_assistant_info_uses_view_or_use_app_permissions():
    assistant_module = _load_assistant_service_module()
    AssistantService = assistant_module.AssistantService

    login_user = SimpleNamespace(user_id=7)
    assistant = SimpleNamespace(id='asst-1', is_delete=False, logo='', model_dump=lambda: {'id': 'asst-1'})

    with patch.object(
        assistant_module.AssistantDao,
        'aget_one_assistant',
        new_callable=AsyncMock,
        return_value=assistant,
    ), patch.object(
        assistant_module.ApplicationPermissionService,
        'has_any_permission_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_has_permission, patch.object(
        assistant_module.AssistantLinkDao,
        'get_assistant_link',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        AssistantService,
        'get_logo_share_link_async',
        new_callable=AsyncMock,
        return_value='logo-url',
        create=True,
    ):
        await AssistantService.get_assistant_info('asst-1', login_user)

    mock_has_permission.assert_awaited_once_with(
        login_user,
        'assistant',
        'asst-1',
        ['view_app', 'use_app'],
    )
