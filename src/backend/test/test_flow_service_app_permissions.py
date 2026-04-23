import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load_flow_service_module():
    service_dir = Path(__file__).resolve().parents[1] / 'bisheng' / 'api' / 'services'
    stubbed = [
        'bisheng.api',
        'bisheng.api.services',
        'bisheng.api.services.audit_log',
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
        'bisheng.database.models.session',
        'bisheng.database.models.user_group',
        'bisheng.permission.domain.services.application_permission_service',
        'bisheng.share_link.domain.models.share_link',
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

        audit_log_module = ModuleType('bisheng.api.services.audit_log')
        audit_log_module.AuditLogService = SimpleNamespace()
        sys.modules['bisheng.api.services.audit_log'] = audit_log_module

        schemas_module = ModuleType('bisheng.api.v1.schemas')

        class _DummyUnifiedResponseModel:
            def __class_getitem__(cls, item):
                return cls

        schemas_module.UnifiedResponseModel = _DummyUnifiedResponseModel
        schemas_module.resp_200 = lambda data=None, message=None: {'data': data, 'message': message}
        schemas_module.FlowVersionCreate = SimpleNamespace
        schemas_module.FlowCompareReq = SimpleNamespace
        schemas_module.resp_500 = lambda *args, **kwargs: {'error': '500'}
        schemas_module.StreamData = SimpleNamespace
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

        chat_utils_module = ModuleType('bisheng.common.chat.utils')
        chat_utils_module.process_node_data = lambda *args, **kwargs: None
        sys.modules['bisheng.common.chat.utils'] = chat_utils_module

        telemetry_module = ModuleType('bisheng.common.constants.enums.telemetry')
        telemetry_module.BaseTelemetryTypeEnum = SimpleNamespace(EDIT_APPLICATION='edit_application')
        sys.modules['bisheng.common.constants.enums.telemetry'] = telemetry_module

        user_deps_module = ModuleType('bisheng.common.dependencies.user_deps')
        user_deps_module.UserPayload = SimpleNamespace
        sys.modules['bisheng.common.dependencies.user_deps'] = user_deps_module

        flow_error_module = ModuleType('bisheng.common.errcode.flow')
        flow_error_module.NotFoundVersionError = SimpleNamespace(return_resp=lambda: {'error': 'not_found_version'})
        flow_error_module.CurVersionDelError = SimpleNamespace(return_resp=lambda: {'error': 'cur_version_del'})
        flow_error_module.VersionNameExistsError = SimpleNamespace(return_resp=lambda: {'error': 'version_name_exists'})
        flow_error_module.WorkFlowOnlineEditError = SimpleNamespace(return_resp=lambda: {'error': 'online_edit'})
        sys.modules['bisheng.common.errcode.flow'] = flow_error_module

        http_error_module = ModuleType('bisheng.common.errcode.http_error')

        class _DummyHttpError(Exception):
            @staticmethod
            def return_resp():
                raise AssertionError('unexpected http error path in test')

            @staticmethod
            def http_exception():
                return _DummyHttpError()

        http_error_module.NotFoundError = _DummyHttpError
        http_error_module.UnAuthorizedError = _DummyHttpError
        sys.modules['bisheng.common.errcode.http_error'] = http_error_module

        common_services_module = ModuleType('bisheng.common.services')
        common_services_module.telemetry_service = SimpleNamespace(log_event=AsyncMock(), log_event_sync=lambda *args, **kwargs: None)
        sys.modules['bisheng.common.services'] = common_services_module

        base_service_module = ModuleType('bisheng.common.services.base')
        base_service_module.BaseService = type('BaseService', (), {})
        sys.modules['bisheng.common.services.base'] = base_service_module

        logger_module = ModuleType('bisheng.core.logger')
        logger_module.trace_id_var = SimpleNamespace(get=lambda: 'trace')
        sys.modules['bisheng.core.logger'] = logger_module

        flow_model_module = ModuleType('bisheng.database.models.flow')
        flow_model_module.FlowDao = SimpleNamespace(aget_flow_by_id=AsyncMock(), get_flow_by_id=MagicMock())
        flow_model_module.FlowStatus = SimpleNamespace(ONLINE=SimpleNamespace(value=2))
        flow_model_module.Flow = SimpleNamespace
        flow_model_module.FlowType = SimpleNamespace(WORKFLOW=SimpleNamespace(value=10))
        sys.modules['bisheng.database.models.flow'] = flow_model_module

        flow_version_module = ModuleType('bisheng.database.models.flow_version')
        flow_version_module.FlowVersionDao = SimpleNamespace(get_version_by_id=lambda *args, **kwargs: None, aget_version_by_id=AsyncMock())
        flow_version_module.FlowVersionRead = SimpleNamespace
        flow_version_module.FlowVersion = SimpleNamespace
        sys.modules['bisheng.database.models.flow_version'] = flow_version_module

        group_resource_module = ModuleType('bisheng.database.models.group_resource')
        group_resource_module.GroupResourceDao = SimpleNamespace()
        group_resource_module.ResourceTypeEnum = SimpleNamespace()
        group_resource_module.GroupResource = SimpleNamespace
        sys.modules['bisheng.database.models.group_resource'] = group_resource_module

        role_access_module = ModuleType('bisheng.database.models.role_access')
        from bisheng.database.models.role_access import AccessType
        role_access_module.AccessType = AccessType
        sys.modules['bisheng.database.models.role_access'] = role_access_module

        session_module = ModuleType('bisheng.database.models.session')
        session_module.MessageSessionDao = SimpleNamespace(update_session_info_by_flow=lambda *args, **kwargs: None)
        sys.modules['bisheng.database.models.session'] = session_module

        user_group_module = ModuleType('bisheng.database.models.user_group')
        user_group_module.UserGroupDao = SimpleNamespace()
        sys.modules['bisheng.database.models.user_group'] = user_group_module

        app_permission_module = ModuleType('bisheng.permission.domain.services.application_permission_service')

        class _DummyApplicationPermissionService:
            @staticmethod
            async def has_any_permission_async(login_user, object_type, object_id, permission_ids):
                return True

            @staticmethod
            def has_any_permission_sync(login_user, object_type, object_id, permission_ids):
                return True

        app_permission_module.ApplicationPermissionService = _DummyApplicationPermissionService
        sys.modules['bisheng.permission.domain.services.application_permission_service'] = app_permission_module

        share_link_module = ModuleType('bisheng.share_link.domain.models.share_link')
        share_link_module.ShareLink = SimpleNamespace
        sys.modules['bisheng.share_link.domain.models.share_link'] = share_link_module

        utils_module = ModuleType('bisheng.utils')
        utils_module.get_request_ip = lambda request: '127.0.0.1'
        sys.modules['bisheng.utils'] = utils_module

        module_name = 'bisheng.api.services.flow'
        if module_name in sys.modules:
            sys.modules.pop(module_name)
        spec = importlib.util.spec_from_file_location(module_name, service_dir / 'flow.py')
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


def test_delete_version_requires_edit_app_permission():
    flow_module = _load_flow_service_module()
    FlowService = flow_module.FlowService
    login_user = SimpleNamespace(user_id=7)
    version_info = SimpleNamespace(flow_id='wf-1', is_current=0)
    flow_info = SimpleNamespace(id='wf-1', user_id=9, flow_type=10)

    with patch.object(
        flow_module.FlowVersionDao,
        'get_version_by_id',
        return_value=version_info,
    ), patch.object(
        flow_module.FlowDao,
        'get_flow_by_id',
        return_value=flow_info,
    ), patch.object(
        flow_module.ApplicationPermissionService,
        'has_any_permission_sync',
        return_value=True,
        create=True,
    ) as mock_has_permission, patch.object(
        flow_module.FlowVersionDao,
        'delete_flow_version',
        create=True,
    ):
        FlowService.delete_version(login_user, 1)

    mock_has_permission.assert_called_once_with(
        login_user,
        'workflow',
        'wf-1',
        ['edit_app'],
    )


@pytest.mark.asyncio
async def test_get_one_flow_uses_view_or_use_app_permissions():
    flow_module = _load_flow_service_module()
    FlowService = flow_module.FlowService
    login_user = SimpleNamespace(user_id=7)
    flow_info = SimpleNamespace(id='wf-2', user_id=10, flow_type=10, logo='')

    with patch.object(
        flow_module.FlowDao,
        'aget_flow_by_id',
        new_callable=AsyncMock,
        return_value=flow_info,
    ), patch.object(
        flow_module.ApplicationPermissionService,
        'has_any_permission_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_has_permission, patch.object(
        FlowService,
        'get_logo_share_link_async',
        new_callable=AsyncMock,
        return_value='logo-url',
        create=True,
    ):
        await FlowService.get_one_flow(login_user, 'wf-2')

    mock_has_permission.assert_awaited_once_with(
        login_user,
        'workflow',
        'wf-2',
        ['view_app', 'use_app'],
    )
