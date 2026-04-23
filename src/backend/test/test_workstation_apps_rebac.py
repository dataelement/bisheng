import importlib
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel
from bisheng.database.models.role_access import AccessType


def _install_apps_endpoint_stubs() -> None:
    if 'bisheng.workstation.api' not in sys.modules:
        workstation_api_module = ModuleType('bisheng.workstation.api')
        workstation_api_module.__path__ = []
        sys.modules['bisheng.workstation.api'] = workstation_api_module
    if 'bisheng.workstation.api.endpoints' not in sys.modules:
        workstation_api_endpoints_module = ModuleType('bisheng.workstation.api.endpoints')
        workstation_api_endpoints_module.__path__ = []
        sys.modules['bisheng.workstation.api.endpoints'] = workstation_api_endpoints_module

    if 'bisheng.api' not in sys.modules:
        api_module = ModuleType('bisheng.api')
        api_module.__path__ = []
        sys.modules['bisheng.api'] = api_module
    if 'bisheng.api.services' not in sys.modules:
        services_module = ModuleType('bisheng.api.services')
        services_module.__path__ = []
        sys.modules['bisheng.api.services'] = services_module
    if 'bisheng.api.services.workflow' not in sys.modules:
        workflow_module = ModuleType('bisheng.api.services.workflow')

        class _DummyWorkflowService:
            @staticmethod
            def add_extra_field(login_user, data, managed=False):
                return data

        workflow_module.WorkFlowService = _DummyWorkflowService
        sys.modules['bisheng.api.services.workflow'] = workflow_module

    if 'bisheng.api.v1.schemas' not in sys.modules:
        schemas_module = ModuleType('bisheng.api.v1.schemas')

        class _DummySchema(BaseModel):
            pass

        schemas_module.ChatList = _DummySchema
        schemas_module.FrequentlyUsedChat = _DummySchema
        schemas_module.UnifiedResponseModel = _DummySchema
        schemas_module.UsedAppPin = _DummySchema
        schemas_module.resp_200 = lambda data=None, message=None: {'data': data, 'message': message}
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

    if 'bisheng.common.errcode.http_error' not in sys.modules:
        http_error_module = ModuleType('bisheng.common.errcode.http_error')
        http_error_module.UnAuthorizedError = SimpleNamespace(return_resp=lambda: {'error': 'unauthorized'})
        sys.modules['bisheng.common.errcode.http_error'] = http_error_module

    if 'bisheng.common.errcode.workstation' not in sys.modules:
        workstation_error_module = ModuleType('bisheng.common.errcode.workstation')
        workstation_error_module.AgentAlreadyExistsError = SimpleNamespace(return_resp=lambda: {'error': 'exists'})
        workstation_error_module.UsedAppNotFoundError = lambda *args, **kwargs: Exception('not found')
        workstation_error_module.UsedAppNotOnlineError = lambda *args, **kwargs: Exception('offline')
        sys.modules['bisheng.common.errcode.workstation'] = workstation_error_module

    if 'bisheng.database.models.flow' not in sys.modules:
        flow_module = ModuleType('bisheng.database.models.flow')
        flow_module.FlowDao = SimpleNamespace(get_all_apps=lambda **kwargs: ([], 0), aget_all_apps=lambda **kwargs: ([], 0))
        flow_module.FlowStatus = SimpleNamespace(ONLINE=SimpleNamespace(value=2))
        flow_module.FlowType = SimpleNamespace(ASSISTANT=SimpleNamespace(value=5), WORKFLOW=SimpleNamespace(value=10))
        sys.modules['bisheng.database.models.flow'] = flow_module

    for mod_name, attrs in {
        'bisheng.database.models.message': {'ChatMessageDao': SimpleNamespace()},
        'bisheng.database.models.session': {'MessageSessionDao': SimpleNamespace()},
        'bisheng.database.models.tag': {'TagDao': SimpleNamespace()},
        'bisheng.database.models.user_link': {'UserLinkDao': SimpleNamespace()},
    }.items():
        if mod_name not in sys.modules:
            module = ModuleType(mod_name)
            for key, value in attrs.items():
                setattr(module, key, value)
            sys.modules[mod_name] = module

    if 'bisheng.workstation.api.dependencies' not in sys.modules:
        dependencies_module = ModuleType('bisheng.workstation.api.dependencies')
        dependencies_module.LoginUserDep = None
        sys.modules['bisheng.workstation.api.dependencies'] = dependencies_module

    if 'bisheng.workstation.domain.services.workstation_service' not in sys.modules:
        workstation_service_module = ModuleType('bisheng.workstation.domain.services.workstation_service')
        workstation_service_module.WorkStationService = SimpleNamespace(get_config=lambda: None)
        sys.modules['bisheng.workstation.domain.services.workstation_service'] = workstation_service_module

    if 'bisheng.workstation.domain.services.constants' not in sys.modules:
        constants_module = ModuleType('bisheng.workstation.domain.services.constants')
        constants_module.USED_APP_PIN_TYPE = 'used_app_pin'
        sys.modules['bisheng.workstation.domain.services.constants'] = constants_module


def _load_apps_endpoint_module():
    _install_apps_endpoint_stubs()
    module_name = 'bisheng.workstation.api.endpoints.apps'
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(
        module_name,
        '/Users/zhou/Code/bisheng/src/backend/bisheng/workstation/api/endpoints/apps.py',
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_get_recommended_apps_uses_supported_access_types_only():
    module = _load_apps_endpoint_module()
    login_user = MagicMock()
    login_user.is_admin.return_value = False
    login_user.user_id = 7
    login_user.get_user_access_resource_ids.return_value = ['wf-1', 'asst-1']

    config = SimpleNamespace(recommendedApps=['wf-1', 'asst-1'])

    with patch.object(module.WorkStationService, 'get_config', return_value=config), \
         patch.object(module.FlowDao, 'get_all_apps', return_value=([], 0)), \
         patch.object(module.WorkFlowService, 'add_extra_field', return_value=[]):
        module.get_recommended_apps(login_user=login_user)

    login_user.get_user_access_resource_ids.assert_called_once_with(
        [AccessType.WORKFLOW, AccessType.ASSISTANT_READ],
    )

@pytest.mark.asyncio
async def test_get_used_apps_uses_async_merged_rebac_helper():
    module = _load_apps_endpoint_module()
    login_user = MagicMock()
    login_user.is_admin.return_value = False
    login_user.user_id = 7
    login_user.aget_merged_rebac_app_resource_ids = AsyncMock(return_value=['wf-1', 'asst-1'])

    used_apps = [('wf-1', None)]

    with patch.object(module.MessageSessionDao, 'get_user_used_apps', new_callable=AsyncMock, return_value=used_apps, create=True), \
         patch.object(module.UserLinkDao, 'get_user_link', return_value=[], create=True), \
         patch.object(module.FlowDao, 'aget_all_apps', new_callable=AsyncMock, return_value=([], 0), create=True), \
         patch.object(module.TagDao, 'get_tags_by_resource', return_value={}, create=True):
        await module.get_used_apps(login_user=login_user, page=1, limit=20)

    login_user.aget_merged_rebac_app_resource_ids.assert_awaited_once_with(for_write=False)
