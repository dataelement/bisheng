"""F120 — WeCom OAuth client (authorize URL, code exchange, member read)."""

import pytest

from bisheng.common.errcode.sso_sync import (
    WeComSsoCodeInvalidError,
    WeComSsoUpstreamError,
)
from bisheng.sso_sync.domain.services import wecom_oauth_client as mod
from bisheng.sso_sync.domain.services.wecom_oauth_client import (
    WeComOAuthClient,
    build_authorize_url,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def http(monkeypatch):
    state = {"responses": [], "calls": []}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            state["calls"].append((url, params))
            if not state["responses"]:
                raise AssertionError(f"unexpected HTTP call: {url}")
            return _FakeResponse(state["responses"].pop(0))

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    return state


@pytest.fixture
def token_cache(monkeypatch):
    store: dict[str, str] = {}

    class _Conn:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ex=None):
            store[key] = value

    class _Client:
        async_connection = _Conn()

    async def _get_redis_client():
        return _Client()

    monkeypatch.setattr(mod, "get_redis_client", _get_redis_client)
    return store


def _token_ok() -> dict:
    return {"errcode": 0, "access_token": "tok-1", "expires_in": 7200}


def test_build_authorize_url_silent():
    url = build_authorize_url(
        mode="silent",
        corpid="ww123",
        agent_id="100001",
        redirect_uri="https://app.example.com/api/v1/user/wecom/callback",
        state="st-1",
    )
    assert url.startswith(mod.WECOM_INAPP_AUTHORIZE_URL)
    assert "appid=ww123" in url
    assert "agentid=100001" in url
    assert "scope=snsapi_base" in url
    assert "state=st-1" in url
    assert url.endswith("#wechat_redirect")


def test_build_authorize_url_qr():
    url = build_authorize_url(
        mode="qr",
        corpid="ww123",
        agent_id="100001",
        redirect_uri="https://app.example.com/cb",
        state="st-1",
    )
    assert url.startswith(mod.WECOM_QR_AUTHORIZE_URL)
    assert "login_type=CorpApp" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcb" in url


async def test_exchange_code_returns_userid_and_caches_token(http, token_cache):
    http["responses"] = [_token_ok(), {"errcode": 0, "userid": "zhangsan"}]
    client = WeComOAuthClient(corpid="ww123", corpsecret="s", agent_id="1", config_id=7)

    userid = await client.exchange_code("code-1")

    assert userid == "zhangsan"
    assert token_cache["org_sync:wecom:token:7"] == "tok-1"
    assert http["calls"][0][0].endswith("/cgi-bin/gettoken")
    assert http["calls"][1][0].endswith("/cgi-bin/auth/getuserinfo")


async def test_exchange_code_uses_cached_token(http, token_cache):
    token_cache["org_sync:wecom:token:7"] = "cached-token"
    http["responses"] = [{"errcode": 0, "userid": "lisi"}]
    client = WeComOAuthClient(corpid="ww123", corpsecret="s", agent_id="1", config_id=7)

    assert await client.exchange_code("code-2") == "lisi"
    assert http["calls"][0][1]["access_token"] == "cached-token"
    assert len(http["calls"]) == 1


async def test_exchange_code_rejects_bad_code(http, token_cache):
    http["responses"] = [_token_ok(), {"errcode": 40029, "errmsg": "invalid code"}]
    client = WeComOAuthClient(corpid="ww123", corpsecret="s", agent_id="1", config_id=7)

    with pytest.raises(WeComSsoCodeInvalidError):
        await client.exchange_code("bad")


async def test_exchange_code_without_userid_is_upstream_failure(http, token_cache):
    # WeCom answers with only ``openid`` when the member is outside the app's
    # visible range — a configuration problem, not a retryable bad code.
    http["responses"] = [_token_ok(), {"errcode": 0, "openid": "o-1"}]
    client = WeComOAuthClient(corpid="ww123", corpsecret="s", agent_id="1", config_id=7)

    with pytest.raises(WeComSsoUpstreamError):
        await client.exchange_code("code-3")


async def test_fetch_member_maps_primary_and_secondary_departments(http, token_cache):
    http["responses"] = [
        _token_ok(),
        {
            "errcode": 0,
            "userid": "zhangsan",
            "name": "张三",
            "email": "z@example.com",
            "mobile": "13800000000",
            "department": [1, 2, 3],
            "main_department": 2,
        },
    ]
    client = WeComOAuthClient(corpid="ww123", corpsecret="s", agent_id="1", config_id=7)

    member = await client.fetch_member("zhangsan")

    assert member is not None
    assert member.primary_dept_id == "2"
    assert member.secondary_dept_ids == ("1", "3")
    assert member.name == "张三"


async def test_fetch_member_without_department(http, token_cache):
    http["responses"] = [_token_ok(), {"errcode": 0, "userid": "zhangsan", "name": "张三"}]
    client = WeComOAuthClient(corpid="ww123", corpsecret="s", agent_id="1", config_id=7)

    member = await client.fetch_member("zhangsan")

    assert member is not None
    assert member.primary_dept_id is None
    assert member.secondary_dept_ids == ()


async def test_fetch_member_degrades_on_contact_permission_error(http, token_cache):
    http["responses"] = [_token_ok(), {"errcode": 60111, "errmsg": "user not found"}]
    client = WeComOAuthClient(corpid="ww123", corpsecret="s", agent_id="1", config_id=7)

    assert await client.fetch_member("zhangsan") is None


async def test_fetch_member_raises_on_broken_credentials(http, token_cache):
    http["responses"] = [_token_ok(), {"errcode": 60011, "errmsg": "no permission"}]
    client = WeComOAuthClient(corpid="ww123", corpsecret="s", agent_id="1", config_id=7)

    with pytest.raises(WeComSsoUpstreamError):
        await client.fetch_member("zhangsan")
