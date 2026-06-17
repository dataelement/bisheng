"""E2E tests for F035 Tracks A / B / C against REAL middleware (no mock).

These verify the integration points the unit suites cannot reach (which mock
Redis/MinIO and use InMemorySaver), against the real infrastructure in
``bisheng/config.yaml``:

  - Track A (AC-1): ``create_linsight_agent`` assembles a real deepagents graph.
  - Track B (AC-5): ``PlainRedisCheckpointer`` round-trips through real Redis
    (put/get/list + pending_writes); parked-thread keys expire via TTL.
  - Track C (AC-6): ``WorkspaceBackend`` writes/reads/ls through real MinIO with
    write-through cache + per-svid tenant isolation.

Why a subprocess: the repo-wide ``test/conftest.py`` pre-mocks
``bisheng.core.cache.redis_manager`` (MagicMock) at import time, which would
intercept Track B's checkpointer. The real logic therefore runs in a CLEAN child
process (``_e2e_abc_runner.py``) with no premock; this wrapper parses its JSON
result and asserts per-Track. Walk-through of the real-middleware checks lives in
the runner.

Marked ``e2e`` (excluded by ``pytest -m "not e2e"``); skipped automatically when
the configured Redis is unreachable so unit CI stays green.

Run:
    cd src/backend && export config=config.yaml
    uv run pytest test/linsight/test_e2e_abc.py -v -m e2e
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.e2e

_RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_e2e_abc_runner.py")
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _redis_reachable() -> bool:
    """Probe the configured Redis without importing the premocked redis_manager."""
    try:
        import yaml

        with open(os.path.join(_BACKEND_ROOT, "bisheng", "config.yaml")) as fh:
            cfg = yaml.safe_load(fh) or {}
        url = cfg.get("redis_url") or os.environ.get("REDIS_URL", "redis://localhost:6379")
        parsed = urlparse(url if "://" in url else f"redis://{url}")
        host, port = parsed.hostname or "localhost", parsed.port or 6379
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _redis_reachable(), reason="configured Redis required for ABC e2e"),
]


@pytest.fixture(scope="module")
def abc_results() -> dict[str, dict]:
    """Run the real-middleware runner once in a clean subprocess; index by check name."""
    env = dict(os.environ)
    env.setdefault("config", "config.yaml")
    proc = subprocess.run(
        [sys.executable, _RUNNER],
        cwd=_BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    # The runner prints a single JSON object on the last stdout line.
    last = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip().startswith("{")), None)
    assert last, f"runner produced no JSON result.\nSTDOUT:\n{proc.stdout[-2000:]}\nSTDERR:\n{proc.stderr[-2000:]}"
    checks = json.loads(last)["checks"]
    return {c["name"]: c for c in checks}


def _assert_prefix(results: dict[str, dict], prefix: str) -> None:
    matched = {n: c for n, c in results.items() if n.startswith(prefix)}
    assert matched, f"no checks recorded for {prefix!r}; got {list(results)}"
    failed = {n: c["detail"] for n, c in matched.items() if not c["ok"]}
    assert not failed, f"{prefix} checks failed: {failed}"


def test_track_a_agent_factory(abc_results):
    """AC-1: create_linsight_agent assembles a runnable real deepagents graph."""
    _assert_prefix(abc_results, "A/")


def test_track_b_checkpointer(abc_results):
    """AC-5: PlainRedisCheckpointer round-trips through real Redis (put/get/list/writes)."""
    _assert_prefix(abc_results, "B/")


def test_track_c_workspace(abc_results):
    """AC-6/AC-7: WorkspaceBackend write-through/read/ls/isolation on real MinIO."""
    _assert_prefix(abc_results, "C/")
