import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict

from bisheng.database.models.role_access import AccessType


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
        'bisheng.common.schemas.telemetry.event_data_schema',
        'bisheng.common.errcode.assistant',
        'bisheng.common.errcode.http_error',
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

        class _DummyAssistantUtils:
            pass

        assistant_base_module.AssistantUtils = _DummyAssistantUtils
        sys.modules['bisheng.api.services.assistant_base'] = assistant_base_module

        audit_log_module = ModuleType('bisheng.api.services.audit_log')
        audit_log_module.AuditLogService = SimpleNamespace()
        sys.modules['bisheng.api.services.audit_log'] = audit_log_module

        schemas_module = ModuleType('bisheng.api.v1.schemas')

        class _DummySchema(BaseModel):
            model_config = ConfigDict(extra='allow')

        schemas_module.AssistantInfo = _DummySchema
        schemas_module.AssistantSimpleInfo = _DummySchema
        schemas_module.AssistantUpdateReq = _DummySchema
        schemas_module.StreamData = _DummySchema
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

        telemetry_module = ModuleType('bisheng.common.constants.enums.telemetry')
        telemetry_module.BaseTelemetryTypeEnum = SimpleNamespace(
            NEW_APPLICATION='new_application',
            EDIT_APPLICATION='edit_application',
            DELETE_APPLICATION='delete_application',
        )
        telemetry_module.ApplicationTypeEnum = SimpleNamespace(ASSISTANT='assistant')
        sys.modules['bisheng.common.constants.enums.telemetry'] = telemetry_module

        user_deps_module = ModuleType('bisheng.common.dependencies.user_deps')
        user_deps_module.UserPayload = SimpleNamespace
        sys.modules['bisheng.common.dependencies.user_deps'] = user_deps_module

        event_data_module = ModuleType('bisheng.common.schemas.telemetry.event_data_schema')
        event_data_module.NewApplicationEventData = _DummySchema
        sys.modules['bisheng.common.schemas.telemetry.event_data_schema'] = event_data_module

        assistant_error_module = ModuleType('bisheng.common.errcode.assistant')
        assistant_error_module.AssistantInitError = Exception
        assistant_error_module.AssistantNameRepeatError = Exception
        assistant_error_module.AssistantNotEditError = Exception
        assistant_error_module.AssistantNotExistsError = Exception
        sys.modules['bisheng.common.errcode.assistant'] = assistant_error_module

        http_error_module = ModuleType('bisheng.common.errcode.http_error')
        http_error_module.UnAuthorizedError = Exception
        sys.modules['bisheng.common.errcode.http_error'] = http_error_module

        common_services_module = ModuleType('bisheng.common.services')
        common_services_module.telemetry_service = SimpleNamespace(
            log_event=AsyncMock(),
            log_event_sync=MagicMock(),
        )
        sys.modules['bisheng.common.services'] = common_services_module

        base_service_module = ModuleType('bisheng.common.services.base')

        class _DummyBaseService:
            @classmethod
            def get_logo_share_link(cls, logo):
                return logo

            @classmethod
            async def get_logo_share_link_async(cls, logo):
                return logo

        base_service_module.BaseService = _DummyBaseService
        sys.modules['bisheng.common.services.base'] = base_service_module

        cache_module = ModuleType('bisheng.core.cache')

        class _DummyCache:
            def __init__(self):
                self._data = {}

            def get(self, key):
                return self._data.get(key)

            def set(self, key, value):
                self._data[key] = value

        cache_module.InMemoryCache = _DummyCache
        sys.modules['bisheng.core.cache'] = cache_module

        logger_module = ModuleType('bisheng.core.logger')
        logger_module.trace_id_var = SimpleNamespace(get=lambda: 'trace')
        sys.modules['bisheng.core.logger'] = logger_module

        assistant_module = ModuleType('bisheng.database.models.assistant')
        assistant_module.Assistant = SimpleNamespace
        assistant_module.AssistantDao = SimpleNamespace(
            get_all_assistants=MagicMock(),
            get_assistants=MagicMock(),
            aget_one_assistant=AsyncMock(),
            get_one_assistant=MagicMock(),
            create_assistant=MagicMock(),
            update_assistant=MagicMock(),
            delete_assistant=MagicMock(),
            get_assistant_by_name_user_id=MagicMock(return_value=None),
        )
        assistant_module.AssistantLinkDao = SimpleNamespace(
            get_assistant_link=AsyncMock(return_value=[]),
            update_assistant_tool=MagicMock(),
            update_assistant_flow=MagicMock(),
            update_assistant_knowledge=MagicMock(),
        )
        assistant_module.AssistantStatus = SimpleNamespace(ONLINE=SimpleNamespace(value=1))
        sys.modules['bisheng.database.models.assistant'] = assistant_module

        flow_module = ModuleType('bisheng.database.models.flow')
        flow_module.Flow = SimpleNamespace
        flow_module.FlowDao = SimpleNamespace(get_flow_by_ids=lambda ids: [])
        flow_module.FlowType = SimpleNamespace(
            ASSISTANT=SimpleNamespace(value=5),
            WORKFLOW=SimpleNamespace(value=10),
        )
        sys.modules['bisheng.database.models.flow'] = flow_module

        group_resource_module = ModuleType('bisheng.database.models.group_resource')
        group_resource_module.ResourceTypeEnum = SimpleNamespace(ASSISTANT='assistant')
        sys.modules['bisheng.database.models.group_resource'] = group_resource_module

        role_access_module = ModuleType('bisheng.database.models.role_access')
        role_access_module.AccessType = AccessType
        sys.modules['bisheng.database.models.role_access'] = role_access_module

        session_module = ModuleType('bisheng.database.models.session')
        session_module.MessageSessionDao = SimpleNamespace(update_session_info_by_flow=MagicMock())
        sys.modules['bisheng.database.models.session'] = session_module

        tag_module = ModuleType('bisheng.database.models.tag')
        tag_module.TagDao = SimpleNamespace(get_tags_by_resource=lambda *args, **kwargs: {})
        sys.modules['bisheng.database.models.tag'] = tag_module

        knowledge_module = ModuleType('bisheng.knowledge.domain.models.knowledge')
        knowledge_module.KnowledgeDao = SimpleNamespace(get_list_by_ids=lambda ids: [])
        sys.modules['bisheng.knowledge.domain.models.knowledge'] = knowledge_module

        llm_module = ModuleType('bisheng.llm.domain.services')
        llm_module.LLMService = SimpleNamespace(get_assistant_llm=AsyncMock(return_value=SimpleNamespace(llm_list=[])))
        sys.modules['bisheng.llm.domain.services'] = llm_module

        app_permission_module = ModuleType('bisheng.permission.domain.services.application_permission_service')

        class _DummyApplicationPermissionService:
            @staticmethod
            async def get_app_permission_map_async(login_user, rows, permission_ids):
                return {}

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

        gpts_module = ModuleType('bisheng.tool.domain.models.gpts_tools')
        gpts_module.GptsToolsDao = SimpleNamespace(get_list_by_ids=lambda ids: [])
        gpts_module.GptsTools = SimpleNamespace
        sys.modules['bisheng.tool.domain.models.gpts_tools'] = gpts_module

        user_module = ModuleType('bisheng.user.domain.models.user')
        user_module.UserDao = SimpleNamespace(get_user=lambda user_id: SimpleNamespace(user_name=f'user-{user_id}'))
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


