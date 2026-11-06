"""F112: the CLI must not upload when release-note input or compatibility is uncertain."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from bisheng_cli.errors import CliError
from tests.helpers.platform_mock import (
    PlatformMock,
    deploy_accept,
    deploy_limits,
    deploy_sync_err,
    v2_ok,
)
from tests.test_command_deploy_sync import _run, _waiting_seq
from tests.test_command_deploy_sync import logged_in as logged_in

LIMITS = "/api/v2/apps/deploy-limits"
DEPLOY = "/api/v2/apps/deploy"


def _platform(*, capability=None, post=None):
    data = deploy_limits().json()["data"]
    if capability is not None:
        data["features"] = {"release_notes": capability}
    return (
        PlatformMock()
        .get(LIMITS, v2_ok(data))
        .post(DEPLOY, post or deploy_accept())
        .get("/api/v2/apps/deployments/dep-1", _waiting_seq())
    )


def _note(request):
    match = re.search(b'name="release_notes"\r\n\r\n(.*?)\r\n--', request.read(), re.S)
    return match.group(1).decode() if match else None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        (" \r\n\t", None),
        ("  First\r\n  Second\rThird  ", "First\n  Second\nThird"),
        ("新功能😀" * 400, "新功能😀" * 400),
        ("x" * 2000, "x" * 2000),
        ("😀" * 2000, "😀" * 2000),
    ],
    ids=["null", "empty", "whitespace", "newlines", "unicode", "limit", "emoji-limit"],
)
def test_same_normalization_as_platform(raw, expected):
    from bisheng_cli.release_notes import normalize_release_notes

    assert normalize_release_notes(raw) == expected


@pytest.mark.parametrize("raw", ["x" * 2001, "😀" * 2001], ids=["ascii", "emoji"])
def test_over_limit_uses_codepoints_not_bytes(raw):
    from bisheng_cli.release_notes import normalize_release_notes

    with pytest.raises(CliError) as caught:
        normalize_release_notes(raw)
    assert caught.value.exit_code == 6


def test_sources_are_mutually_exclusive(logged_in, sample_project, monkeypatch):
    mock = _platform()
    with pytest.raises(SystemExit) as caught:
        _run(
            ["deploy", str(sample_project), "--release-notes", "hello", "--release-notes-file", "notes.txt"],
            monkeypatch=monkeypatch,
            mock=mock,
        )
    assert caught.value.code == 2
    assert not mock.calls


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid-utf8", "too-long", "unreadable"])
def test_bad_files_never_upload(kind, logged_in, sample_project, tmp_path, monkeypatch):
    path = tmp_path / "notes.txt"
    if kind == "directory":
        path.mkdir()
    elif kind == "invalid-utf8":
        path.write_bytes(b"\xff")
    elif kind == "too-long":
        path.write_text("x" * 2001)
    elif kind == "unreadable":
        path.write_text("hello")
        original = Path.open

        def no_read(self, *args, **kwargs):
            if self == path:
                raise PermissionError("no access")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", no_read)
    mock = _platform()
    code, _, _ = _run(
        ["deploy", str(sample_project), "--release-notes-file", str(path)], monkeypatch=monkeypatch, mock=mock
    )
    assert code == 6
    assert not mock.calls


def test_dry_run_validates_without_network(logged_in, sample_project, monkeypatch):
    mock = _platform()
    code, out, _ = _run(
        ["deploy", str(sample_project), "--release-notes", "  New\r\nfix  ", "--dry-run", "--json"],
        monkeypatch=monkeypatch,
        mock=mock,
    )
    assert code == 0
    result = json.loads(out.splitlines()[-1])
    assert result["data"]["has_release_notes"] is True
    assert result["data"]["release_notes_codepoints"] == 7
    assert not mock.calls


@pytest.mark.parametrize(
    "capability",
    [
        None,
        {"version": 2, "max_codepoints": 2000},
        {"version": True, "max_codepoints": 2000},
        {"version": 1, "max_codepoints": "2000"},
        {"version": 1, "max_codepoints": 0},
        {"version": 1, "max_codepoints": 2},
    ],
    ids=["old", "future", "bool-version", "string-limit", "zero", "smaller-limit"],
)
def test_unknown_support_never_uploads(capability, logged_in, sample_project, monkeypatch):
    mock = _platform(capability=capability)
    code, _, _ = _run(["deploy", str(sample_project), "--release-notes", "Feature"], monkeypatch=monkeypatch, mock=mock)
    assert code == 9
    assert mock.paths_called() == [LIMITS]


def test_network_failure_with_notes_does_not_soft_fallback(logged_in, sample_project, monkeypatch):
    def broken(request):
        raise httpx.ConnectError("connection failed", request=request)

    mock = PlatformMock().get(LIMITS, broken)
    code, _, _ = _run(["deploy", str(sample_project), "--release-notes", "Feature"], monkeypatch=monkeypatch, mock=mock)
    assert code == 7
    assert mock.paths_called() == [LIMITS]


@pytest.mark.parametrize("notes", [None, " \r\n"])
def test_empty_notes_keep_legacy_platform_compatible(notes, logged_in, sample_project, monkeypatch):
    mock = _platform()
    argv = ["deploy", str(sample_project)] + (["--release-notes", notes] if notes is not None else [])
    code, _, _ = _run(argv, monkeypatch=monkeypatch, mock=mock)
    assert code == 0
    post = next(r for r in mock.calls if r.method == "POST")
    assert _note(post) is None


def test_file_is_frozen_for_schema_confirmation_retry(logged_in, sample_project, tmp_path, monkeypatch):
    path = tmp_path / "notes.txt"
    path.write_bytes("  新增功能\r\n  Fix  ".encode())
    bodies = []

    def receive(request):
        bodies.append(_note(request))
        path.write_text("Changed during upload")
        if len(bodies) == 1:
            return deploy_sync_err(16229, details={"items": []})
        return deploy_accept()

    mock = _platform(capability={"version": 1, "max_codepoints": 2000}, post=receive)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    code, _, _ = _run(
        ["deploy", str(sample_project), "--release-notes-file", str(path)], monkeypatch=monkeypatch, mock=mock, tty=True
    )
    assert code == 0
    assert bodies == ["新增功能\n  Fix", "新增功能\n  Fix"]
    assert mock.paths_called().count(LIMITS) == 1


def test_server_rejection_maps_to_fix_input(logged_in, sample_project, monkeypatch):
    mock = _platform(capability={"version": 1, "max_codepoints": 2000}, post=deploy_sync_err(16233))
    code, _, _ = _run(["deploy", str(sample_project), "--release-notes", "Feature"], monkeypatch=monkeypatch, mock=mock)
    assert code == 6


@pytest.mark.parametrize(
    ("language", "word"),
    [("zh_CN.UTF-8", "发布说明"), ("en_US.UTF-8", "Release notes"), ("ja_JP.UTF-8", "リリースノート")],
)
def test_new_messages_support_all_three_languages(language, word, monkeypatch):
    from bisheng_cli.release_notes import message

    monkeypatch.setenv("LC_ALL", language)
    assert word in message("text_help")


def test_file_source_is_relative_to_command_directory(tmp_path, monkeypatch):
    from bisheng_cli.release_notes import load_release_notes

    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.txt").write_bytes(b"  A\r\n  B  ")
    assert load_release_notes(file_path="notes.txt") == "A\n  B"


@pytest.mark.parametrize("explicit", [False, True])
def test_packaging_post_release_preserves_minimum_and_sdk(tmp_path, explicit):
    script = (Path(__file__).resolve().parents[3] / "scripts/pack_cli_wheel.sh").read_text()
    manifest_writer = script.split("python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    target = tmp_path / "manifest.json"
    sdk = {"version": "0.1.0", "filename": "sdk.whl", "sha256": "sdk-preserved"}
    target.write_text(json.dumps({"sdk": sdk}))
    env = {
        **os.environ,
        "MANIFEST": str(target),
        "CLI_VERSION": "3.0.0.post1",
        "CLI_MIN_COMPATIBLE": "3.0.0" if explicit else "",
        "PLATFORM_VERSION": "3.0.0" if explicit else "",
        "CLI_FILENAME": "cli.whl",
        "CLI_SHA256": "cli-digest",
    }
    subprocess.run([sys.executable, "-c", manifest_writer], check=True, env=env)
    result = json.loads(target.read_text())
    assert result["cli"]["version"] == "3.0.0.post1"
    assert result["cli"]["min_compatible"] == "3.0.0"
    assert result["platform"]["version"] == "3.0.0"
    assert result["sdk"] == sdk
