"""Shared wiring: real app, real HMAC, fake peers.

Two deliberate choices worth knowing before adding a test here:

* **Every fixture body imports lazily.** The suite is written test-first, so at
  any point during Wave 2 some ``app_proxy.*`` module does not exist yet. A
  top-level import would make the *whole package* fail collection and hide the
  one test that was supposed to be red.
* **``HTTP(S)_PROXY`` is scrubbed autouse.** Without ``socksio`` installed, a
  developer's ``ALL_PROXY`` turns every httpx call in the suite into a
  collection-time ERROR that looks nothing like a proxy problem.
"""

from __future__ import annotations

import os

import httpx
import pytest

from tests.fakes import EchoUpstream, FakeBackend, FakeManager, FrozenClock, UpstreamTransport

BACKEND_SECRET = "backend-secret-for-tests"
MANAGER_SECRET = "manager-secret-for-tests"
BACKEND_BASE = "http://backend.test"
MANAGER_BASE = "http://manager.test"

#: Headers a browser sends on a top-level navigation. The page / handoff branch
#: keys off exactly these (D7).
NAVIGATE_HEADERS = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", "Accept": "text/html"}
#: Headers an in-app ``fetch()`` sends. Must never receive HTML.
XHR_HEADERS = {"Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty", "Accept": "application/json"}


@pytest.fixture(autouse=True)
def _no_proxy_env(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
        os.environ.pop(name, None)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend(BACKEND_SECRET)


@pytest.fixture
def fake_manager() -> FakeManager:
    return FakeManager(MANAGER_SECRET)


@pytest.fixture
def echo_upstream() -> EchoUpstream:
    return EchoUpstream()


@pytest.fixture
def upstream_transport(echo_upstream) -> UpstreamTransport:
    from tests.fakes import DEFAULT_UPSTREAM

    transport = UpstreamTransport()
    transport.register(DEFAULT_UPSTREAM, echo_upstream)
    return transport


@pytest.fixture(autouse=True)
def wired(fake_backend, fake_manager, upstream_transport, frozen_clock):
    """Point the process at the fakes, then put it back.

    Autouse because a test that forgot it would silently reach for
    ``127.0.0.1:7860`` and fail with a connection error three layers away from
    the cause.
    """
    from app_proxy import clients
    from app_proxy.config import Config, set_config

    config = Config(
        backend_base=BACKEND_BASE,
        manager_base=MANAGER_BASE,
        backend_secret=BACKEND_SECRET,
        manager_secret=MANAGER_SECRET,
    )
    set_config(config)

    backend_client = clients.BackendAuthzClient(
        BACKEND_BASE,
        BACKEND_SECRET,
        ttl_seconds=config.authz_ttl_seconds,
        clock=frozen_clock,
        transport=httpx.ASGITransport(app=fake_backend),
    )
    manager_client = clients.ManagerRouteClient(
        MANAGER_BASE,
        MANAGER_SECRET,
        ttl_seconds=config.route_ttl_seconds,
        clock=frozen_clock,
        transport=httpx.ASGITransport(app=fake_manager),
    )
    clients.set_clients(backend_client, manager_client)

    try:
        from app_proxy import proxy

        proxy.set_upstream_transport(upstream_transport)
    except ImportError:  # pragma: no cover - only before T045 lands
        proxy = None

    yield config

    clients.set_clients(None, None)
    set_config(None)
    if proxy is not None:
        proxy.set_upstream_transport(None)


@pytest.fixture
def proxy_client(wired):
    """``TestClient`` over the real ASGI app.

    Not used as a context manager on purpose: running the lifespan would close
    the fake-backed clients that ``wired`` just installed.
    """
    from starlette.testclient import TestClient

    from app_proxy.main import app

    return TestClient(app)


@pytest.fixture
def logged_in(proxy_client):
    """A client carrying the platform session cookie (host-only, ``path=/``)."""
    proxy_client.cookies.set("access_token_cookie", "jwt-token-for-tests")
    return proxy_client
