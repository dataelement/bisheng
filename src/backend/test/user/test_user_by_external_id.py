"""Tests for ``GET /user/by-external-id``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.user import UserValidateError
from bisheng.user.api import user as user_api


def _user(
    *,
    user_id: int = 7,
    external_id: str = "E001",
    source: str = "local",
    delete: int = 0,
    user_name: str = "Alice",
):
    return SimpleNamespace(
        user_id=user_id,
        external_id=external_id,
        source=source,
        delete=delete,
        user_name=user_name,
        model_dump=lambda: {
            "user_id": user_id,
            "external_id": external_id,
            "source": source,
            "delete": delete,
            "user_name": user_name,
            "password": "secret",
            "password_update_time": "2026-01-01T00:00:00",
            "token_version": 0,
            "avatar": None,
        },
    )


class _LoginUser:
    def __init__(self, *, admin: bool = True, user_id: int = 1) -> None:
        self._admin = admin
        self.user_id = user_id

    def is_admin(self) -> bool:
        return self._admin


@pytest.mark.asyncio
async def test_get_user_by_external_id_returns_single_payload() -> None:
    target = _user()
    login_user = _LoginUser(admin=True)

    with (
        patch.object(user_api.UserDao, "aget_users_by_external_id", AsyncMock(return_value=[target])),
        patch.object(user_api, "_compute_viewable_user_ids", AsyncMock(return_value=None)),
        patch.object(user_api, "_primary_department_id_map_for_user_ids", return_value={7: 21}),
        patch.object(user_api, "_build_user_list_entry", AsyncMock(return_value={"user_id": 7, "external_id": "E001"})),
    ):
        response = await user_api.get_user_by_external_id(
            external_id="E001",
            source=None,
            include_deleted=False,
            login_user=login_user,
        )

    assert response.data == {"user_id": 7, "external_id": "E001"}


@pytest.mark.asyncio
async def test_get_user_by_external_id_with_source_uses_exact_match() -> None:
    target = _user(source="feishu")
    login_user = _LoginUser(admin=True)

    exact_lookup = AsyncMock(return_value=target)
    list_lookup = AsyncMock(return_value=[])

    with (
        patch.object(user_api.UserDao, "aget_by_source_external_id", exact_lookup),
        patch.object(user_api.UserDao, "aget_users_by_external_id", list_lookup),
        patch.object(user_api, "_compute_viewable_user_ids", AsyncMock(return_value=None)),
        patch.object(user_api, "_primary_department_id_map_for_user_ids", return_value={7: 21}),
        patch.object(user_api, "_build_user_list_entry", AsyncMock(return_value={"user_id": 7, "source": "feishu"})),
    ):
        await user_api.get_user_by_external_id(
            external_id="E001",
            source="feishu",
            include_deleted=False,
            login_user=login_user,
        )

    exact_lookup.assert_awaited_once_with("feishu", "E001")
    list_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_get_user_by_external_id_not_found_when_deleted() -> None:
    login_user = _LoginUser(admin=True)

    with patch.object(
        user_api.UserDao,
        "aget_users_by_external_id",
        AsyncMock(return_value=[_user(delete=1)]),
    ):
        with pytest.raises(NotFoundError):
            await user_api.get_user_by_external_id(
                external_id="E001",
                source=None,
                include_deleted=False,
                login_user=login_user,
            )


@pytest.mark.asyncio
async def test_get_user_by_external_id_rejects_blank_external_id() -> None:
    login_user = _LoginUser(admin=True)

    with pytest.raises(UserValidateError):
        await user_api.get_user_by_external_id(
            external_id="   ",
            source=None,
            include_deleted=False,
            login_user=login_user,
        )


@pytest.mark.asyncio
async def test_get_user_by_external_id_hides_out_of_scope_user() -> None:
    login_user = _LoginUser(admin=False)

    with (
        patch.object(
            user_api.UserDao,
            "aget_users_by_external_id",
            AsyncMock(return_value=[_user(user_id=99)]),
        ),
        patch.object(user_api, "_compute_viewable_user_ids", AsyncMock(return_value={7})),
    ):
        with pytest.raises(NotFoundError):
            await user_api.get_user_by_external_id(
                external_id="E001",
                source=None,
                include_deleted=False,
                login_user=login_user,
            )


@pytest.mark.asyncio
async def test_build_user_list_entry_strips_sensitive_fields() -> None:
    target = _user()

    with (
        patch.object(user_api.DepartmentDao, "get_by_id", return_value=SimpleNamespace(name="研发部")),
        patch.object(user_api.UserService, "get_avatar_share_link", AsyncMock(return_value=None)),
        patch.object(user_api, "get_user_roles", return_value=[]),
        patch.object(user_api, "get_user_groups", return_value=[]),
    ):
        payload = await user_api._build_user_list_entry(
            target,
            user_admin_groups=[],
            primary_dept_id=21,
        )

    assert "password" not in payload
    assert "password_update_time" not in payload
    assert "token_version" not in payload
    assert payload["department_id"] == 21
    assert payload["department_name"] == "研发部"
