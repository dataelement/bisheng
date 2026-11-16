"""F120 — WeCom login orchestration (availability / authorize / callback)."""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.sso_sync import (
    WeComSsoNotConfiguredError,
    WeComSsoUpstreamError,
)
from bisheng.core.config.sso_sync import WeComSSOConf
from bisheng.sso_sync.domain.schemas.payloads import LoginSyncResponse
from bisheng.sso_sync.domain.services import wecom_login_service as mod
from bisheng.sso_sync.domain.services.wecom_login_service import (
    WeComLoginConfig,
    WeComLoginService,
)
from bisheng.sso_sync.domain.services.wecom_login_state import WeComLoginState
from bisheng.sso_sync.domain.services.wecom_oauth_client import WeComMember

PUBLIC_ORIGIN = "https://app.example.com"
CONFIG = WeComLoginConfig(config_id=7, corpid="ww123", corpsecret="secret", agent_id="100001")


def _fake_settings(*, pro: bool = False, wecom: WeComSSOConf | None = None):
    return SimpleNamespace(
        sso_sync=SimpleNamespace(wecom=wecom or WeComSSOConf()),
        get_system_login_method=lambda: SimpleNamespace(bisheng_pro=pro),
    )


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setattr(mod, "settings", _fake_settings())

    async def _load_config():
        return CONFIG

    monkeypatch.setattr(WeComLoginService, "_load_config", classmethod(lambda cls: _load_config()))

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(WeComLoginService, "_write_login_audit", _noop)
    monkeypatch.setattr(WeComLoginService, "_write_org_sync_log", _noop)
    return mod


class _FakeWeComClient:
    def __init__(self, *, userid: str = "zhangsan", member: WeComMember | None = None, error=None):
        self._userid = userid
        self._member = member
        self._error = error

    async def exchange_code(self, code: str) -> str:
        if self._error is not None:
            raise self._error
        return self._userid

    async def fetch_member(self, userid: str):
        return self._member


def _bind_client(monkeypatch, client) -> None:
    monkeypatch.setattr(WeComLoginConfig, "client", lambda self: client)


# ---------------------------------------------------------------------------
# availability
# ---------------------------------------------------------------------------


async def test_availability_disabled_when_gateway_deployment(svc, monkeypatch):
    monkeypatch.setattr(mod, "settings", _fake_settings(pro=True))
    assert await WeComLoginService.availability("wxwork/4.1") == {
        "enabled": False,
        "mode": None,
        "login_path": None,
    }


async def test_availability_disabled_without_config(svc, monkeypatch):
    async def _raise(cls):
        raise WeComSsoNotConfiguredError()

    monkeypatch.setattr(WeComLoginService, "_load_config", classmethod(_raise))
    assert (await WeComLoginService.availability(None))["enabled"] is False


async def test_availability_mode_follows_user_agent(svc):
    data = await WeComLoginService.availability("Mozilla/5.0 wxwork/4.1.10")
    assert data == {"enabled": True, "mode": "silent", "login_path": "/api/v1/user/wecom/authorize"}

    data = await WeComLoginService.availability("Mozilla/5.0 Chrome/120")
    assert data["mode"] == "qr"


# ---------------------------------------------------------------------------
# return_to validation
# ---------------------------------------------------------------------------


def test_return_to_same_origin_is_kept(svc):
    target = f"{PUBLIC_ORIGIN}/build/apps"
    assert WeComLoginService._safe_return_to(target, PUBLIC_ORIGIN) == target


def test_return_to_foreign_origin_falls_back(svc):
    assert WeComLoginService._safe_return_to("https://evil.example.net/x", PUBLIC_ORIGIN) == f"{PUBLIC_ORIGIN}/"


def test_return_to_relative_path_falls_back(svc):
    assert WeComLoginService._safe_return_to("/build/apps", PUBLIC_ORIGIN) == f"{PUBLIC_ORIGIN}/"


def test_return_to_allowed_origin_is_kept(monkeypatch):
    wecom = WeComSSOConf(allowed_return_origins=["https://client.example.com"])
    monkeypatch.setattr(mod, "settings", _fake_settings(wecom=wecom))
    target = "https://client.example.com/workspace/c/new"
    assert WeComLoginService._safe_return_to(target, PUBLIC_ORIGIN) == target


