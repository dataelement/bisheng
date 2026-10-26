"""The address the backend writes into skill packs must be the browser-facing one."""

import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from starlette.requests import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings
from bisheng.core.config.open_platform import OpenApiConf
from bisheng.open_api.api.endpoints import personal_token_self, skill_pack
from bisheng.open_api.domain.services import public_base_url as resolver_module
from bisheng.open_api.domain.services.public_base_url import resolve_public_base_url

PACK_PATH = "/api/v1/open-api/skill-packs/knowledge-search"


class _Warnings:
    def __init__(self):
        self.messages: list[str] = []

    def warning(self, message, *args, **_kwargs):
        self.messages.append(message.format(*args))


@pytest.fixture(autouse=True)
def _no_configured_url(monkeypatch):
    monkeypatch.setattr(settings.open_api, "public_base_url", "")
    resolver_module._WARNED.clear()


@pytest.fixture
def warnings(monkeypatch):
    sink = _Warnings()
    monkeypatch.setattr(resolver_module, "logger", sink)
    return sink


def _request(headers=None, *, scheme="http", server=("10.0.0.5", 7860), root_path=""):
    raw = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": raw,
        "scheme": scheme,
        "server": server,
        "root_path": root_path,
    }
    return Request(scope)


# ── resolution order ─────────────────────────────────────────────────────────


def test_forwarded_headers_win_over_the_upstream_hop():
    request = _request(
        {"Host": "backend:7860", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "kb.example.com:8443"}
    )
    assert resolve_public_base_url(request) == "https://kb.example.com:8443"


def test_first_value_of_a_proxy_chain_is_the_public_one():
    # Spring Cloud Gateway appends its own view: "https,http" / "kb, gateway:8080".
    request = _request(
        {"Host": "backend:7860", "X-Forwarded-Proto": "https,http", "X-Forwarded-Host": "kb.example.com, gateway:8080"}
    )
    assert resolve_public_base_url(request) == "https://kb.example.com"


def test_host_header_keeps_its_port_when_nothing_is_forwarded():
    assert resolve_public_base_url(_request({"Host": "192.168.1.10:3001"})) == "http://192.168.1.10:3001"


def test_unknown_scheme_falls_back_to_the_connection_scheme():
    request = _request({"Host": "kb.example.com", "X-Forwarded-Proto": "gopher"}, scheme="https")
    assert resolve_public_base_url(request) == "https://kb.example.com"


@pytest.mark.parametrize(
    "bad",
    ['kb".exec(', "kb.example.com/evil", "kb example.com", "kb.example.com:99999x", "<script>", "kb\\example"],
)
def test_hosts_that_could_break_generated_files_are_rejected(bad):
    # X-Forwarded-Host is rejected and the Host header is used instead...
    assert (
        resolve_public_base_url(_request({"Host": "kb.example.com", "X-Forwarded-Host": bad}))
        == "http://kb.example.com"
    )
    # ...and a bad Host header falls back to the bound socket, never to the raw value.
    assert resolve_public_base_url(_request({"Host": bad})) == "http://10.0.0.5:7860"


def test_ipv6_literals_and_root_path_are_preserved():
    assert resolve_public_base_url(_request({"Host": "[::1]:7860"})) == "http://[::1]:7860"
    assert (
        resolve_public_base_url(_request({"Host": "kb.example.com"}, root_path="/bisheng/"))
        == "http://kb.example.com/bisheng"
    )
    assert resolve_public_base_url(_request(server=("::1", 7860))) == "http://[::1]:7860"


def test_configured_public_base_url_beats_every_header(monkeypatch):
    monkeypatch.setattr(settings.open_api, "public_base_url", "https://portal.example.com/bisheng/")
    request = _request({"Host": "backend:7860", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "kb.example.com"})
    assert resolve_public_base_url(request) == "https://portal.example.com/bisheng"


# ── the setting is validated at boot ─────────────────────────────────────────


