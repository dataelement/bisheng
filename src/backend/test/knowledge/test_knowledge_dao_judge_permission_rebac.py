"""Tests for KnowledgeDao.judge_knowledge_permission / ajudge_knowledge_permission
after F008 follow-up migration to ReBAC.

Verifies:
  * Empty input short-circuits to [].
  * Unknown user short-circuits to [].
  * Admin user (list_accessible_ids returns None) gets the full set fetched
    by id.
  * Non-admin user gets only the intersection of input ids and the FGA-
    accessible id set.
  * Non-admin user with no overlap gets [].
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao


def _kb(id_: int):
    return SimpleNamespace(id=id_, name=f'kb-{id_}')


def _patch_user_lookup_async(monkeypatch, user_id: int = 42):
    user = SimpleNamespace(user_id=user_id, user_name='alice')
    monkeypatch.setattr(
        knowledge_module.UserDao,
        'aget_user_by_username',
        AsyncMock(return_value=user),
    )
    return user


def _patch_user_lookup_sync(monkeypatch, user_id: int = 42):
    user = SimpleNamespace(user_id=user_id, user_name='alice')
    monkeypatch.setattr(
        knowledge_module.UserDao,
        'get_user_by_username',
        MagicMock(return_value=user),
    )
    return user


def _patch_login_user_async(monkeypatch, user_id: int = 42):
    fake_login_user = SimpleNamespace(user_id=user_id, user_name='alice')
    from bisheng.user.domain.services import auth as auth_mod

    monkeypatch.setattr(
        auth_mod.LoginUser,
        'init_login_user',
        AsyncMock(return_value=fake_login_user),
    )
    return fake_login_user


def _patch_login_user_sync(monkeypatch, user_id: int = 42):
    fake_login_user = SimpleNamespace(user_id=user_id, user_name='alice')
    from bisheng.user.domain.services import auth as auth_mod

    monkeypatch.setattr(
        auth_mod.LoginUser,
        'init_login_user_sync',
        MagicMock(return_value=fake_login_user),
    )
    return fake_login_user


# ──────────────────────────────────────────────────────────────────────────
# Async tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ajudge_empty_input_returns_empty():
    result = await KnowledgeDao.ajudge_knowledge_permission('alice', [])
    assert result == []


@pytest.mark.asyncio
async def test_ajudge_unknown_user_returns_empty(monkeypatch):
    monkeypatch.setattr(
        knowledge_module.UserDao,
        'aget_user_by_username',
        AsyncMock(return_value=None),
    )
    result = await KnowledgeDao.ajudge_knowledge_permission('ghost', [1, 2])
    assert result == []


@pytest.mark.asyncio
async def test_ajudge_admin_gets_full_set(monkeypatch):
    _patch_user_lookup_async(monkeypatch)
    _patch_login_user_async(monkeypatch)

    from bisheng.permission.domain.services import permission_service as ps_mod

    monkeypatch.setattr(
        ps_mod.PermissionService,
        'list_accessible_ids',
        AsyncMock(return_value=None),
    )
    aget_list_mock = AsyncMock(return_value=[_kb(1), _kb(2), _kb(3)])
    monkeypatch.setattr(KnowledgeDao, 'aget_list_by_ids', aget_list_mock)

    result = await KnowledgeDao.ajudge_knowledge_permission('alice', [1, 2, 3])

    aget_list_mock.assert_awaited_once_with([1, 2, 3])
    assert [k.id for k in result] == [1, 2, 3]


@pytest.mark.asyncio
async def test_ajudge_non_admin_filters_to_accessible_intersection(monkeypatch):
    _patch_user_lookup_async(monkeypatch)
    _patch_login_user_async(monkeypatch)

    from bisheng.permission.domain.services import permission_service as ps_mod

    monkeypatch.setattr(
        ps_mod.PermissionService,
        'list_accessible_ids',
        AsyncMock(return_value=['1', '3', '99']),  # 99 not in input — must be discarded
    )
    aget_list_mock = AsyncMock(return_value=[_kb(1), _kb(3)])
    monkeypatch.setattr(KnowledgeDao, 'aget_list_by_ids', aget_list_mock)

    result = await KnowledgeDao.ajudge_knowledge_permission('alice', [1, 2, 3])

    aget_list_mock.assert_awaited_once_with([1, 3])
    assert sorted(k.id for k in result) == [1, 3]


@pytest.mark.asyncio
async def test_ajudge_non_admin_no_overlap_returns_empty(monkeypatch):
    _patch_user_lookup_async(monkeypatch)
    _patch_login_user_async(monkeypatch)

    from bisheng.permission.domain.services import permission_service as ps_mod

    monkeypatch.setattr(
        ps_mod.PermissionService,
        'list_accessible_ids',
        AsyncMock(return_value=['77', '88']),
    )
    aget_list_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(KnowledgeDao, 'aget_list_by_ids', aget_list_mock)

    result = await KnowledgeDao.ajudge_knowledge_permission('alice', [1, 2, 3])

    aget_list_mock.assert_not_awaited()
    assert result == []


# ──────────────────────────────────────────────────────────────────────────
# Sync tests
# ──────────────────────────────────────────────────────────────────────────


def test_judge_empty_input_returns_empty():
    assert KnowledgeDao.judge_knowledge_permission('alice', []) == []


def test_judge_unknown_user_returns_empty(monkeypatch):
    monkeypatch.setattr(
        knowledge_module.UserDao,
        'get_user_by_username',
        MagicMock(return_value=None),
    )
    assert KnowledgeDao.judge_knowledge_permission('ghost', [1, 2]) == []


def _patch_run_async_safe(monkeypatch):
    """Replace run_async_safe with a plain asyncio.run so we can drive the
    sync entrypoint deterministically inside pytest's main thread."""
    monkeypatch.setattr(
        'bisheng.permission.domain.services.owner_service._run_async_safe',
        lambda coro, *args, **kwargs: asyncio.new_event_loop().run_until_complete(coro),
    )


