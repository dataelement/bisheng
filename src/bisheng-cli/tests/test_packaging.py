"""T017 — packaging. Each assertion here is the dual of a failure seen in the field."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import tarfile
from pathlib import Path

import httpx
import pytest

from bisheng_cli.errors import EXIT_LOCAL_INVALID, CliError
from bisheng_cli.http import PlatformClient
from bisheng_cli.ignore import collect_files
from bisheng_cli.packaging import DEFAULT_LIMITS, Limits, build_package, check_limits, fetch_limits, format_size_report
from tests.helpers.platform_mock import FAKE_KEY, PlatformMock, deploy_limits

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes / links")


def _pack(root: Path, tmp_path: Path, name: str = "pkg.tar.gz"):
    out = tmp_path / name
    return build_package(root, collect_files(root, use_git=False), out), out


def _members(path: Path) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(path, "r:gz") as tar:
        return {m.name: m for m in tar.getmembers()}


def test_credentials_file_never_in_package(sample_project: Path, tmp_path: Path, home_dir: Path) -> None:
    # Two paths to the same leak: the real user-level file, and a stray copy that
    # somebody dropped inside the project.
    (home_dir / ".bisheng").mkdir()
    (home_dir / ".bisheng" / "credentials.json").write_text("{}", encoding="utf-8")
    stray = sample_project / ".bisheng"
    stray.mkdir(exist_ok=True)
    (stray / "credentials.json").write_text(f'{{"api_key": "{FAKE_KEY}"}}', encoding="utf-8")

    _, out = _pack(sample_project, tmp_path)
    names = _members(out)
    assert not [n for n in names if "credentials" in n]
    assert out.read_bytes().find(FAKE_KEY.encode()) == -1


def test_venv_node_modules_git_pycache_excluded(sample_project: Path, tmp_path: Path) -> None:
    names = _members(_pack(sample_project, tmp_path)[1])
    assert not [n for n in names if n.startswith((".venv/", "node_modules/", ".git/", "__pycache__/"))]


def test_local_sqlite_and_attachment_dir_excluded(sample_project: Path, tmp_path: Path) -> None:
    (sample_project / "attachments").mkdir()
    (sample_project / "attachments" / "a.bin").write_bytes(b"x")
    names = _members(_pack(sample_project, tmp_path)[1])
    assert "app.sqlite" not in names
    assert not [n for n in names if n.startswith("attachments/")]


def test_member_paths_are_posix_relative_no_backslash_no_abs_no_dotdot(sample_project: Path, tmp_path: Path) -> None:
    # A `\` separator survives as part of the *filename* on Linux: the server
    # unpacks a single file called `src\main.py` and the app's directory tree is
    # gone — or the unpack gate rejects it as 16202.
    for name in _members(_pack(sample_project, tmp_path)[1]):
        assert "\\" not in name
        assert not name.startswith("/")
        assert not name.startswith("./")
        assert ".." not in Path(name).parts


def test_symlink_device_fifo_skipped_and_listed(sample_project: Path, tmp_path: Path) -> None:
    os.mkfifo(sample_project / "a.fifo")
    stat_result, out = _pack(sample_project, tmp_path)
    names = _members(out)
    kinds = {entry.path: entry.kind for entry in stat_result.skipped}

    assert "link-to-main.py" not in names and kinds["link-to-main.py"] == "symlink"
    assert "a.fifo" not in names and kinds["a.fifo"] == "fifo"
    # Skipped, but never silently: the server's unpack gate rejects these kinds,
    # so a silent skip would turn into a 16202 after a wasted upload.
    assert all(entry.path in format_size_report(stat_result, DEFAULT_LIMITS) for entry in stat_result.skipped)


def test_hardlinked_regular_file_is_packed_with_its_contents(sample_project: Path, tmp_path: Path) -> None:
    """``st_nlink > 1`` is not a property the author chose, or can even see.

    ``_tar_info`` hand-builds a REGTYPE header and streams the bytes, so this
    writer cannot emit a hardlink member no matter how many links a file has —
    that only happens when tarfile picks the type itself via ``add`` and its
    inode table. Skipping these would drop the contents of an ordinary file to
    avoid a member type that is never produced.
    """
    os.link(sample_project / "main.py", sample_project / "hardlinked.py")
    stat_result, out = _pack(sample_project, tmp_path)

    assert "hardlinked.py" not in {entry.path for entry in stat_result.skipped}
    with tarfile.open(out, "r:gz") as tar:
        member = tar.getmember("hardlinked.py")
        assert member.isreg(), "a hardlink member would be rejected by the server's unpack gate"
        assert tar.extractfile(member).read() == (sample_project / "main.py").read_bytes()


def test_owner_exec_bit_preserved_0755_others_normalized_0644(sample_project: Path, tmp_path: Path) -> None:
    members = _members(_pack(sample_project, tmp_path)[1])
    # Losing the bit makes the entrypoint unexecutable, and that failure only
    # surfaces at build/probe time pointing at "the platform build".
    assert members["entrypoint.sh"].mode == 0o755
    assert members["main.py"].mode == 0o644


def test_reproducible_same_sha256_twice(sample_project: Path, tmp_path: Path) -> None:
    first, path_a = _pack(sample_project, tmp_path, "a.tar.gz")
    second, path_b = _pack(sample_project, tmp_path, "b.tar.gz")
    assert first.sha256 == second.sha256
    assert hashlib.sha256(path_a.read_bytes()).hexdigest() == first.sha256
    assert path_a.read_bytes() == path_b.read_bytes()


def test_member_metadata_is_normalised(sample_project: Path, tmp_path: Path) -> None:
    for member in _members(_pack(sample_project, tmp_path)[1]).values():
        assert member.mtime == 0
        assert member.uid == member.gid == 0
        assert member.uname == member.gname == ""
        assert member.type == tarfile.REGTYPE


def test_never_silently_truncates_on_limit(sample_project: Path, tmp_path: Path) -> None:
    result = collect_files(sample_project, use_git=False)
    stat_result, out = _pack(sample_project, tmp_path)
    # Nothing was dropped to fit: what got packed is what the ignore rules chose.
    packed = set(_members(out))
    expected = set(result.files) - {entry.path for entry in stat_result.skipped}
    assert packed == expected

    with pytest.raises(CliError) as excinfo:
        check_limits(stat_result, Limits(max_package_mb=0, max_unpacked_mb=0, max_package_entries=1))
    assert excinfo.value.exit_code == EXIT_LOCAL_INVALID
    assert "整包拒绝" in excinfo.value.message or "拒绝" in excinfo.value.message


def test_oversize_report_lists_excluded_count_then_top10(sample_project: Path, tmp_path: Path) -> None:
    stat_result, _ = _pack(sample_project, tmp_path)
    report = format_size_report(stat_result, Limits(max_package_mb=0, max_unpacked_mb=0, max_package_entries=1))
    # "Clean up your project" is useless advice on its own. The first reflex is
    # "the platform limit is too small"; the excluded count answers that before
    # the Top-10 list names what to do next.
    assert report.index("已排除") < report.index("Top")
    assert "entrypoint.sh" in report or "main.py" in report


def test_entry_count_limit_is_enforced(sample_project: Path, tmp_path: Path) -> None:
    stat_result, _ = _pack(sample_project, tmp_path)
    with pytest.raises(CliError):
        check_limits(stat_result, Limits(max_package_mb=999, max_unpacked_mb=999, max_package_entries=1))


def test_within_limits_passes_quietly(sample_project: Path, tmp_path: Path) -> None:
    stat_result, _ = _pack(sample_project, tmp_path)
    check_limits(stat_result, DEFAULT_LIMITS)


def test_limits_endpoint_returns_server_values() -> None:
    mock = PlatformMock().get("/api/v2/apps/deploy-limits", deploy_limits(max_package_mb=7))
    limits = fetch_limits(PlatformClient("http://p.test", api_key=FAKE_KEY, transport=mock.transport))
    assert limits.max_package_mb == 7 and limits.degraded is False


def test_limits_endpoint_unreachable_falls_back_to_defaults_and_proceeds() -> None:
    # A soft self-check must never be able to kill the main flow: if the endpoint
    # is missing or flaky we upload anyway and let the server's 16201 decide.
    mock = PlatformMock().get("/api/v2/apps/deploy-limits", httpx.ConnectError("refused"))
    limits = fetch_limits(PlatformClient("http://p.test", api_key=FAKE_KEY, transport=mock.transport))
    assert limits.max_package_mb == DEFAULT_LIMITS.max_package_mb
    assert limits.degraded is True


def test_limits_endpoint_error_code_also_falls_back() -> None:
    from tests.helpers.platform_mock import v2_error

    mock = PlatformMock().get("/api/v2/apps/deploy-limits", v2_error(16207, "layer off"))
    limits = fetch_limits(PlatformClient("http://p.test", api_key=FAKE_KEY, transport=mock.transport))
    assert limits.degraded is True


def test_package_is_targz_not_zip(sample_project: Path, tmp_path: Path) -> None:
    _, out = _pack(sample_project, tmp_path)
    assert out.read_bytes()[:2] == b"\x1f\x8b"
    with tarfile.open(out, "r:gz"):
        pass


def test_directory_mode_of_source_tree_is_not_leaked(sample_project: Path, tmp_path: Path) -> None:
    script = sample_project / "entrypoint.sh"
    script.chmod(stat.S_IMODE(script.stat().st_mode) | 0o077)
    members = _members(_pack(sample_project, tmp_path)[1])
    assert members["entrypoint.sh"].mode == 0o755
