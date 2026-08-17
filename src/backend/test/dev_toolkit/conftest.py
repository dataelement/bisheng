"""Shared fixtures for the dev_toolkit (F053) test package.

The two endpoints under test are **anonymous** (design D10), so nothing here
seeds users, credentials or a database — the whole point of the feature is that
a developer can reach it before they hold a key.

Two things do need controlling, and both are process-level state:

* ``settings.open_platform.enabled`` decides whether the router is registered at
  all (AC-05 lands as *no route*, not as an error code). The include happens at
  import time of ``bisheng.api.router``, so switching it means reloading that
  module and handing the freshly built router to ``create_app``.
* ``ARTIFACTS_DIR`` points at build output that a plain checkout does not have
  (``scripts/pack_cli_wheel.sh`` produces it). Tests that need artifacts stage
  their own; the degradation test points the module at an empty directory.

Proxy env: the repo-wide ``test/conftest.py`` has no proxy handling, and a stray
``ALL_PROXY=socks://`` makes the httpx-based TestClient fail on a missing
``socksio``, turning the whole package into ERRORs. ``_clear_proxy_env`` strips
the six variables for every test here.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

_PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")

# Deliberately different from ``bisheng.__version__`` ('2.6.0-fix', hardcoded in
# source) so a test can prove the payload does not fall back to it (pit 21).
MANIFEST_PLATFORM_VERSION = "3.0.0-from-manifest"
CLI_VERSION = "3.0.0"
CLI_MIN_COMPATIBLE = "3.0.0"
WHEEL_NAME = f"bisheng_cli-{CLI_VERSION}-py3-none-any.whl"
WHEEL_BYTES = b"PK\x03\x04 not a real wheel, only its bytes matter for Content-Length"


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch):
    """Strip proxy variables — see module docstring (missing socksio → whole batch ERROR)."""
    for key in _PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def _artifact_service():
    return importlib.import_module("bisheng.dev_toolkit.domain.services.artifact_service")


@pytest.fixture()
def staged_artifacts(monkeypatch, tmp_path) -> Path:
    """A directory shaped exactly like ``pack_cli_wheel.sh`` output, bound into the service."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wheel = artifacts / WHEEL_NAME
    wheel.write_bytes(WHEEL_BYTES)
    manifest = {
        "cli": {
            "version": CLI_VERSION,
            "min_compatible": CLI_MIN_COMPATIBLE,
            "filename": WHEEL_NAME,
            "sha256": hashlib.sha256(WHEEL_BYTES).hexdigest(),
        },
        "platform": {"version": MANIFEST_PLATFORM_VERSION},
    }
    (artifacts / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(_artifact_service(), "ARTIFACTS_DIR", artifacts)
    return artifacts


@pytest.fixture()
def absent_artifacts(monkeypatch, tmp_path) -> Path:
    """Point the service at a directory that does not exist — the state of any fresh checkout."""
    artifacts = tmp_path / "never-packed"
    monkeypatch.setattr(_artifact_service(), "ARTIFACTS_DIR", artifacts)
    return artifacts


@pytest.fixture()
def build_app(monkeypatch):
    """Factory building the **real** application with the F053 switches under control.

    ``bisheng.api.router`` decides on the dev-toolkit include at import time, and
    ``bisheng.main`` bound that router object when it was first imported. So the
    factory reloads the aggregate router under the requested settings and points
    ``bisheng.main.router`` at the fresh object before calling ``create_app`` —
    the app then carries the real middleware stack, which is what makes the
    tenant-exemption assertion meaningful.
    """
    from bisheng.common.services.config_service import settings

    original_open_platform = settings.open_platform.enabled

    def _build(*, open_platform_enabled: bool = True, app_runtime_enabled: bool = True, multi_tenant: bool = False):
        monkeypatch.setattr(settings.open_platform, "enabled", open_platform_enabled)
        monkeypatch.setattr(settings.app_runtime, "enabled", app_runtime_enabled)
        monkeypatch.setattr(settings.multi_tenant, "enabled", multi_tenant)

        router_module = importlib.import_module("bisheng.api.router")
        importlib.reload(router_module)

        main_module = importlib.import_module("bisheng.main")
        monkeypatch.setattr(main_module, "lifespan", _noop_lifespan)
        monkeypatch.setattr(main_module, "router", router_module.router)
        return main_module.create_app()

    yield _build

    # Restore the module-level router to the shape the rest of the suite expects.
    # This runs before monkeypatch's own undo, so put the switch back by hand
    # first — otherwise the reload would bake the test's value into the router.
    settings.open_platform.enabled = original_open_platform
    importlib.reload(importlib.import_module("bisheng.api.router"))


@pytest.fixture()
def client_factory(build_app):
    """``client_factory(**switches)`` → ``TestClient`` over the real app.

    ``raise_server_exceptions=False`` is required by the degradation test: an
    unhandled exception must show up as a 500 *response* to be asserted against,
    not as an exception re-raised into the test.
    """
    from starlette.testclient import TestClient

    clients = []

    def _make(**switches):
        client = TestClient(build_app(**switches), raise_server_exceptions=False)
        clients.append(client)
        client.__enter__()
        return client

    yield _make

    for client in clients:
        client.__exit__(None, None, None)
