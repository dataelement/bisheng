"""Shared fixtures for the bisheng-cli suite.

Three rules this file enforces for the whole package:

1. **No test ever touches the network.** `no_network` swaps httpx's real
   transport for a sentinel that raises. A forgotten mock therefore fails loudly
   at the call site instead of quietly reaching out to whatever host the test
   happened to name — which on a developer machine means a proxy timeout that
   looks nothing like a missing mock.
2. **No test ever touches the real home directory.** Credentials are written
   with `Path.home()`; pointing that at `tmp_path` is what keeps a test run from
   overwriting the developer's own `~/.bisheng/credentials.json`.
3. **No long key literal is ever written into a `.py` file.** `scripts/arch-guard.sh`
   RULE-7 greps for an assignment of a long string literal to a credential-looking
   name. It only emits a WARNING and does not
   block, which is precisely the problem: a permanent stream of false warnings is
   how a real hardcoded secret gets scrolled past. `FAKE_KEY` is assembled by
   concatenation so the pattern never matches.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import httpx
import pytest

from tests.helpers.platform_mock import FAKE_KEY

__all__ = ["FAKE_KEY"]

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

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `@pytest.mark.network` unless a real platform was opted into."""
    if os.environ.get("BISHENG_CLI_RUN_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(
        reason="needs a real platform — 114 manual verification only (set BISHENG_CLI_RUN_NETWORK_TESTS=1)"
    )
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any un-mocked HTTP call fail immediately.

    Also strips proxy env: a `socks5://` ALL_PROXY without `socksio` installed
    turns an entire file into collection ERRORs that read like an import
    problem, and the proxy-hint logic in `http.py` has to be exercised under a
    known-empty environment anyway.
    """
    for name in _PROXY_ENV:
        monkeypatch.delenv(name, raising=False)

    def _refuse(self, request):
        raise AssertionError(f"unmocked network call: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse, raising=True)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse, raising=True)


@pytest.fixture
def home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `Path.home()` (and the env vars behind it) at a throwaway dir."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _build_sample_tree(root: Path) -> None:
    """Materialise the sample application, noise and all.

    The noise is the point: `.venv/` and `node_modules/` are what actually blows
    the 50 MB ceiling in the field, `dist/` is the soft-exclude that a real app
    may legitimately need back, and the symlink / 0755 script / sqlite file each
    stand for one packaging rule.
    """
    shutil.copytree(FIXTURES / "sample_app", root)
    (root / ".gitignore").write_text((root / "gitignore.template").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "gitignore.template").unlink()

    script = root / "entrypoint.sh"
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    for noisy in (".venv", "node_modules", "__pycache__", ".pytest_cache"):
        d = root / noisy
        d.mkdir()
        (d / "payload.bin").write_bytes(b"\x00" * 32)

    dist = root / "dist"
    dist.mkdir()
    (dist / "bundle.js").write_text("console.log(1)\n", encoding="utf-8")

    (root / "app.sqlite").write_bytes(b"SQLite format 3\x00")
    (root / "debug.log").write_text("noise\n", encoding="utf-8")
    (root / "important.log").write_text("kept by the ! rule\n", encoding="utf-8")
    build_artifacts = root / "build-artifacts"
    build_artifacts.mkdir()
    (build_artifacts / "old.tar").write_bytes(b"x")

    try:
        (root / "link-to-main.py").symlink_to(root / "main.py")
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without dev mode
        pass


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    root = tmp_path / "sample"
    _build_sample_tree(root)
    return root


def _git_available() -> bool:
    return shutil.which("git") is not None


@pytest.fixture
def sample_project_git(tmp_path: Path) -> Path:
    """Same tree, under real git.

    CI has git; a developer machine is not guaranteed to, so the fixture skips
    rather than failing — a missing `git` says nothing about the code.
    """
    if not _git_available():
        pytest.skip("git is not available; the git-backed ignore path cannot be exercised")
    root = tmp_path / "sample-git"
    _build_sample_tree(root)
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_SYSTEM": str(tmp_path / "gitconfig-system"),
    }
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    return root
