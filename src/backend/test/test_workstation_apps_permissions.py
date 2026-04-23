from datetime import datetime
import importlib
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from bisheng.database.models.flow import FlowType
def _load_apps_module():
    api_dir = Path(__file__).resolve().parents[1] / 'bisheng' / 'workstation' / 'api'
    endpoints_dir = api_dir / 'endpoints'
    stubbed_module_names = [
        'bisheng.workstation.api',
        'bisheng.workstation.api.endpoints',
        'bisheng.api.services.workflow',
        'bisheng.api.v1.schemas',
        'bisheng.common.errcode.http_error',
        'bisheng.common.errcode.workstation',
        'bisheng.workstation.api.dependencies',
        'bisheng.workstation.domain.services.workstation_service',
        'bisheng.workstation.domain.services.constants',
    ]
    original_modules = {name: sys.modules.get(name) for name in stubbed_module_names}

    try:
        api_package = ModuleType('bisheng.workstation.api')
        api_package.__path__ = [str(api_dir)]
        sys.modules['bisheng.workstation.api'] = api_package

        endpoints_package = ModuleType('bisheng.workstation.api.endpoints')
        endpoints_package.__path__ = [str(endpoints_dir)]
        sys.modules['bisheng.workstation.api.endpoints'] = endpoints_package

        workflow_module = ModuleType('bisheng.api.services.workflow')

        class _DummyWorkFlowService:
            @staticmethod
            def add_extra_field(user, data, managed=False):
                return data

            @staticmethod
            def get_logo_share_link(logo):
                return logo

            @staticmethod
            async def aenrich_apps_can_share(user, data, managed=False):
                return data

        workflow_module.WorkFlowService = _DummyWorkFlowService
        sys.modules['bisheng.api.services.workflow'] = workflow_module

        schemas_module = ModuleType('bisheng.api.v1.schemas')
        from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

        class _DummySchema(BaseModel):
            pass

        schemas_module.ChatList = _DummySchema
        schemas_module.FrequentlyUsedChat = _DummySchema
        schemas_module.FileChunk = _DummySchema
        schemas_module.FileProcessBase = _DummySchema
        schemas_module.KnowledgeFileOne = _DummySchema
        schemas_module.KnowledgeFileProcess = _DummySchema
        schemas_module.UnifiedResponseModel = UnifiedResponseModel
        schemas_module.UpdatePreviewFileChunk = _DummySchema
        schemas_module.UsedAppPin = _DummySchema
        schemas_module.ExcelRule = _DummySchema
        schemas_module.KnowledgeFileReProcess = _DummySchema
        schemas_module.resp_200 = resp_200
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

        http_error_module = ModuleType('bisheng.common.errcode.http_error')

        class _DummyUnauthorizedError:
            @staticmethod
            def return_resp():
                raise AssertionError('unexpected unauthorized response path in test')

        class _DummyHttpError(Exception):
            @staticmethod
            def return_resp():
                raise AssertionError('unexpected http error response path in test')

        http_error_module.NotFoundError = _DummyHttpError
        http_error_module.ServerError = _DummyHttpError
        http_error_module.UnAuthorizedError = _DummyUnauthorizedError
        sys.modules['bisheng.common.errcode.http_error'] = http_error_module

        workstation_error_module = ModuleType('bisheng.common.errcode.workstation')

        class _DummyError(Exception):
            @staticmethod
            def return_resp():
                raise AssertionError('unexpected workstation error response path in test')

        workstation_error_module.AgentAlreadyExistsError = _DummyError
        workstation_error_module.UsedAppNotFoundError = _DummyError
        workstation_error_module.UsedAppNotOnlineError = _DummyError
        sys.modules['bisheng.common.errcode.workstation'] = workstation_error_module

        dependencies_module = ModuleType('bisheng.workstation.api.dependencies')
        dependencies_module.LoginUserDep = None
        sys.modules['bisheng.workstation.api.dependencies'] = dependencies_module

        workstation_service_module = ModuleType('bisheng.workstation.domain.services.workstation_service')

        class _DummyWorkStationService:
            @staticmethod
            def get_config():
                return None

        workstation_service_module.WorkStationService = _DummyWorkStationService
        sys.modules['bisheng.workstation.domain.services.workstation_service'] = workstation_service_module

        constants_module = ModuleType('bisheng.workstation.domain.services.constants')
        constants_module.USED_APP_PIN_TYPE = 'used_app_pin'
        sys.modules['bisheng.workstation.domain.services.constants'] = constants_module

        sys.modules.pop('bisheng.workstation.api.endpoints.apps', None)
        return importlib.import_module('bisheng.workstation.api.endpoints.apps')
    finally:
        for name, module in original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@pytest.mark.asyncio
