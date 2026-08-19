"""T011 — credential storage.

The key is stored in clear text because every request needs its original value.
That makes the file mode the *only* protection there is, not a hardening extra —
which is why the creation mode, not a later chmod, is what these tests assert.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from bisheng_cli import credentials
from bisheng_cli.errors import EXIT_NOT_LOGGED_IN, CliError
from tests.helpers.platform_mock import FAKE_KEY, FAKE_KEY_MASK

BASE = "http://114.test:7860"
OTHER = "http://another.test"

pytestmark = pytest.mark.usefixtures("home_dir")


def _profile(base_url: str = BASE, **overrides) -> dict:
    payload = {
        "base_url": base_url,
        "api_key": FAKE_KEY,
        "key_mask": FAKE_KEY_MASK,
        "tenant_id": 1,
        "service_account": {"id": 123, "name": "问卷小队开发号"},
        "resource_owner": {"user_id": 7, "user_name": "张三"},
        "expires_at": "2026-12-31T00:00:00",
    }
    payload.update(overrides)
    return payload


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits do not exist on Windows")
def test_file_created_0600_and_dir_0700_in_one_step() -> None:
    credentials.save_profile(BASE, _profile())
    path = credentials.credentials_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits do not exist on Windows")
def test_rewrite_keeps_0600_and_leaves_no_world_readable_leftover(tmp_path: Path) -> None:
    credentials.save_profile(BASE, _profile())
    credentials.save_profile(BASE, _profile(tenant_id=2))
    directory = credentials.credentials_path().parent
    for entry in directory.iterdir():
        assert not stat.S_IMODE(entry.stat().st_mode) & 0o077, f"{entry} is readable by others"


def test_never_written_into_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    credentials.save_profile(BASE, _profile())
    assert list(project.rglob("*")) == []
    assert Path.home() in credentials.credentials_path().parents


def test_scopes_never_persisted() -> None:
    credentials.save_profile(BASE, _profile(scopes=["app:manage", "delegate"]))
    raw = json.loads(credentials.credentials_path().read_text(encoding="utf-8"))
    assert "scopes" not in json.dumps(raw)


def test_multi_profile_isolated_by_base_url() -> None:
    credentials.save_profile(BASE, _profile())
    credentials.save_profile(OTHER, _profile(OTHER, tenant_id=9))
    store = json.loads(credentials.credentials_path().read_text(encoding="utf-8"))
    assert set(store["profiles"]) == {BASE, OTHER}
    assert store["current"] == OTHER
    assert credentials.load_profile(BASE).tenant_id == 1


def test_relogin_same_platform_overwrites_profile() -> None:
    credentials.save_profile(BASE, _profile())
    credentials.save_profile(BASE, _profile(tenant_id=42))
    store = json.loads(credentials.credentials_path().read_text(encoding="utf-8"))
    assert list(store["profiles"]) == [BASE]
    assert credentials.load_current().tenant_id == 42


def test_base_url_normalised_before_use_as_key() -> None:
    # Two real failures ride on this, not just a duplicate row:
    #   1. "please run bisheng login" right after a successful login;
    #   2. .bisheng/app.json keyed by the other spelling, so an iterative deploy
    #      looks like a first deploy and the platform grows a second draft app.
    variants = ["http://114.test:7860/", "http://114.test:7860", "HTTP://114.test:7860"]
    assert len({credentials.normalise_base_url(v) for v in variants}) == 1
    credentials.save_profile(variants[0], _profile())
    for variant in variants:
        assert credentials.load_profile(variant).api_key == FAKE_KEY


def test_explicit_default_port_is_not_stripped() -> None:
    # Guessing that :80 == no port would be a guess about how the operator wrote
    # their nginx config; keeping them distinct is wrong at most in one direction.
    assert credentials.normalise_base_url("http://p.test:80") != credentials.normalise_base_url("http://p.test")


def test_load_without_credentials_raises_exit_3_not_network_error() -> None:
    with pytest.raises(CliError) as excinfo:
        credentials.load_current()
    assert excinfo.value.exit_code == EXIT_NOT_LOGGED_IN
    assert "bisheng login" in excinfo.value.next_step


def test_load_profile_for_unknown_platform_raises_exit_3() -> None:
    credentials.save_profile(BASE, _profile())
    with pytest.raises(CliError) as excinfo:
        credentials.load_profile("http://never-seen.test")
    assert excinfo.value.exit_code == EXIT_NOT_LOGGED_IN


def test_stored_snapshot_fields() -> None:
    credentials.save_profile(BASE, _profile())
    stored = json.loads(credentials.credentials_path().read_text(encoding="utf-8"))["profiles"][BASE]
    assert set(stored) == {
        "base_url",
        "api_key",
        "key_mask",
        "tenant_id",
        "service_account",
        "resource_owner",
        "expires_at",
        "logged_in_at",
    }
    assert stored["logged_in_at"]


def test_resource_owner_may_be_null_until_f049_adds_it() -> None:
    credentials.save_profile(BASE, _profile(resource_owner=None))
    assert credentials.load_current().resource_owner is None


def test_windows_acl_failure_warns_loudly_instead_of_pretending(monkeypatch: pytest.MonkeyPatch) -> None:
    # os.chmod on Windows only moves the read-only bit; if the ACL call fails the
    # file is readable by every account on the box. Saying nothing would be the
    # one outcome worse than failing.
    warnings: list[str] = []
    monkeypatch.setattr(credentials, "_is_windows", lambda: True)
    monkeypatch.setattr(credentials, "_run_icacls", lambda path: False)
    credentials.save_profile(BASE, _profile(), warn=warnings.append)
    assert warnings and "权限" in warnings[0]


def test_windows_acl_success_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(credentials, "_is_windows", lambda: True)
    monkeypatch.setattr(credentials, "_run_icacls", lambda path: True)
    credentials.save_profile(BASE, _profile(), warn=warnings.append)
    assert warnings == []


def test_corrupt_store_is_reported_not_silently_reset() -> None:
    path = credentials.credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CliError) as excinfo:
        credentials.load_current()
    assert str(path) in excinfo.value.next_step
    assert os.path.exists(path)


# ---- Windows ACL hardening: SID grant + never brick the file (field fix) ----


class _FakeRun:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_current_user_grantee_prefers_sid(monkeypatch: pytest.MonkeyPatch) -> None:
    # whoami /user gives an unambiguous SID; a bare username may not resolve.
    monkeypatch.setattr(
        credentials.subprocess,
        "run",
        lambda *a, **k: _FakeRun(0, '"DESKTOP-ABC\\X1C","S-1-5-21-1-2-3-1001"\n'),
    )
    assert credentials._current_user_grantee() == "*S-1-5-21-1-2-3-1001"


def test_current_user_grantee_falls_back_to_username(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise OSError

    monkeypatch.setattr(credentials.subprocess, "run", boom)
    monkeypatch.setenv("USERNAME", "X1C")
    assert credentials._current_user_grantee() == "X1C"


def test_run_icacls_never_strips_inheritance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # /inheritance:r on a file with only inherited ACEs is what bricked the field
    # machine: it must never be issued again.
    path = tmp_path / "credentials.json"
    path.write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(credentials.subprocess, "run", lambda args, **k: calls.append(args) or _FakeRun())
    monkeypatch.setattr(credentials, "_current_user_grantee", lambda: "*S-1-5-21-x")
    monkeypatch.setattr(credentials, "_can_read", lambda p: True)

    assert credentials._run_icacls(path) is True
    flat = [a for call in calls for a in call]
    assert "/inheritance:r" not in flat
    assert "*S-1-5-21-x:F" in flat  # granted by SID
    assert not any("/reset" in call for call in calls)  # readable, so no rollback


def test_run_icacls_rolls_back_when_the_grant_bricks_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # If the ACL change somehow leaves the file unreadable by us, restore inherited
    # permissions so the next `bisheng deploy` can still read the key.
    path = tmp_path / "credentials.json"
    path.write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(credentials.subprocess, "run", lambda args, **k: calls.append(args) or _FakeRun())
    monkeypatch.setattr(credentials, "_current_user_grantee", lambda: "*S-1-5-21-x")
    reads = iter([False, True])  # unreadable after grant, readable after /reset
    monkeypatch.setattr(credentials, "_can_read", lambda p: next(reads))

    assert credentials._run_icacls(path) is True
    assert any("/reset" in call for call in calls)


def test_run_icacls_returns_false_only_when_still_unreadable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(credentials.subprocess, "run", lambda args, **k: _FakeRun())
    monkeypatch.setattr(credentials, "_current_user_grantee", lambda: "*S-1-5-21-x")
    monkeypatch.setattr(credentials, "_can_read", lambda p: False)  # even /reset didn't help

    assert credentials._run_icacls(path) is False
