"""T035 — `bisheng skills sync`.

The pack is a platform release artifact, so the command's contract is narrow and
sharp: fetch the current version from the anonymous endpoint, overwrite the local
copy wholesale (no merge, 决议-8), and say what it overwrote. Everything the CLI
refuses to do — merge, keep local edits, ask before overwriting — is as much part
of the contract as what it does, so those get tests too.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from bisheng_cli import credentials
from bisheng_cli.commands import skills as skills_mod
from bisheng_cli.errors import EXIT_LOCAL_INVALID, EXIT_NOT_ENABLED, EXIT_NOT_LOGGED_IN, EXIT_OK, EXIT_USAGE
from bisheng_cli.main import run as main_run
from bisheng_cli.output import Emitter
from tests.helpers.platform_mock import FAKE_KEY, FAKE_KEY_MASK, PlatformMock, use_mock_transport

BASE = "http://platform.test"
PACK = "deploy-hosting"
SKILLS_PATH = f"/api/v1/dev-toolkit/skills/{PACK}"


@pytest.fixture
def logged_in(home_dir) -> None:
    credentials.save_profile(
        BASE,
        {
            "api_key": FAKE_KEY,
            "key_mask": FAKE_KEY_MASK,
            "tenant_id": 1,
            "service_account": {"id": 123, "name": "问卷小队开发号"},
        },
    )


def _pack_tar(files: dict[str, str], *, pack: str = PACK) -> bytes:
    """Build a pack tarball the same shape the endpoint serves: members under ``pack/``."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for rel, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"{pack}/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _pack_response(files: dict[str, str], *, version: str = "3.0.0") -> httpx.Response:
    return httpx.Response(
        200,
        content=_pack_tar(files),
        headers={"x-bisheng-pack-version": version, "content-type": "application/gzip"},
    )


SAMPLE = {"SKILL.md": "# deploy-hosting\n铁律……\n", "example/main.py": "print('hi')\n", "selfcheck.py": "print('ok')\n"}