# ---------------------------------------------------------------------------
# payload assembly
# ---------------------------------------------------------------------------


async def _known_departments(known):
    async def _probe(external_ids):
        return {e for e in external_ids if e in known}

    return _probe


async def test_build_payload_binds_known_departments(svc, monkeypatch):
    monkeypatch.setattr(
        WeComLoginService,
        "_existing_departments",
        staticmethod(await _known_departments({"2", "3"})),
    )
    member = WeComMember(
        userid="zhangsan",
        name="张三",
        email="z@example.com",
        phone=None,
        primary_dept_id="2",
        secondary_dept_ids=("1", "3"),
    )

    payload = await WeComLoginService._build_payload("zhangsan", member)

    assert payload.source == "wecom"
    assert payload.primary_dept_external_id == "2"
    assert payload.secondary_dept_external_ids == ["3"]
    assert payload.user_attrs.name == "张三"


async def test_build_payload_degrades_when_department_unsynced(svc, monkeypatch):
    monkeypatch.setattr(
        WeComLoginService,
        "_existing_departments",
        staticmethod(await _known_departments(set())),
    )
    member = WeComMember(
        userid="zhangsan",
        name="张三",
        email=None,
        phone=None,
        primary_dept_id="2",
        secondary_dept_ids=(),
    )

    payload = await WeComLoginService._build_payload("zhangsan", member)

    assert payload.primary_dept_external_id is None
    # A disabled account must never be re-enabled by a login: the field tells
    # LoginSyncService to flip ``delete`` back to 0 (design §5 item 1).
    assert "account_disabled" not in payload.model_fields_set


async def test_build_payload_without_member_detail(svc):
    payload = await WeComLoginService._build_payload("zhangsan", None)
    assert payload.primary_dept_external_id is None
    assert "account_disabled" not in payload.model_fields_set


# ---------------------------------------------------------------------------
# callback
# ---------------------------------------------------------------------------


@pytest.fixture
def callback_env(svc, monkeypatch):
    state = SimpleNamespace(return_to=f"{PUBLIC_ORIGIN}/build/apps", executed={})

    async def _consume(state_value):
        return WeComLoginState(mode="qr", return_to=state.return_to)

    monkeypatch.setattr(mod.WeComLoginStateStore, "consume", _consume)
    _bind_client(monkeypatch, _FakeWeComClient())

    async def _probe(external_ids):
        return set()

    monkeypatch.setattr(WeComLoginService, "_existing_departments", staticmethod(_probe))

    async def _execute(cls, payload, request_ip="", row_source="sso", bootstrap_first_user_admin=False):
        state.executed = {
            "payload": payload,
            "row_source": row_source,
            "bootstrap": bootstrap_first_user_admin,
        }
        return LoginSyncResponse(user_id=42, leaf_tenant_id=1, token="jwt-token")

    monkeypatch.setattr(mod.LoginSyncService, "execute", classmethod(_execute))
    return state


async def test_callback_completes_login_through_login_sync(callback_env):
    return_to, token = await WeComLoginService.callback(code="c1", state="s1", request_ip="10.0.0.1")

    assert return_to == f"{PUBLIC_ORIGIN}/build/apps"
    assert token == "jwt-token"
    executed = callback_env.executed
    assert executed["payload"].external_user_id == "zhangsan"
    assert executed["payload"].source == "wecom"
    assert executed["row_source"] == "wecom"
    assert executed["bootstrap"] is True


async def test_callback_surfaces_disabled_account(callback_env, monkeypatch):
    async def _execute(cls, payload, request_ip="", row_source="sso", bootstrap_first_user_admin=False):
        return LoginSyncResponse(user_id=42, leaf_tenant_id=1, token="")

    monkeypatch.setattr(mod.LoginSyncService, "execute", classmethod(_execute))

    with pytest.raises(WeComSsoUpstreamError):
        await WeComLoginService.callback(code="c1", state="s1", request_ip="10.0.0.1")
