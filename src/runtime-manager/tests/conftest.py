"""Shared fixtures for the runtime-manager suite.

Two rules this file enforces for the whole package:

1. **No test ever needs a docker daemon.** ``fake_docker`` is installed as the
   process-wide backend for every test; anything that genuinely needs a real
   daemon carries ``@pytest.mark.docker`` and is skipped unless
   ``RTM_RUN_DOCKER_TESTS=1`` (CI middleware stage / 114 manual verification).
2. **No test ever shares state with another.** ``data_root`` is a per-test
   ``tmp_path``, and because the desired-state store and the build registry are
   cached *by path*, a fresh ``data_root`` is a fresh store — nothing to reset,
   nothing to leak.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runtime_manager.auth import compute_signature
from runtime_manager.config import Config, set_config
from runtime_manager.docker_backend import set_docker_backend
from tests.fakes import FakeDockerBackend, FakeHostProbe

TEST_SECRET = "rtm-test-secret"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``@pytest.mark.docker`` unless a real daemon was opted into."""
    if os.environ.get("RTM_RUN_DOCKER_TESTS") == "1":
        return
    skip = pytest.mark.skip(
        reason="needs a real docker daemon — CI middleware stage + 114 manual verification (set RTM_RUN_DOCKER_TESTS=1)"
    )
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip proxy env vars.

    A ``socks5://`` ``ALL_PROXY`` without ``socksio`` installed turns the whole
    file into collection ERRORs that look nothing like a proxy problem.
    """
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def tmp_data_root(tmp_path: Path) -> Path:
    root = tmp_path / "app-data"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def rtm_config(tmp_data_root: Path) -> Config:
    """Process config for a test: real defaults, test secret, isolated data root."""
    config = Config(
        hmac_secret=TEST_SECRET,
        data_root=tmp_data_root,
        network="bisheng-apps",
        reserve_mb=2048,
        overcommit_ratio=0.8,
        build_reserve_mb=2048,
        build_index_url="https://pypi.example.com/simple",
        build_trusted_host="pypi.example.com",
        # The reconcile loop is a background thread in production (D4). Tests
        # call ``reconcile_once()`` themselves so a pass can never race an
        # assertion; ``test_reconciler`` starts a real loop where that is the
        # thing under test.
        reconcile_enabled=False,
    )
    set_config(config)
    yield config
    set_config(None)


@pytest.fixture
def fake_docker(rtm_config: Config) -> FakeDockerBackend:
    backend = FakeDockerBackend(network=rtm_config.network)
    set_docker_backend(backend)
    yield backend
    set_docker_backend(None)


@pytest.fixture
def fake_meminfo() -> FakeHostProbe:
    """Injectable ``MemAvailable`` / ``MemTotal`` / ``nproc`` (K2)."""
    return FakeHostProbe()


class SignedClient:
    """TestClient wrapper that signs exactly the bytes it sends.

    The body is serialised here — not handed to httpx as ``json=`` — because the
    signature covers the raw bytes, and httpx's JSON separators have changed
    between releases. Signing what we literally send removes that whole class of
    flake.
    """

    def __init__(self, client: TestClient, secret: str = TEST_SECRET) -> None:
        self.client = client
        self.secret = secret

    def _headers(self, method: str, path: str, body: bytes, secret: str | None) -> dict[str, str]:
        signature = compute_signature(method, path, body, secret if secret is not None else self.secret)
        headers = {"X-Signature": signature}
        if body:
            headers["content-type"] = "application/json"
        return headers

    def post(self, path: str, payload: dict[str, Any] | None = None, *, secret: str | None = None, sign: bool = True):
        body = json.dumps(payload or {}).encode()
        headers = self._headers("POST", path, body, secret) if sign else {"content-type": "application/json"}
        return self.client.post(path, content=body, headers=headers)

    def get(self, path: str, params: dict[str, Any] | None = None, *, secret: str | None = None, sign: bool = True):
        headers = self._headers("GET", path, b"", secret) if sign else {}
        return self.client.get(path, params=params, headers=headers)


@pytest.fixture
def rtm_client(rtm_config: Config, fake_docker: FakeDockerBackend) -> SignedClient:
    from runtime_manager.main import app

    with TestClient(app) as client:
        yield SignedClient(client)
