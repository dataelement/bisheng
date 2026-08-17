"""T034 — the internal app-proxy endpoints, over real HTTP.

The service-level verdict logic is ``test_entry_authz_service.py``. What this
file owns is the *wire*: that only a correctly signed caller reaches it, that a
business verdict is never mistaken for a transport failure, and that the answer
carries identity but not topology.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

pytestmark = pytest.mark.usefixtures("app_db")

PROXY_SECRET = "f054-proxy-secret"
AUTHORIZE_PATH = "/api/v1/internal/app-proxy/authorize"


@pytest.fixture()
def proxy_settings(monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "enabled", True, raising=False)
    monkeypatch.setattr(settings.app_runtime, "proxy_hmac_secret", PROXY_SECRET, raising=False)
    monkeypatch.setattr(settings.app_runtime, "obo_secret", "f054-obo-secret", raising=False)
    return settings


@pytest.fixture()
def stub_verdict(monkeypatch):
    """Program the entry verdict; the endpoint is what is under test here."""
    from bisheng.app_runtime.api.endpoints import internal_app_proxy

    state = {"verdict": {"decision": "not_found"}, "calls": []}

    async def _authorize(**kwargs):
        state["calls"].append(kwargs)
        return state["verdict"]

    monkeypatch.setattr(internal_app_proxy, "authorize_entry", _authorize)
    return state


async def _signed(client, body: dict, *, secret: str = PROXY_SECRET):
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), b"POST\n" + AUTHORIZE_PATH.encode() + b"\n" + raw, hashlib.sha256).hexdigest()
    return await client.post(
        AUTHORIZE_PATH,
        content=raw,
        headers={"X-Signature": signature, "Content-Type": "application/json"},
    )


class TestHmac:
    async def test_hmac_required_and_constant_time(self, api_app, proxy_settings, stub_verdict):
        """Unsigned and mis-signed callers are 401 — and a 401 must mean *that*.

        app-proxy treats a 401 as "our own deployment is broken", never as "this
        visitor is forbidden"; a business refusal comes back as HTTP 200 with a
        ``decision`` (see ``test_business_verdicts_are_http_200``).
        """
        import inspect

        from bisheng.app_runtime.domain.services import hmac_auth

        client = api_app()
        assert (await client.post(AUTHORIZE_PATH, json={"slug": "x"})).status_code == 401
        assert (await _signed(client, {"slug": "x"}, secret="wrong-secret")).status_code == 401
        assert (await _signed(client, {"slug": "x"})).status_code == 200

        # The header is attacker supplied: a byte-wise ``==`` leaks the matching
        # prefix length through timing.
        assert "compare_digest" in inspect.getsource(hmac_auth.verify_proxy_hmac)

    async def test_empty_secret_fails_closed(self, api_app, proxy_settings, stub_verdict, monkeypatch):
        """A rollout that forgot the secret must not accept unsigned identity requests."""
        from bisheng.common.services.config_service import settings

        monkeypatch.setattr(settings.app_runtime, "proxy_hmac_secret", "", raising=False)
        assert (await _signed(api_app(), {"slug": "x"}, secret="")).status_code == 401

    async def test_path_in_tenant_check_exempt(self):
        """No JWT rides on this request, so the tenant ContextVar is unset; without
        the exemption every tenant-aware DAO in the call tree would raise."""
        import inspect

        from bisheng.app_runtime.api.endpoints import internal_app_proxy
        from bisheng.utils.http_middleware import TENANT_CHECK_EXEMPT_PATHS

        assert AUTHORIZE_PATH.startswith(TENANT_CHECK_EXEMPT_PATHS)
        assert "/api/v1/apps/_unavailable".startswith(TENANT_CHECK_EXEMPT_PATHS)
        assert "bypass_tenant_filter" in inspect.getsource(internal_app_proxy.authorize)


class TestVerdictSurface:
    @pytest.mark.parametrize(
        "verdict",
        [
            {"decision": "allow", "headers": {"X-BiSheng-User-Id": "1"}, "obo_token": "t"},
            {"decision": "login"},
            {"decision": "forbidden", "app_name": "A", "owner_name": "O"},
            {"decision": "stopped", "app_name": "A"},
            {"decision": "not_found"},
            {"decision": "not_enabled"},
        ],
    )
    async def test_decision_matrix_end_to_end(self, api_app, proxy_settings, stub_verdict, verdict):
        """All six verdicts travel as HTTP 200 + envelope — see the class above for why."""
        stub_verdict["verdict"] = verdict
        response = await _signed(api_app(), {"slug": "s", "access_token": "tok", "request_id": "r"})

        assert response.status_code == 200
        body = response.json()
        assert body["status_code"] == 200
        assert body["data"]["decision"] == verdict["decision"]

    async def test_request_fields_reach_the_service(self, api_app, proxy_settings, stub_verdict):
        await _signed(api_app(), {"slug": "s", "access_token": "tok", "request_id": "r-9", "client_ip": "10.0.0.1"})
        assert stub_verdict["calls"] == [
            {"slug": "s", "access_token": "tok", "request_id": "r-9", "client_ip": "10.0.0.1"}
        ]

    async def test_response_contains_no_upstream_address(self, api_app, proxy_settings, stub_verdict):
        """D5.1 — where the app runs is runtime-manager's answer, on its own cache
        clock. One response carrying both would make "revoke access" and "switch
        version" invalidate each other."""
        stub_verdict["verdict"] = {
            "decision": "allow",
            "app_id": "app-1",
            "headers": {"X-BiSheng-User-Id": "1"},
            "obo_token": "t",
        }
        body = (await _signed(api_app(), {"slug": "s", "access_token": "tok"})).json()

        serialized = json.dumps(body)
        for leak in ("upstream", "generation", "container", "http://172.", ":8080"):
            assert leak not in serialized

    async def test_obo_returned_on_allow_only(self, api_app, proxy_settings, stub_verdict):
        """AC-34 — a refused visitor never receives a signed identity token."""
        stub_verdict["verdict"] = {"decision": "allow", "headers": {}, "obo_token": "signed"}
        assert (await _signed(api_app(), {"slug": "s"})).json()["data"]["obo_token"] == "signed"

        stub_verdict["verdict"] = {"decision": "forbidden", "app_name": "A"}
        assert (await _signed(api_app(), {"slug": "s"})).json()["data"].get("obo_token") is None


class TestUnavailablePage:
    async def test_unavailable_page_endpoint_returns_html_200(self, api_app):
        """AC-30 — nginx's ``error_page`` fallback when app-proxy itself is down.

        Serving one static page from backend does not violate K1: there is no
        orchestration in a string. It carries no scripts or external assets
        because it is shown exactly when something is already broken.
        """
        response = await api_app().get("/api/v1/apps/_unavailable")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "应用" in response.text
        assert "<script" not in response.text and "http://" not in response.text