def test_public_base_url_setting_is_normalised_and_validated():
    assert OpenApiConf().public_base_url == ""
    assert OpenApiConf(public_base_url=" https://kb.example.com/ ").public_base_url == "https://kb.example.com"
    assert (
        OpenApiConf(public_base_url="https://portal.example.com/bisheng").public_base_url
        == "https://portal.example.com/bisheng"
    )
    for bad in ("kb.example.com", "ftp://kb.example.com", "https://", "https://kb.example.com/?x=1"):
        with pytest.raises(ValidationError):
            OpenApiConf(public_base_url=bad)


# ── endpoints ────────────────────────────────────────────────────────────────


def _app() -> FastAPI:
    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(skill_pack.router)
    api.include_router(personal_token_self.router)
    app.include_router(api)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=1, tenant_id=1)
    return app


async def _download(app: FastAPI, headers: dict | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://backend:7860") as client:
        return await client.get(PACK_PATH, headers=headers)


def _rendered(response) -> dict[str, str]:
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    return {name.rsplit("/", 1)[-1]: archive.read(name).decode("utf-8") for name in archive.namelist()}


async def test_pack_bakes_the_browser_facing_address_from_proxy_headers():
    response = await _download(_app(), {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "kb.example.com:8443"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    files = _rendered(response)
    assert "Base URL: `https://kb.example.com:8443`" in files["SKILL.md"]
    assert "`https://kb.example.com:8443`" in files["SECURITY.md"]  # outbound allow-list, same origin
    assert 'DEFAULT_BASE_URL = "https://kb.example.com:8443"' in files["search.py"]
    assert "https://kb.example.com:8443" in files["api.md"]
    assert "backend:7860" not in "".join(files.values())  # the upstream hop never leaks


async def test_pack_without_proxy_headers_still_uses_the_host_header():
    files = _rendered(await _download(_app()))
    assert 'DEFAULT_BASE_URL = "http://backend:7860"' in files["search.py"]


async def test_pack_uses_the_configured_address_when_set(monkeypatch):
    monkeypatch.setattr(settings.open_api, "public_base_url", "https://portal.example.com/bisheng")
    files = _rendered(await _download(_app(), {"X-Forwarded-Host": "kb.example.com"}))
    assert 'DEFAULT_BASE_URL = "https://portal.example.com/bisheng"' in files["search.py"]
    assert "`https://portal.example.com`" in files["SECURITY.md"]  # origin only, path stripped
    assert "kb.example.com" not in "".join(files.values())


async def test_install_prompt_points_at_the_same_public_address():
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://backend:7860") as client:
        response = await client.get(
            "/api/v1/me/api-token/install-prompt",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "kb.example.com:8443"},
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["skill_pack_url"] == f"https://kb.example.com:8443{PACK_PATH}"
    assert data["skill_pack_url"] in data["prompt"]


# ── operators get a signal when the address was guessed from the last hop ────


def test_host_header_fallback_warns_once_per_process(warnings):
    resolve_public_base_url(_request({"Host": "backend:7860"}))
    resolve_public_base_url(_request({"Host": "backend:7860"}))
    assert len(warnings.messages) == 1
    assert "http://backend:7860" in warnings.messages[0] and "Host header" in warnings.messages[0]
    assert "open_api.public_base_url" in warnings.messages[0]


def test_socket_fallback_warns_separately(warnings):
    resolve_public_base_url(_request({"Host": "backend:7860"}))
    resolve_public_base_url(_request({"Host": "bad host"}))
    assert len(warnings.messages) == 2
    assert "http://10.0.0.5:7860" in warnings.messages[1] and "server socket" in warnings.messages[1]


def test_forwarded_or_configured_addresses_do_not_warn(warnings, monkeypatch):
    resolve_public_base_url(_request({"Host": "backend:7860", "X-Forwarded-Host": "kb.example.com"}))
    monkeypatch.setattr(settings.open_api, "public_base_url", "https://kb.example.com")
    resolve_public_base_url(_request({"Host": "backend:7860"}))
    assert warnings.messages == []