def _run(argv: list[str], *, monkeypatch: pytest.MonkeyPatch, mock: PlatformMock) -> tuple[int, str, str]:
    use_mock_transport(monkeypatch, skills_mod, mock)
    out, err = io.StringIO(), io.StringIO()
    code = main_run(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _skills_dir(home: Path) -> Path:
    return home / ".bisheng" / "skills"


# ---- not logged in / usage ------------------------------------------------


def test_not_logged_in_exits_3_without_request(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    mock = PlatformMock()
    code, _, err = _run(["skills", "sync"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_NOT_LOGGED_IN
    assert "login" in err
    assert mock.paths_called() == []


def test_bare_skills_prints_usage_exit_2(monkeypatch: pytest.MonkeyPatch, logged_in) -> None:
    mock = PlatformMock()
    code, _, err = _run(["skills"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_USAGE
    assert "skills sync" in err
    assert mock.paths_called() == []


# ---- happy path -----------------------------------------------------------


def test_sync_writes_pack_into_home_skills_dir(monkeypatch: pytest.MonkeyPatch, logged_in, home_dir) -> None:
    mock = PlatformMock().get(SKILLS_PATH, _pack_response(SAMPLE))
    code, _, err = _run(["skills", "sync"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    pack_dir = _skills_dir(home_dir) / PACK
    assert (pack_dir / "SKILL.md").read_text(encoding="utf-8") == SAMPLE["SKILL.md"]
    assert (pack_dir / "example" / "main.py").read_text(encoding="utf-8") == SAMPLE["example/main.py"]
    assert (pack_dir / "selfcheck.py").is_file()
    # AC-20: the reference guide points a non-Claude engine at the same dir.
    assert "AGENTS.md" in err
    assert str(_skills_dir(home_dir)) in err


def test_sync_reports_version_and_is_idempotent(monkeypatch: pytest.MonkeyPatch, logged_in, home_dir) -> None:
    mock = PlatformMock().get(
        SKILLS_PATH, [_pack_response(SAMPLE, version="3.0.1"), _pack_response(SAMPLE, version="3.0.1")]
    )
    code1, _, err1 = _run(["skills", "sync"], monkeypatch=monkeypatch, mock=mock)
    code2, _, _ = _run(["skills", "sync"], monkeypatch=monkeypatch, mock=mock)
    assert code1 == EXIT_OK and code2 == EXIT_OK
    assert "3.0.1" in err1
    # Second run is a clean overwrite, not a duplicate/merge: the tree matches.
    files = sorted(p.name for p in (_skills_dir(home_dir) / PACK).rglob("*") if p.is_file())
    assert files == ["SKILL.md", "main.py", "selfcheck.py"]


def test_sync_overwrites_local_edits_and_lists_them(monkeypatch: pytest.MonkeyPatch, logged_in, home_dir) -> None:
    # First sync, then the developer edits a pack file; re-sync must restore the
    # platform version (决议-8: one-way overwrite) and name the overwritten file.
    mock = PlatformMock().get(SKILLS_PATH, [_pack_response(SAMPLE), _pack_response(SAMPLE)])
    _run(["skills", "sync"], monkeypatch=monkeypatch, mock=mock)
    edited = _skills_dir(home_dir) / PACK / "SKILL.md"
    edited.write_text("我改过了\n", encoding="utf-8")
    code, out, _ = _run(["skills", "sync", "--json"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert edited.read_text(encoding="utf-8") == SAMPLE["SKILL.md"]  # restored
    # The machine-readable result lists the overwritten file so the edit is not silent.
    assert f"{PACK}/SKILL.md" in out


# ---- endpoint absent / errors --------------------------------------------


def test_endpoint_404_exits_not_enabled(monkeypatch: pytest.MonkeyPatch, logged_in, home_dir) -> None:
    mock = PlatformMock().get(SKILLS_PATH, httpx.Response(404, json={"detail": "Not Found"}))
    code, _, err = _run(["skills", "sync"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_NOT_ENABLED
    assert "open_platform" in err or "开放能力层" in err
    assert not (_skills_dir(home_dir) / PACK).exists()


def test_traversal_member_rejected_nothing_escapes(monkeypatch: pytest.MonkeyPatch, logged_in, home_dir) -> None:
    evil = _pack_tar({"../evil.txt": "pwned\n", "SKILL.md": "ok\n"})
    mock = PlatformMock().get(SKILLS_PATH, httpx.Response(200, content=evil))
    code, _, _ = _run(["skills", "sync"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_LOCAL_INVALID
    assert not (home_dir / ".bisheng" / "evil.txt").exists()
    assert not (home_dir / "evil.txt").exists()


# ---- login auto-sync (AC-08) ---------------------------------------------


def test_run_after_login_never_raises_on_failure(monkeypatch: pytest.MonkeyPatch, logged_in, home_dir) -> None:
    # A sync failure at login must degrade to a warning, never propagate — login
    # already succeeded by the time this runs.
    mock = PlatformMock().get(SKILLS_PATH, httpx.Response(404, json={"detail": "Not Found"}))
    use_mock_transport(monkeypatch, skills_mod, mock)
    err = io.StringIO()
    emitter = Emitter(stdout=io.StringIO(), stderr=err)
    profile = credentials.Profile(base_url=BASE, api_key=FAKE_KEY)
    args = SimpleNamespace(no_proxy=False, timeout=None)
    skills_mod.run_after_login(profile, args, emitter)  # must not raise
    assert "skills sync" in err.getvalue()


def test_run_after_login_syncs_on_success(monkeypatch: pytest.MonkeyPatch, logged_in, home_dir) -> None:
    mock = PlatformMock().get(SKILLS_PATH, _pack_response(SAMPLE))
    use_mock_transport(monkeypatch, skills_mod, mock)
    emitter = Emitter(stdout=io.StringIO(), stderr=io.StringIO())
    profile = credentials.Profile(base_url=BASE, api_key=FAKE_KEY)
    args = SimpleNamespace(no_proxy=False, timeout=None)
    skills_mod.run_after_login(profile, args, emitter)
    assert (_skills_dir(home_dir) / PACK / "SKILL.md").is_file()
