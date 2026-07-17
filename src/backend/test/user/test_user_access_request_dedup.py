from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bisheng.user.domain.services.auth as auth_module
import bisheng.user.domain.services.user as user_service_module


async def test_user_entry_queries_each_access_source_once():
    user = SimpleNamespace(user_id=7, tenant_id=1)
    role_rows = [SimpleNamespace(role_id=2)]

    with (
        patch.object(
            auth_module.UserRoleDao,
            "aget_user_roles",
            new_callable=AsyncMock,
            return_value=role_rows,
        ) as mock_roles,
        patch.object(
            auth_module.DepartmentDao,
            "aget_user_admin_departments",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_departments,
        patch.object(
            auth_module.RoleAccessDao,
            "aget_role_access",
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(third_id="workstation")],
        ),
        patch.object(
            auth_module.UserMenuAccessService,
            "list_effective_menu_grants",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        entry = await auth_module.LoginUser.user_entry_payload_for_read(user)

    assert entry == {
        "has_workbench": True,
        "has_admin_console": False,
        "default_entry": "workspace",
    }
    mock_roles.assert_awaited_once_with(7)
    mock_departments.assert_awaited_once_with(7)


async def test_init_login_user_reuses_explicit_empty_role_snapshot():
    with (
        patch.object(
            auth_module.UserRoleDao,
            "aget_user_roles",
            new_callable=AsyncMock,
        ) as mock_async_roles,
        patch.object(auth_module.UserRoleDao, "get_user_roles") as mock_sync_roles,
        patch(
            "bisheng.utils.http_middleware._check_is_global_super",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_global_super,
    ):
        login_user = await auth_module.LoginUser.init_login_user(
            9,
            "user-9",
            role_ids=[],
        )

    assert login_user.user_role == []
    mock_async_roles.assert_not_awaited()
    mock_sync_roles.assert_not_called()
    mock_global_super.assert_awaited_once_with(9, role_ids=[])


async def test_login_access_guard_reuses_resolved_roles_and_department_flag():
    user = SimpleNamespace(user_id=11)

    with (
        patch.object(
            user_service_module.UserRoleDao,
            "aget_user_roles",
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(role_id=2)],
        ) as mock_roles,
        patch.object(
            user_service_module.DepartmentDao,
            "aget_user_admin_departments",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_departments,
        patch.object(
            user_service_module.LoginUser,
            "user_has_workbench_or_admin_effective_menu",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_effective_menu,
    ):
        result = await user_service_module.UserService._reject_login_if_user_has_no_usable_access(user)

    assert result is None
    mock_roles.assert_awaited_once_with(11)
    mock_departments.assert_awaited_once_with(11)
    mock_effective_menu.assert_awaited_once_with(
        user,
        role_ids=[2],
        is_department_admin=False,
    )


async def test_user_login_enters_tenant_bypass_before_multi_tenant_resolution():
    db_user = SimpleNamespace(user_id=12, delete=0)
    rejected_response = object()
    login_request = SimpleNamespace(user_name="alice", password="encrypted")
    captcha_setting = AsyncMock(return_value=False)

    with (
        patch.object(
            user_service_module,
            "settings",
            SimpleNamespace(aget_from_db=captcha_setting),
        ),
        patch.object(
            user_service_module.UserDao,
            "aget_login_candidates_by_account",
            new_callable=AsyncMock,
            return_value=[db_user],
        ),
        patch.object(
            user_service_module.UserService,
            "decrypt_md5_password",
            return_value="password",
        ),
        patch.object(
            user_service_module.UserService,
            "judge_user_password",
            new_callable=AsyncMock,
        ),
        patch.object(
            user_service_module.UserService,
            "clear_error_password_key",
            new_callable=AsyncMock,
        ),
        patch.object(
            user_service_module.UserRoleDao,
            "aget_user_roles",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            user_service_module.DepartmentDao,
            "aget_user_admin_departments",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            user_service_module.UserService,
            "_reject_login_if_user_has_no_usable_access",
            new_callable=AsyncMock,
            return_value=rejected_response,
        ),
    ):
        result = await user_service_module.UserService.user_login(
            SimpleNamespace(),
            login_request,
            auth_jwt=SimpleNamespace(),
        )

    assert result is rejected_response
    captcha_setting.assert_awaited_once_with("use_captcha")
