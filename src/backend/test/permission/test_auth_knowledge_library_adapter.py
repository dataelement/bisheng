import asyncio
from unittest.mock import AsyncMock

import pytest

from bisheng.user.domain.services import auth as auth_mod


@pytest.fixture
def login_user(monkeypatch):
    monkeypatch.setattr(auth_mod.UserRoleDao, 'get_user_roles', lambda user_id: [])
    return auth_mod.LoginUser(user_id=7, user_name='tester', user_role=[2])


def test_sync_access_check_accepts_legacy_and_new_knowledge_targets(login_user, monkeypatch):
    monkeypatch.setitem(
        auth_mod._ACCESS_TYPE_TO_REBAC,
        'legacy-read',
        (
            ('can_read', 'knowledge_library'),
            ('can_read', 'knowledge_space'),
        ),
    )
    monkeypatch.setattr(
        auth_mod.LoginUser,
        'rebac_check',
        AsyncMock(side_effect=lambda relation, object_type, object_id: object_type == 'knowledge_space'),
    )
    monkeypatch.setattr(
        'bisheng.permission.domain.services.owner_service._run_async_safe',
        lambda coro: asyncio.run(coro),
    )

    assert login_user.access_check(owner_user_id=99, target_id='12', access_type='legacy-read') is True


@pytest.mark.asyncio
async def test_async_access_check_unions_new_and_legacy_knowledge_targets(login_user, monkeypatch):
    monkeypatch.setitem(
        auth_mod._ACCESS_TYPE_TO_REBAC,
        'legacy-read',
        (
            ('can_read', 'knowledge_library'),
            ('can_read', 'knowledge_space'),
        ),
    )
    monkeypatch.setattr(
        auth_mod.LoginUser,
        'rebac_check',
        AsyncMock(side_effect=lambda relation, object_type, object_id: object_type == 'knowledge_library'),
    )

    allowed = await login_user.async_access_check(
        owner_user_id=99,
        target_id='15',
        access_type='legacy-read',
    )

    assert allowed is True


@pytest.mark.asyncio
async def test_async_accessible_ids_merge_new_and_legacy_knowledge_targets(login_user, monkeypatch):
    monkeypatch.setitem(
        auth_mod._ACCESS_TYPE_TO_REBAC,
        'legacy-read',
        (
            ('can_read', 'knowledge_library'),
            ('can_read', 'knowledge_space'),
        ),
    )
    monkeypatch.setattr(
        auth_mod.LoginUser,
        'rebac_list_accessible',
        AsyncMock(side_effect=lambda relation, object_type: (
            ['1', '2'] if object_type == 'knowledge_library' else ['2', '3']
        )),
    )

    ids = await login_user.aget_user_access_resource_ids(['legacy-read'])

    assert set(ids) == {'1', '2', '3'}
