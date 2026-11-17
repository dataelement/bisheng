"""F004 T010: tenant-scoped switch between the legacy and the unified runtime.

The switch lives in the per-tenant daily workstation config (``workstation``
key, ``tenant_workstation_config`` table / legacy ``config`` table), the same
record the 工作台配置 page edits. It defaults to off, so every tenant stays on
the legacy path until an operator turns it on.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.common.models.config import ConfigKeyEnum
from bisheng.workstation.domain.services import workstation_service as ws_module
from bisheng.workstation.domain.services.workstation_service import (
    WorkStationService,
    is_unified_runtime_enabled,
)


class _FakeTenantDao:
    """In-memory stand-in for TenantWorkstationConfigDao.aresolve (Root inheritance included)."""

    def __init__(self, rows: dict[tuple[int, str], str]):
        self.rows = rows
        self.calls: list[tuple[int, str]] = []

    async def aresolve(self, tenant_id: int, key: str):
        self.calls.append((tenant_id, key))
        own = self.rows.get((tenant_id, key))
        if own:
            return own, False, tenant_id, True
        root = self.rows.get((1, key))
        if root:
            return root, tenant_id != 1, 1, tenant_id == 1
        return None, False, 1, False


@pytest.fixture
def multi_tenant(monkeypatch):
    def _install(rows: dict[tuple[int, str], str]) -> _FakeTenantDao:
        dao = _FakeTenantDao(rows)
        monkeypatch.setattr(WorkStationService, "_multi_tenant_enabled", classmethod(lambda cls: True))
        monkeypatch.setattr(ws_module, "TenantWorkstationConfigDao", dao)
        return dao

    return _install


def _payload(**fields) -> str:
    return json.dumps(fields)


KEY = ConfigKeyEnum.WORKSTATION.value


def test_schema_default_is_false():
    assert WorkstationConfig().unified_runtime_enabled is False
    # Old payloads (no key) still parse, and the field is not "set" for exclude_unset dumps.
    cfg = WorkstationConfig(**json.loads(_payload(welcomeMessage="hi")))
    assert cfg.unified_runtime_enabled is False
    assert "unified_runtime_enabled" not in cfg.model_dump(exclude_unset=True)


async def test_default_false_when_nothing_stored(multi_tenant):
    multi_tenant({})
    assert await is_unified_runtime_enabled(5) is False


async def test_default_false_when_key_missing(multi_tenant):
    multi_tenant({(5, KEY): _payload(welcomeMessage="saved")})
    assert await is_unified_runtime_enabled(5) is False


async def test_true_only_for_the_tenant_that_set_it(multi_tenant):
    dao = multi_tenant(
        {
            (5, KEY): _payload(unified_runtime_enabled=True),
            (6, KEY): _payload(unified_runtime_enabled=False),
        }
    )
    assert await is_unified_runtime_enabled(5) is True
    assert await is_unified_runtime_enabled(6) is False
    # The explicit tenant id is used, not the request context.
    assert (5, KEY) in dao.calls and (6, KEY) in dao.calls


async def test_child_tenant_inherits_root_switch(multi_tenant):
    multi_tenant({(1, KEY): _payload(unified_runtime_enabled=True)})
    assert await is_unified_runtime_enabled(9) is True


async def test_none_tenant_resolves_to_root(multi_tenant):
    dao = multi_tenant({(1, KEY): _payload(unified_runtime_enabled=True)})
    assert await is_unified_runtime_enabled(None) is True
    assert dao.calls[-1] == (1, KEY)


@pytest.mark.parametrize(
    "stored",
    [
        "not json at all",
        json.dumps(["a", "list"]),
        _payload(unified_runtime_enabled="definitely"),
        _payload(unified_runtime_enabled=None),
    ],
)
async def test_malformed_values_do_not_raise(multi_tenant, stored):
    multi_tenant({(5, KEY): stored})
    assert await is_unified_runtime_enabled(5) is False


async def test_read_failure_does_not_raise(monkeypatch):
    class _Boom:
        async def aresolve(self, tenant_id, key):
            raise RuntimeError("db down")

    monkeypatch.setattr(WorkStationService, "_multi_tenant_enabled", classmethod(lambda cls: True))
    monkeypatch.setattr(ws_module, "TenantWorkstationConfigDao", _Boom())
    assert await is_unified_runtime_enabled(5) is False


async def test_single_tenant_reads_legacy_config(monkeypatch):
    monkeypatch.setattr(WorkStationService, "_multi_tenant_enabled", classmethod(lambda cls: False))

    async def fake_aget_config(key):
        assert key == ConfigKeyEnum.WORKSTATION
        return SimpleNamespace(value=_payload(unified_runtime_enabled=True))

    monkeypatch.setattr(ws_module.ConfigDao, "aget_config", staticmethod(fake_aget_config))
    assert await is_unified_runtime_enabled(1) is True


async def test_admin_save_without_the_field_keeps_stored_switch(monkeypatch):
    """The 工作台配置 page does not know the switch; saving the page must not turn it off."""
    saved = {}

    async def fake_upsert(key, *, payload):
        saved["payload"] = payload

    async def fake_resolve(key):
        return _payload(welcomeMessage="old", unified_runtime_enabled=True), False, 5, True

    async def fake_meta():
        return WorkstationConfig(**json.loads(saved["payload"])), False, 5, True, False

    monkeypatch.setattr(WorkStationService, "_aupsert_tenant_config", fake_upsert)
    monkeypatch.setattr(WorkStationService, "_aresolve_tenant_config", fake_resolve)
    monkeypatch.setattr(WorkStationService, "get_daily_chat_config_with_meta", fake_meta)

    await WorkStationService.update_daily_chat_config(WorkstationConfig(welcomeMessage="new"))
    stored = json.loads(saved["payload"])
    assert stored["welcomeMessage"] == "new"
    assert stored["unified_runtime_enabled"] is True

    # An explicit value in the request wins.
    await WorkStationService.update_daily_chat_config(
        WorkstationConfig(welcomeMessage="new", unified_runtime_enabled=False)
    )
    assert json.loads(saved["payload"])["unified_runtime_enabled"] is False
