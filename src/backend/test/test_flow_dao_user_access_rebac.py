"""Tests for FlowDao.get_user_access_online_flows after F008 follow-up
migration to ReBAC.

Verifies:
  * Admin user (list_accessible_ids returns None) preserves the magic
    sentinel flow_id_extra='admin'.
  * Non-admin user passes the FGA-resolved id list to FlowDao.get_flows.
  * No-access user passes [] to FlowDao.get_flows.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.database.models.flow import FlowDao


def _patch_login_user_sync(monkeypatch, user_id: int = 7):
    fake_login_user = SimpleNamespace(user_id=user_id, user_name='')
    from bisheng.user.domain.services import auth as auth_mod

    monkeypatch.setattr(
        auth_mod.LoginUser,
        'init_login_user_sync',
        MagicMock(return_value=fake_login_user),
    )
    return fake_login_user


def _patch_run_async_safe(monkeypatch, return_value):
    monkeypatch.setattr(
        'bisheng.permission.domain.services.owner_service._run_async_safe',
        lambda coro, *args, **kwargs: (asyncio.new_event_loop().run_until_complete(coro), return_value)[1]
        if False else _consume_and_return(coro, return_value),
    )


def _consume_and_return(coro, value):
    coro.close()
    return value


def test_admin_passes_magic_admin_sentinel(monkeypatch):
    _patch_login_user_sync(monkeypatch)
    _patch_run_async_safe(monkeypatch, return_value=None)

    captured = {}

    def fake_get_flows(user_id, flow_id_extra, *args, **kwargs):
        captured['user_id'] = user_id
        captured['flow_id_extra'] = flow_id_extra
        return ['flow-row']

    monkeypatch.setattr(FlowDao, 'get_flows', fake_get_flows)

    out = FlowDao.get_user_access_online_flows(user_id=7, page=1, limit=50)

    assert out == ['flow-row']
    assert captured['user_id'] == 7
    assert captured['flow_id_extra'] == 'admin'


def test_non_admin_passes_accessible_ids_list(monkeypatch):
    _patch_login_user_sync(monkeypatch)
    _patch_run_async_safe(monkeypatch, return_value=['11', '22', '33'])

    captured = {}

    def fake_get_flows(user_id, flow_id_extra, *args, **kwargs):
        captured['flow_id_extra'] = flow_id_extra
        return []

    monkeypatch.setattr(FlowDao, 'get_flows', fake_get_flows)

    FlowDao.get_user_access_online_flows(user_id=7)

    assert captured['flow_id_extra'] == ['11', '22', '33']


def test_non_admin_no_accessible_passes_empty_list(monkeypatch):
    _patch_login_user_sync(monkeypatch)
    _patch_run_async_safe(monkeypatch, return_value=[])

    captured = {}

    def fake_get_flows(user_id, flow_id_extra, *args, **kwargs):
        captured['flow_id_extra'] = flow_id_extra
        return []

    monkeypatch.setattr(FlowDao, 'get_flows', fake_get_flows)

    FlowDao.get_user_access_online_flows(user_id=7)

    assert captured['flow_id_extra'] == []
