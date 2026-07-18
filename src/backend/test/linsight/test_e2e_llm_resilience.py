"""E2E test for 灵思LLM容错 — LLM fault tolerance in the REAL deepagents graph.

The safety-guardrail error is hard to reproduce against a live model, so the
model API is substituted by a scripted fault model while the rest is the real
path: ``create_linsight_agent`` → deepagents graph → resilience middleware →
``astream``. Unlike ``test_e2e_abc.py`` this needs NO external middleware — the
runner patches the merged-config read and uses InMemorySaver + the in-memory
FakeWorkspaceBackend — so it runs anywhere.

Why a subprocess: the repo-wide ``test/conftest.py`` pre-mocks infrastructure at
import time; the real graph assembly runs in a CLEAN child process
(``_e2e_llm_resilience_runner.py``) and this wrapper asserts on its JSON.

Run:
    cd src/backend && uv run pytest test/linsight/test_e2e_llm_resilience.py -v -m e2e
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e

_RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_e2e_llm_resilience_runner.py")
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Proxy env vars make langchain_ollama's eager Client() init fail on SOCKS import;
# the runner needs no network, so strip them for a clean subprocess.
_PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")


@pytest.fixture(scope="module")
def resilience_results() -> dict[str, dict]:
    env = {k: v for k, v in os.environ.items() if k not in _PROXY_KEYS}
    env.setdefault("config", "config.yaml")
    proc = subprocess.run(
        [sys.executable, _RUNNER],
        cwd=_BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    last = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip().startswith("{")), None)
    assert last, f"runner produced no JSON result.\nSTDOUT:\n{proc.stdout[-2000:]}\nSTDERR:\n{proc.stderr[-2000:]}"
    checks = json.loads(last)["checks"]
    return {c["name"]: c for c in checks}


def _assert_prefix(results: dict[str, dict], prefix: str) -> None:
    matched = {n: c for n, c in results.items() if n.startswith(prefix)}
    assert matched, f"no checks recorded for {prefix!r}; got {list(results)}"
    failed = {n: c["detail"] for n, c in matched.items() if not c["ok"]}
    assert not failed, f"{prefix} checks failed: {failed}"


def test_r1_transient_retry(resilience_results):
    """Layer A: a transient model error is retried with backoff; the task continues."""
    _assert_prefix(resilience_results, "R1")


def test_r2_main_content_filter_fails_cleanly(resilience_results):
    """Main-agent content-filter re-raises (no retry) and classifies as content_filter."""
    _assert_prefix(resilience_results, "R2")


def test_r3_subagent_content_filter_degrades(resilience_results):
    """Layer B: a subagent content-filter degrades to a synthetic reply so the loop continues."""
    _assert_prefix(resilience_results, "R3")
