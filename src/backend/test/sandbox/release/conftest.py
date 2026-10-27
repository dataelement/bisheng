"""Live release fixtures. Missing processes are skipped, never passed."""

from __future__ import annotations

import httpx
import pytest

from test.sandbox.release.env import SANDBOX_URL


def sandbox_reachable() -> bool:
    try:
        resp = httpx.get(f"{SANDBOX_URL}/health", timeout=2.0)
    except httpx.HTTPError:
        return False
    return resp.status_code == 200


@pytest.fixture(scope="session")
def sandbox_url() -> str:
    if not sandbox_reachable():
        pytest.skip("沙箱进程未启动，容器组未测")
    return SANDBOX_URL
