from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload


@pytest.mark.asyncio
async def test_get_model_admin_user_bypasses_menu_check_for_super_admin(monkeypatch):
    login_user = UserPayload(user_id=1, user_name='root', user_role=[1])
    get_login_user = AsyncMock(return_value=login_user)
    assert_menu = AsyncMock()

    monkeypatch.setattr(UserPayload, 'get_login_user', get_login_user)
    monkeypatch.setattr(UserPayload, 'assert_effective_web_menu_contains', assert_menu)

    result = await UserPayload.get_model_admin_user(MagicMock())

    assert result is login_user
    get_login_user.assert_awaited_once()
    assert_menu.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_model_admin_user_allows_non_admin_with_model_menu(monkeypatch):
    login_user = UserPayload(user_id=7, user_name='tenant-admin', user_role=[2])
    get_login_user = AsyncMock(return_value=login_user)
    assert_menu = AsyncMock()

    monkeypatch.setattr(UserPayload, 'get_login_user', get_login_user)
    monkeypatch.setattr(UserPayload, 'assert_effective_web_menu_contains', assert_menu)

    result = await UserPayload.get_model_admin_user(MagicMock())

    assert result is login_user
    get_login_user.assert_awaited_once()
    assert_menu.assert_awaited_once_with(7, 'model')
