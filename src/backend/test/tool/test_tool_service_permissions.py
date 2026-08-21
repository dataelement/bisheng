import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load_tool_service_module():
    service_dir = Path(__file__).resolve().parents[2] / 'bisheng' / 'tool' / 'domain' / 'services'
    stubbed = [
        'bisheng.api.services.audit_log',
        'bisheng.api.utils',
        'bisheng.common.dependencies.user_deps',
        'bisheng.common.errcode',
        'bisheng.common.errcode.http_error',
        'bisheng.common.errcode.tool',
        'bisheng.common.services.config_service',
        'bisheng.database.models.group_resource',
        'bisheng.database.models.role_access',
        'bisheng.mcp_manage.constant',
        'bisheng.mcp_manage.manager',
        'bisheng.permission.domain.services.tool_permission_service',
        "bisheng.permission.domain.tool_permission_template",
        'bisheng.tool.domain.const',
        'bisheng.tool.domain.langchain.linsight_knowledge',
        'bisheng.tool.domain.models.gpts_tools',
        'bisheng.tool.domain.services.openapi',
        'bisheng.utils',
        'bisheng.utils.mask_data',
        'bisheng_langchain.gpts.load_tools',
    ]
    original = {name: sys.modules.get(name) for name in stubbed}

    try:
        audit_log_module = ModuleType('bisheng.api.services.audit_log')
        audit_log_module.AuditLogService = SimpleNamespace()
        sys.modules['bisheng.api.services.audit_log'] = audit_log_module

        api_utils_module = ModuleType('bisheng.api.utils')
        api_utils_module.get_url_content = AsyncMock()
        sys.modules['bisheng.api.utils'] = api_utils_module

        user_deps_module = ModuleType('bisheng.common.dependencies.user_deps')
        user_deps_module.UserPayload = SimpleNamespace
        sys.modules['bisheng.common.dependencies.user_deps'] = user_deps_module

        errcode_module = ModuleType('bisheng.common.errcode')
        errcode_module.BaseErrorCode = Exception
        sys.modules['bisheng.common.errcode'] = errcode_module

        http_error_module = ModuleType('bisheng.common.errcode.http_error')
        http_error_module.UnAuthorizedError = Exception
        http_error_module.NotFoundError = Exception
        sys.modules['bisheng.common.errcode.http_error'] = http_error_module

        tool_error_module = ModuleType('bisheng.common.errcode.tool')
        for name in [
            'ToolTypeNotExistsError', 'ToolTypeRepeatError', 'ToolTypeNameError',
            'ToolTypeIsPresetError', 'ToolSchemaDownloadError', 'ToolSchemaEmptyError',
            'ToolSchemaParseError', 'ToolSchemaServerError', 'ToolMcpSchemaError',
            'ToolMcpStdioError',
        ]:
            setattr(tool_error_module, name, Exception)
        sys.modules['bisheng.common.errcode.tool'] = tool_error_module

        config_service_module = ModuleType('bisheng.common.services.config_service')
        config_service_module.settings = SimpleNamespace(
            get_mcp_conf=AsyncMock(return_value=SimpleNamespace(enable_stdio=True)),
        )
        sys.modules['bisheng.common.services.config_service'] = config_service_module

        group_resource_module = ModuleType('bisheng.database.models.group_resource')
        group_resource_module.ResourceTypeEnum = SimpleNamespace()
        sys.modules['bisheng.database.models.group_resource'] = group_resource_module

        role_access_module = ModuleType('bisheng.database.models.role_access')
        from bisheng.database.models.role_access import AccessType
        role_access_module.AccessType = AccessType
        sys.modules['bisheng.database.models.role_access'] = role_access_module

        mcp_constant_module = ModuleType('bisheng.mcp_manage.constant')
        mcp_constant_module.McpClientType = SimpleNamespace(STDIO=SimpleNamespace(value='stdio'))
        sys.modules['bisheng.mcp_manage.constant'] = mcp_constant_module

        mcp_manager_module = ModuleType('bisheng.mcp_manage.manager')
        mcp_manager_module.ClientManager = SimpleNamespace(
            connect_mcp_from_json=AsyncMock(),
            parse_mcp_client_type=lambda *args, **kwargs: ('http', None),
        )
        sys.modules['bisheng.mcp_manage.manager'] = mcp_manager_module

        tool_permission_module = ModuleType('bisheng.permission.domain.services.tool_permission_service')

        class _DummyToolPermissionService:
            @staticmethod
            def filter_tool_ids_by_permission_sync(login_user, tool_ids, permission_id):
                return tool_ids

            @staticmethod
            async def filter_tool_ids_by_permission_async(login_user, tool_ids, permission_id):
                return tool_ids

            @staticmethod
            async def has_any_permission_async(login_user, tool_type_id, permission_ids):
                return True

        tool_permission_module.ToolPermissionService = _DummyToolPermissionService
        sys.modules['bisheng.permission.domain.services.tool_permission_service'] = tool_permission_module

        tool_permission_template_module = ModuleType("bisheng.permission.domain.tool_permission_template")
        tool_permission_template_module.relation_for_tool_permission_id = (
            lambda permission_id: "can_read" if permission_id in ("view_tool", "use_tool") else None
        )
        sys.modules["bisheng.permission.domain.tool_permission_template"] = tool_permission_template_module

        tool_const_module = ModuleType('bisheng.tool.domain.const')
        tool_const_module.ToolPresetType = SimpleNamespace(
            PRESET=SimpleNamespace(value=1),
            API=SimpleNamespace(value=2),
            MCP=SimpleNamespace(value=3),
        )
        sys.modules['bisheng.tool.domain.const'] = tool_const_module

        linsight_knowledge_module = ModuleType('bisheng.tool.domain.langchain.linsight_knowledge')
        linsight_knowledge_module.SearchKnowledgeBase = SimpleNamespace
        sys.modules['bisheng.tool.domain.langchain.linsight_knowledge'] = linsight_knowledge_module

        gpts_tools_module = ModuleType('bisheng.tool.domain.models.gpts_tools')
        gpts_tools_module.GptsToolsDao = SimpleNamespace(
            aget_user_tool_type=AsyncMock(return_value=[]),
            aget_preset_tool_type=AsyncMock(return_value=[]),
            aget_list_by_type=AsyncMock(return_value=[]),
            aget_one_tool_type=AsyncMock(return_value=None),
        )
        gpts_tools_module.GptsTools = SimpleNamespace
        gpts_tools_module.GptsToolsType = SimpleNamespace

        class _DummyGptsToolsTypeRead:
            @classmethod
            def model_validate(cls, one):
                return one

        gpts_tools_module.GptsToolsTypeRead = _DummyGptsToolsTypeRead
        sys.modules['bisheng.tool.domain.models.gpts_tools'] = gpts_tools_module

        openapi_module = ModuleType('bisheng.tool.domain.services.openapi')
        openapi_module.OpenApiSchema = SimpleNamespace
        sys.modules['bisheng.tool.domain.services.openapi'] = openapi_module

        utils_module = ModuleType('bisheng.utils')
        utils_module.md5_hash = lambda value: 'hash'
        utils_module.get_request_ip = lambda request: '127.0.0.1'
        sys.modules['bisheng.utils'] = utils_module

        mask_module = ModuleType('bisheng.utils.mask_data')
        mask_module.JsonFieldMasker = SimpleNamespace
        sys.modules['bisheng.utils.mask_data'] = mask_module

        langchain_load_tools_module = ModuleType('bisheng_langchain.gpts.load_tools')
        langchain_load_tools_module.load_tools = lambda *args, **kwargs: []
        sys.modules['bisheng_langchain.gpts.load_tools'] = langchain_load_tools_module

        module_name = 'bisheng.tool.domain.services.tool'
        if module_name in sys.modules:
            sys.modules.pop(module_name)
        spec = importlib.util.spec_from_file_location(module_name, service_dir / 'tool.py')
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
async def test_get_tool_list_skips_redundant_filter_for_can_read_permission():
    """Default ``use_tool`` permission maps to ``can_read`` — the same relation
    AccessType.GPTS_TOOL_READ used by the coarse FGA list. Skipping the
    per-tool re-filter is what makes /api/v1/tool?is_preset=0|2 fast for
    normal users; the call must NOT happen at all (IKABRE)."""
    tool_module = _load_tool_service_module()
    ToolServices = tool_module.ToolServices

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_user_access_resource_ids=AsyncMock(return_value=['1', '2']),
        rebac_list_accessible=AsyncMock(side_effect=AssertionError('coarse relation list should not be used')),
    )
    tool_service = ToolServices(request=None, login_user=login_user)

    tool_type_one = SimpleNamespace(id=1, user_id=9, children=[], mask_sensitive_data=lambda: None)
    tool_type_two = SimpleNamespace(id=2, user_id=10, children=[], mask_sensitive_data=lambda: None)

    with patch.object(
        tool_module.ToolPermissionService,
        'filter_tool_ids_by_permission_async',
        new_callable=AsyncMock,
        side_effect=AssertionError(
            "use_tool (can_read) re-filter must be skipped when AccessType.GPTS_TOOL_READ already returned the set"
        ),
    ) as mock_filter_ids, patch.object(
        tool_module.ToolPermissionService,
        'get_tool_permission_map_async',
        new_callable=AsyncMock,
        return_value={'1': set(), '2': {'edit_tool', 'delete_tool'}},
    ), patch.object(
        tool_module.GptsToolsDao,
        'aget_user_tool_type',
        new_callable=AsyncMock,
        return_value=[tool_type_one, tool_type_two],
    ), patch.object(
        tool_module.GptsToolsDao,
        'aget_list_by_type',
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await tool_service.get_tool_list()

    # Both visible tools should still be returned (no second filter, so the
    # coarse list passes through).
    assert [one.id for one in result] == [1, 2]
    # Creator-of-tool #2 gets edit/delete via the in-code shortcut;
    # tool #1 has neither, so write/delete must be False.
    assert getattr(result[0], 'write', False) is False
    assert result[1].write is True
    assert getattr(result[0], 'delete', False) is False
    assert result[1].delete is True
    # The redundant filter must not run; only the action-level map is consulted.
    assert mock_filter_ids.call_count == 0


@pytest.mark.asyncio
async def test_get_tool_list_still_filters_for_strict_permission():
    """For permission ids that do NOT map to the coarse ``can_read`` list
    (e.g. legacy callers passing a custom id), the strict per-tool filter
    must still run so we don't accidentally over-grant visibility."""
    tool_module = _load_tool_service_module()
    ToolServices = tool_module.ToolServices

    login_user = SimpleNamespace(
        user_id=7,
        is_admin=lambda: False,
        aget_user_access_resource_ids=AsyncMock(return_value=['1', '2']),
        rebac_list_accessible=AsyncMock(side_effect=AssertionError('coarse relation list should not be used')),
    )
    tool_service = ToolServices(request=None, login_user=login_user)

    tool_type_one = SimpleNamespace(id=1, user_id=9, children=[], mask_sensitive_data=lambda: None)
    tool_type_two = SimpleNamespace(id=2, user_id=10, children=[], mask_sensitive_data=lambda: None)

    with patch.object(
        tool_module.ToolPermissionService,
        'filter_tool_ids_by_permission_async',
        new_callable=AsyncMock,
        return_value=['2'],
    ) as mock_filter_ids, patch.object(
        tool_module.GptsToolsDao,
        'aget_user_tool_type',
        new_callable=AsyncMock,
        return_value=[tool_type_one, tool_type_two],
    ), patch.object(
        tool_module.GptsToolsDao,
        'aget_list_by_type',
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await tool_service.get_tool_list(permission_id='manage_tool_owner')

    assert [one.id for one in result] == [2]
    # The strict path is taken — single call with the full input set.
    assert mock_filter_ids.call_count == 1
    assert mock_filter_ids.call_args_list[0].args[1] == [1, 2]
    assert mock_filter_ids.call_args_list[0].args[2] == 'manage_tool_owner'


def test_relation_for_tool_permission_id_maps_known_ids():
    """Tool permission ids must round-trip to their OpenFGA relation. This
    drives the fast-path branch in ToolServices.get_tool_list — if a new
    can_read id is added to the template the lookup must follow it."""
    from bisheng.permission.domain.tool_permission_template import (
        relation_for_tool_permission_id,
    )

    assert relation_for_tool_permission_id('view_tool') == 'can_read'
    assert relation_for_tool_permission_id('use_tool') == 'can_read'
    assert relation_for_tool_permission_id('edit_tool') == 'can_edit'
    assert relation_for_tool_permission_id('delete_tool') == 'can_delete'
    assert relation_for_tool_permission_id('manage_tool_owner') == 'can_manage'
    # Unknown id — must not silently resolve to can_read and over-grant.
    assert relation_for_tool_permission_id('not_a_real_id') is None
    # Empty / None must not raise; fast-path callers always treat None as
    # "fall back to the strict filter".
    assert relation_for_tool_permission_id('') is None
    assert relation_for_tool_permission_id(None) is None


@pytest.mark.asyncio
async def test_update_and_delete_tools_use_action_level_permissions():
    tool_module = _load_tool_service_module()
    ToolServices = tool_module.ToolServices

    login_user = SimpleNamespace(user_id=7)
    tool_service = ToolServices(request=None, login_user=login_user)
    preset_tool_type = SimpleNamespace(id=12, user_id=9, is_preset=1, extra='{}', name='tool')
    custom_tool_type = SimpleNamespace(id=12, user_id=9, is_preset=0, extra='{}', name='tool')

    with patch.object(
        tool_module.GptsToolsDao,
        'aget_one_tool_type',
        new_callable=AsyncMock,
        return_value=preset_tool_type,
    ), patch.object(
        tool_module.ToolPermissionService,
        'has_any_permission_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_has_permission, patch.object(
        tool_module.GptsToolsDao,
        'update_tools_extra',
        new_callable=AsyncMock,
        create=True,
    ), patch.object(
        tool_module,
        'JsonFieldMasker',
        return_value=SimpleNamespace(update_json_with_masked=lambda old, new: new),
    ):
        await tool_service.update_tool_config(12, {'k': 'v'})

    mock_has_permission.assert_awaited_once_with(login_user, '12', ['edit_tool'])

    with patch.object(
        tool_module.GptsToolsDao,
        'aget_one_tool_type',
        new_callable=AsyncMock,
        return_value=custom_tool_type,
    ), patch.object(
        tool_module.ToolPermissionService,
        'has_any_permission_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete_permission, patch.object(
        tool_module.GptsToolsDao,
        'delete_tool_type',
        new_callable=AsyncMock,
        create=True,
    ), patch.object(
        ToolServices,
        'delete_tool_hook',
        new_callable=AsyncMock,
        create=True,
    ):
        await tool_service.delete_tools(12)

    mock_delete_permission.assert_awaited_once_with(login_user, '12', ['delete_tool'])


@pytest.mark.asyncio
async def test_update_tools_uses_edit_tool_permission():
    tool_module = _load_tool_service_module()
    ToolServices = tool_module.ToolServices

    login_user = SimpleNamespace(user_id=7)
    tool_service = ToolServices(request=None, login_user=login_user)
    req = SimpleNamespace(
        id=12,
        name='tool',
        is_preset=0,
        openapi_schema='',
        children=[],
        logo='',
        description='',
        server_host='',
        auth_method=0,
        api_key='',
        auth_type='',
        api_location='',
        parameter_name='',
    )
    existing = SimpleNamespace(id=12, user_id=9, is_preset=0, name='tool')

    with patch.object(
        tool_module.GptsToolsDao,
        'aget_one_tool_type',
        new_callable=AsyncMock,
        return_value=existing,
    ), patch.object(
        tool_module.GptsToolsDao,
        'get_one_tool_type_by_name',
        new_callable=AsyncMock,
        return_value=None,
        create=True,
    ), patch.object(
        tool_module.ToolPermissionService,
        'has_any_permission_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_has_permission, patch.object(
        tool_module.ToolServices,
        '_update_gpts_tools',
        new_callable=AsyncMock,
        return_value=req,
    ), patch.object(
        tool_module.ToolServices,
        'update_tool_hook',
        new_callable=AsyncMock,
    ), patch.object(
        tool_module,
        'ToolPresetType',
        SimpleNamespace(PRESET=SimpleNamespace(value=1), API=SimpleNamespace(value=2), MCP=SimpleNamespace(value=3)),
    ):
        await tool_service.update_tools(req)

    mock_has_permission.assert_awaited_once_with(login_user, '12', ['edit_tool'])


@pytest.mark.asyncio
async def test_add_tool_hook_writes_owner_tuple_from_async_context(monkeypatch):
    tool_module = _load_tool_service_module()
    write_owner = AsyncMock()
    create_tool_audit = MagicMock()

    owner_service_module = ModuleType('bisheng.permission.domain.services.owner_service')
    owner_service_module.OwnerService = SimpleNamespace(write_owner_tuple=write_owner)
    monkeypatch.setitem(sys.modules, 'bisheng.permission.domain.services.owner_service', owner_service_module)

    api_module = ModuleType('bisheng.api')
    api_module.__path__ = []
    services_module = ModuleType('bisheng.api.services')
    services_module.__path__ = []
    audit_log_module = ModuleType('bisheng.api.services.audit_log')
    audit_log_module.AuditLogService = SimpleNamespace(create_tool=create_tool_audit)
    monkeypatch.setitem(sys.modules, 'bisheng.api', api_module)
    monkeypatch.setitem(sys.modules, 'bisheng.api.services', services_module)
    monkeypatch.setitem(sys.modules, 'bisheng.api.services.audit_log', audit_log_module)

    user = SimpleNamespace(user_id=7)
    tool_type = SimpleNamespace(id=12)

    await tool_module.ToolServices.add_gpts_tools_hook(None, user, tool_type)

    write_owner.assert_awaited_once_with(7, 'tool', '12')
    create_tool_audit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_tool_hook_cleans_fga_tuples_from_async_context(monkeypatch):
    tool_module = _load_tool_service_module()
    delete_tuples = AsyncMock()
    delete_tool_audit = MagicMock()

    owner_service_module = ModuleType('bisheng.permission.domain.services.owner_service')
    owner_service_module.OwnerService = SimpleNamespace(delete_resource_tuples=delete_tuples)
    monkeypatch.setitem(sys.modules, 'bisheng.permission.domain.services.owner_service', owner_service_module)

    api_module = ModuleType('bisheng.api')
    api_module.__path__ = []
    services_module = ModuleType('bisheng.api.services')
    services_module.__path__ = []
    audit_log_module = ModuleType('bisheng.api.services.audit_log')
    audit_log_module.AuditLogService = SimpleNamespace(delete_tool=delete_tool_audit)
    monkeypatch.setitem(sys.modules, 'bisheng.api', api_module)
    monkeypatch.setitem(sys.modules, 'bisheng.api.services', services_module)
    monkeypatch.setitem(sys.modules, 'bisheng.api.services.audit_log', audit_log_module)

    user = SimpleNamespace(user_id=7)
    tool_type = SimpleNamespace(id=12)

    await tool_module.ToolServices.delete_tool_hook(None, user, tool_type)

    delete_tuples.assert_awaited_once_with('tool', '12')
    delete_tool_audit.assert_called_once()
