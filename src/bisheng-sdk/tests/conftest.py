"""Shared fixtures. Four rules this file enforces for the whole package.

1. **No test ever touches the network.** `no_network` swaps httpx's real
   transport for a sentinel that raises, so a forgotten mock fails at the call
   site instead of quietly reaching out to whatever host the test named.
2. **No test ever sees the developer's own environment.** Every `BISHENG_*`
   variable is cleared: a developer with `BISHENG_APP_STORAGE_DIR` exported
   would otherwise get a different verdict from the same test than CI does.
3. **No test leaks request context into the next one.** The identity lives in a
   `ContextVar`; one test that forgets to reset would hand its user to the next.
4. **No long credential literal is ever written into a `.py` file** —
   `scripts/arch-guard.sh` RULE-7 greps for exactly that, and a permanent stream
   of false warnings is how a real leak gets scrolled past. Fakes are assembled
   by concatenation in `tests/helpers/platform_mock.py`.
"""

from __future__ import annotations

import os

import httpx
import pytest

from bisheng_sdk import _compat, _context, _http

_PROXY_ENV = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `@pytest.mark.network` unless a real platform was opted into."""
    if os.environ.get("BISHENG_SDK_RUN_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(
        reason="needs a real platform — 114 manual verification only (set BISHENG_SDK_RUN_NETWORK_TESTS=1)"
    )
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROXY_ENV:
        monkeypatch.delenv(name, raising=False)

    def _refuse(self, request):
        raise AssertionError(f"unmocked network call: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse, raising=True)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse, raising=True)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer machine's own `BISHENG_*` must not decide a test's verdict."""
    for name in list(os.environ):
        if name.startswith("BISHENG_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """Request context, client pool and the version probe cache are per-test."""
    _http.reset_clients()
    _compat.reset()
    _context.clear()
    yield
    _http.reset_clients()
    _compat.reset()
    _context.clear()


@pytest.fixture
def platform_env(monkeypatch: pytest.MonkeyPatch) -> str:
    from tests.helpers.platform_mock import PLATFORM_BASE

    monkeypatch.setenv("BISHENG_PLATFORM_API_BASE", PLATFORM_BASE)
    return PLATFORM_BASE


@pytest.fixture
def app_token_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """The application's own runtime credential, as F055 injects it."""
    from tests.helpers.platform_mock import FAKE_APP_TOKEN

    monkeypatch.setenv("BISHENG_APP_TOKEN", FAKE_APP_TOKEN)
    return FAKE_APP_TOKEN


@pytest.fixture
def mock_transport(monkeypatch: pytest.MonkeyPatch):
    """Install a `httpx.MockTransport` behind the SDK's client pool.

    Patching the pool factories rather than passing a transport parameter keeps
    the production code free of a test-only hook — and still exercises the real
    `request` / `parse_envelope` path.
    """

    def install(transport):
        def _client(base_url: str, kind: str = "retrieve") -> httpx.Client:
            return httpx.Client(base_url=base_url, transport=transport.sync, timeout=_http.timeout_for(kind))

        def _aclient(base_url: str, kind: str = "retrieve") -> httpx.AsyncClient:
            return httpx.AsyncClient(base_url=base_url, transport=transport.asgi, timeout=_http.timeout_for(kind))

        monkeypatch.setattr(_http, "client", _client)
        monkeypatch.setattr(_http, "aclient", _aclient)
        return transport

    return install