def test_judge_admin_gets_full_set(monkeypatch):
    _patch_user_lookup_sync(monkeypatch)
    _patch_login_user_sync(monkeypatch)
    _patch_run_async_safe(monkeypatch)

    from bisheng.permission.domain.services import permission_service as ps_mod

    monkeypatch.setattr(
        ps_mod.PermissionService,
        'list_accessible_ids',
        AsyncMock(return_value=None),
    )
    get_list_mock = MagicMock(return_value=[_kb(1), _kb(2)])
    monkeypatch.setattr(KnowledgeDao, 'get_list_by_ids', get_list_mock)

    result = KnowledgeDao.judge_knowledge_permission('alice', [1, 2])

    get_list_mock.assert_called_once_with([1, 2])
    assert [k.id for k in result] == [1, 2]


def test_judge_non_admin_filters_to_accessible_intersection(monkeypatch):
    _patch_user_lookup_sync(monkeypatch)
    _patch_login_user_sync(monkeypatch)
    _patch_run_async_safe(monkeypatch)

    from bisheng.permission.domain.services import permission_service as ps_mod

    monkeypatch.setattr(
        ps_mod.PermissionService,
        'list_accessible_ids',
        AsyncMock(return_value=['2']),
    )
    get_list_mock = MagicMock(return_value=[_kb(2)])
    monkeypatch.setattr(KnowledgeDao, 'get_list_by_ids', get_list_mock)

    result = KnowledgeDao.judge_knowledge_permission('alice', [1, 2, 3])

    get_list_mock.assert_called_once_with([2])
    assert [k.id for k in result] == [2]


def test_judge_non_admin_no_overlap_returns_empty(monkeypatch):
    _patch_user_lookup_sync(monkeypatch)
    _patch_login_user_sync(monkeypatch)
    _patch_run_async_safe(monkeypatch)

    from bisheng.permission.domain.services import permission_service as ps_mod

    monkeypatch.setattr(
        ps_mod.PermissionService,
        'list_accessible_ids',
        AsyncMock(return_value=['7']),
    )
    get_list_mock = MagicMock(return_value=[])
    monkeypatch.setattr(KnowledgeDao, 'get_list_by_ids', get_list_mock)

    result = KnowledgeDao.judge_knowledge_permission('alice', [1, 2])

    get_list_mock.assert_not_called()
    assert result == []
