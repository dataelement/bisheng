import asyncio
from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.role_access import AccessType
from bisheng.user.domain.services import auth as auth_mod


@pytest.fixture
def login_user(monkeypatch):
    monkeypatch.setattr(auth_mod.UserRoleDao, "get_user_roles", lambda user_id: [])
    return auth_mod.LoginUser(user_id=7, user_name="tester", user_role=[2])


def test_sync_access_check_uses_canonical_knowledge_library_target(login_user, monkeypatch):
    rebac_check = AsyncMock(side_effect=lambda relation, object_type, object_id: object_type == "knowledge_library")
    monkeypatch.setattr(
        auth_mod.LoginUser,
        "rebac_check",
        rebac_check,
    )
    monkeypatch.setattr(
        "bisheng.permission.domain.services.owner_service._run_async_safe",
        lambda coro: asyncio.run(coro),
    )

    assert login_user.access_check(owner_user_id=99, target_id="12", access_type=AccessType.KNOWLEDGE) is True
    rebac_check.assert_awaited_once_with("can_read", "knowledge_library", "12")


@pytest.mark.asyncio
async def test_async_access_check_uses_canonical_knowledge_library_target(login_user, monkeypatch):
    rebac_check = AsyncMock(side_effect=lambda relation, object_type, object_id: object_type == "knowledge_library")
    monkeypatch.setattr(
        auth_mod.LoginUser,
        "rebac_check",
        rebac_check,
    )

    allowed = await login_user.async_access_check(
        owner_user_id=99,
        target_id="15",
        access_type=AccessType.KNOWLEDGE,
    )

    assert allowed is True
    rebac_check.assert_awaited_once_with("can_read", "knowledge_library", "15")


@pytest.mark.asyncio
async def test_async_accessible_ids_use_canonical_knowledge_library_target(login_user, monkeypatch):
    rebac_list_accessible = AsyncMock(
        side_effect=lambda relation, object_type: ["1", "2"] if object_type == "knowledge_library" else ["3"]
    )
    monkeypatch.setattr(
        auth_mod.LoginUser,
        "rebac_list_accessible",
        rebac_list_accessible,
    )

    ids = await login_user.aget_user_access_resource_ids([AccessType.KNOWLEDGE])

    assert set(ids) == {"1", "2"}
    rebac_list_accessible.assert_awaited_once_with("can_read", "knowledge_library")