async def test_recommended_apps_uses_async_merged_rebac_helper():
    apps_endpoints = _load_apps_module()

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['wf-1']),
    )

    with patch.object(
        apps_endpoints.WorkStationService,
        'get_config',
        return_value=SimpleNamespace(recommendedApps=['wf-1']),
    ), patch.object(
        apps_endpoints.FlowDao,
        'get_all_apps',
        return_value=([{'id': 'wf-1'}], 1),
    ) as mock_get_all_apps, patch.object(
        apps_endpoints.WorkFlowService,
        'add_extra_field',
        return_value=[{'id': 'wf-1'}],
    ):
        result = await apps_endpoints.get_recommended_apps(login_user=login_user)

    login_user.aget_merged_rebac_app_resource_ids.assert_awaited_once_with(
        for_write=False
    )
    assert mock_get_all_apps.call_args.kwargs['id_extra'] == ['wf-1']
    assert result.data == [{'id': 'wf-1'}]


@pytest.mark.asyncio
async def test_used_apps_awaits_async_app_visibility_helper():
    apps_endpoints = _load_apps_module()

    last_used_at = datetime(2026, 4, 23, 14, 30, 0)
    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_merged_rebac_app_resource_ids=AsyncMock(return_value=['asst-1']),
        get_merged_rebac_app_resource_ids=MagicMock(
            side_effect=AssertionError('sync app visibility helper should not be used here'),
        ),
    )

    app_row = {
        'id': 'asst-1',
        'flow_type': FlowType.ASSISTANT.value,
        'logo': '/logo.png',
        'user_id': 9,
        'name': 'assistant',
    }

    with patch.object(
        apps_endpoints.MessageSessionDao,
        'get_user_used_apps',
        new_callable=AsyncMock,
        return_value=[('asst-1', last_used_at)],
        create=True,
    ), patch.object(
        apps_endpoints.UserLinkDao,
        'get_user_link',
        return_value=[],
        create=True,
    ), patch.object(
        apps_endpoints.FlowDao,
        'aget_all_apps',
        new_callable=AsyncMock,
        return_value=([app_row], 1),
    ) as mock_aget_all_apps, patch.object(
        apps_endpoints.TagDao,
        'get_tags_by_resource',
        return_value={},
        create=True,
    ), patch.object(
        apps_endpoints.WorkFlowService,
        'get_logo_share_link',
        return_value='logo-url',
    ), patch.object(
        apps_endpoints,
        'batch_user_may_share_app',
        new_callable=AsyncMock,
        return_value=[False],
    ):
        result = await apps_endpoints.get_used_apps(login_user=login_user)

    login_user.aget_merged_rebac_app_resource_ids.assert_awaited_once_with(for_write=False)
    login_user.get_merged_rebac_app_resource_ids.assert_not_called()
    assert mock_aget_all_apps.await_args.kwargs['id_extra'] == ['asst-1']
    assert result.data == {
        'list': [{
            'id': 'asst-1',
            'flow_type': FlowType.ASSISTANT.value,
            'logo': 'logo-url',
            'user_id': 9,
            'name': 'assistant',
            'is_pinned': False,
            'last_used_time': last_used_at,
            'tags': [],
            'can_share': False,
        }],
        'total': 1,
    }