def _assistant_row(*, assistant_id: str, owner_user_id: int):
    row = SimpleNamespace(
        id=assistant_id,
        name='assistant',
        desc='desc',
        logo='/logo.png',
        status=1,
        user_id=owner_user_id,
        is_delete=0,
        create_time=None,
        update_time=None,
    )

    def _model_dump(**kwargs):
        return {
            'id': row.id,
            'name': row.name,
            'desc': row.desc,
            'logo': row.logo,
            'status': row.status,
            'user_id': row.user_id,
            'create_time': row.create_time,
            'update_time': row.update_time,
        }

    row.model_dump = _model_dump
    return row


def test_get_assistant_uses_rebac_accessible_ids_for_independent_list():
    module = _load_assistant_service_module()
    AssistantService = module.AssistantService

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        get_user_access_resource_ids=MagicMock(return_value=['asst-1']),
    )
    assistant = _assistant_row(assistant_id='asst-1', owner_user_id=99)

    with patch.object(
        module.AssistantDao,
        'get_assistants',
        return_value=([assistant], 1),
    ), patch.object(
        module.ApplicationPermissionService,
        'filter_object_ids_by_permission_sync',
        side_effect=lambda login_user, object_type, object_ids, permission_id: (
            object_ids if permission_id == 'use_app' else []
        ),
    ) as mock_filter_ids, patch.object(
        module.TagDao,
        'get_tags_by_resource',
        return_value={'asst-1': ['tag-a']},
    ), patch.object(
        AssistantService,
        'get_logo_share_link',
        return_value='logo-url',
    ), patch.object(
        AssistantService,
        'get_user_name',
        return_value='owner-name',
    ):
        data, total = AssistantService.get_assistant(
            login_user,
            name='',
            status=None,
            tag_id=None,
            page=1,
            limit=20,
        )

    login_user.get_user_access_resource_ids.assert_called_once_with([AccessType.ASSISTANT_READ])
    assert [call.args[3] for call in mock_filter_ids.call_args_list] == ['use_app', 'edit_app']
    assert total == 1
    assert len(data) == 1
    assert data[0].id == 'asst-1'
    assert data[0].user_name == 'owner-name'
    assert data[0].tags == ['tag-a']
    assert data[0].write is False


@pytest.mark.asyncio
async def test_get_assistant_info_checks_assistant_read_permission():
    module = _load_assistant_service_module()
    AssistantService = module.AssistantService

    login_user = SimpleNamespace(
        user_id=7,
        async_access_check=AsyncMock(return_value=True),
    )
    assistant = _assistant_row(assistant_id='asst-1', owner_user_id=99)

    with patch.object(
        module.AssistantDao,
        'aget_one_assistant',
        new_callable=AsyncMock,
        return_value=assistant,
    ), patch.object(
        module.ApplicationPermissionService,
        'has_any_permission_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_has_permission, patch.object(
        module,
        'UnAuthorizedError',
        Exception,
    ), patch.object(
        module.AssistantLinkDao,
        'get_assistant_link',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        AssistantService,
        'get_logo_share_link_async',
        new_callable=AsyncMock,
        return_value='logo-url',
    ):
        result = await AssistantService.get_assistant_info('asst-1', login_user, None)

    mock_has_permission.assert_awaited_once_with(
        login_user,
        'assistant',
        'asst-1',
        ['view_app', 'use_app'],
    )
    assert result.id == 'asst-1'
    assert result.logo == 'logo-url'
