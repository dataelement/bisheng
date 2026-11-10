"""``pull_sync_service`` unit tests — console-triggered (manual) org sync.

The provider and the shared apply path are stubbed; what is asserted here is the
orchestration: status guards, the CAS lock, tenant pinning, and that the payload
handed to ``apply_wecom_org_snapshot`` carries the full snapshot + leader grants.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.org_sync import (
    OrgSyncAlreadyRunningError,
    OrgSyncConfigDisabledError,
    OrgSyncConfigNotFoundError,
    OrgSyncInvalidConfigError,
)
from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO
from bisheng.org_sync.domain.services import pull_sync_service as mod


def _config(**overrides):
    base = {
        "id": 7,
        "tenant_id": 1,
        "provider": "wecom",
        "status": "active",
        "sync_status": "idle",
        "auth_config": "encrypted",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeDao:
    def __init__(self, config, *, cas_ok=True):
        self.config = config
        self.cas_ok = cas_ok
        self.status_calls = []

    async def aget_by_id(self, config_id):
        return self.config

    async def aset_sync_status(self, config_id, old, new):
        self.status_calls.append((config_id, old, new))
        return self.cas_ok


class _FakeProvider:
    async def fetch_departments(self):
        return [RemoteDepartmentDTO(external_id="2", name="HQ", parent_external_id=None, sort_order=3)]

    async def fetch_members(self):
        return [
            RemoteMemberDTO(
                external_id="boss",
                name="负责人",
                primary_dept_external_id="2",
                admin_dept_external_ids=["2"],
            )
        ]


class _DeptResult:
    applied_upsert = 3
    applied_remove = 1
    errors: list = []
    skipped_ts_conflict = 0


class _ApplyResult:
    department_result = _DeptResult()
    member_sync_ok = 2
    member_sync_fail = 0
    absent_wecom_users_disabled = 1


@pytest.fixture()
def patched(monkeypatch):
    """Wire fake DAO/provider/apply; expose the captured apply kwargs."""
    captured: dict = {}

    def _install(config, *, cas_ok=True):
        dao = _FakeDao(config, cas_ok=cas_ok)
        monkeypatch.setattr(mod, "OrgSyncConfigDao", dao)
        monkeypatch.setattr(
            mod, "decrypt_auth_config", lambda _raw: {"corpid": "c", "corpsecret": "s", "agent_id": "a"}
        )

        def _get_provider(provider, auth):
            captured["provider"] = provider
            captured["auth"] = auth
            return _FakeProvider()

        async def _apply(payload, **kwargs):
            captured["payload"] = payload
            captured["apply_kwargs"] = kwargs
            return _ApplyResult()

        release = AsyncMock()
        monkeypatch.setattr(mod, "release_enqueue_lock", release)
        captured["release"] = release

        monkeypatch.setattr(mod, "get_provider", _get_provider)
        monkeypatch.setattr(mod, "apply_wecom_org_snapshot", _apply)
        return dao, captured

    return _install


async def test_happy_path_applies_full_snapshot(patched):
    dao, captured = patched(_config())

    summary = await mod.run_pull_sync(7, trigger_user=42, enqueue_token="tok-1")

    payload = captured["payload"]
    assert payload.departments.full_snapshot is True
    # Schemas validate the payload builder's dicts into typed items.
    assert payload.departments.upsert[0].external_id == "2"
    assert payload.departments.upsert[0].sort == 3
    member = payload.members[0]
    assert member.external_user_id == "boss"
    assert member.department_admin_external_ids == ["2"]
    assert member.source == "wecom"

    kwargs = captured["apply_kwargs"]
    assert kwargs["trigger_type"] == "manual"
    assert kwargs["config_id"] == 7
    assert kwargs["trigger_user"] == 42

    assert summary["dept_updated"] == 3
    assert summary["dept_archived"] == 1
    assert summary["member_ok"] == 2
    assert summary["absent_disabled"] == 1

    # CAS lock is taken and always released.
    assert dao.status_calls == [(7, "idle", "running"), (7, "running", "idle")]
    # The API's queue gate is released too, so the button unlocks on completion.
    captured["release"].assert_awaited_once_with(7, "tok-1")


async def test_unknown_provider_is_rejected(patched):
    patched(_config(provider="feishu"))
    with pytest.raises(OrgSyncInvalidConfigError):
        await mod.run_pull_sync(7)


async def test_disabled_config_is_rejected(patched):
    patched(_config(status="disabled"))
    with pytest.raises(OrgSyncConfigDisabledError):
        await mod.run_pull_sync(7)


async def test_missing_config_is_rejected(patched):
    patched(None)
    with pytest.raises(OrgSyncConfigNotFoundError):
        await mod.run_pull_sync(7)


async def test_concurrent_run_is_rejected(patched):
    patched(_config(), cas_ok=False)
    with pytest.raises(OrgSyncAlreadyRunningError):
        await mod.run_pull_sync(7)
