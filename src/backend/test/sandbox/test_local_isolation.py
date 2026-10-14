"""LocalExecutor uid isolation: the parts that do not need root.

Copy-in / copy-back, path rewriting, output bounding, the environment allowlist,
the uid pool's marker logic and the fail-closed paths. The end-to-end runs as a
pool uid live in ``test_local_isolation_root.py``.
"""

from __future__ import annotations

import os
import threading

import pytest

from bisheng.core.config.settings import SandboxConf
from bisheng_langchain.gpts.tools.code_interpreter import local_isolation, local_uid_pool, workspace_copy
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import (
    COPY_IN_SKIPPED_NOTICE,
    DISK_LIMIT_MSG,
    ISOLATION_UNAVAILABLE_MSG,
    LocalExecutor,
)
from bisheng_langchain.gpts.tools.code_interpreter.local_isolation import (
    IsolatedOutcome,
    LocalIsolationUnavailable,
)

IS_LINUX_ROOT = os.name == "posix" and os.uname().sysname == "Linux" and os.geteuid() == 0
HAS_PROC = os.path.exists(f"/proc/{os.getpid()}/stat")


@pytest.fixture
def conf(monkeypatch: pytest.MonkeyPatch, tmp_path) -> SandboxConf:
    value = SandboxConf(local_isolation="uid", local_run_root=str(tmp_path / "runs"))
    monkeypatch.setattr(local_isolation, "_conf", lambda: value)
    monkeypatch.setattr(local_isolation, "_prlimit_path", None)
    return value


# --- configuration ---------------------------------------------------------


def test_local_isolation_defaults_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BS_SANDBOX_CONF__LOCAL_ISOLATION", raising=False)
    assert SandboxConf().local_isolation == "off"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("off", "off"), ("OFF ", "off"), ("", "off"), ("uid", "uid"), ("UID", "uid"), ("of", "uid"), ("none", "uid")],
)
def test_only_an_explicit_off_disables_isolation(raw: str, expected: str) -> None:
    assert SandboxConf(local_isolation=raw).local_isolation == expected


def test_unreadable_conf_counts_as_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom():
        raise RuntimeError("settings not loaded")

    monkeypatch.setattr(local_isolation, "_conf", boom)
    assert local_isolation.isolation_mode() == "uid"


# --- path rewriting --------------------------------------------------------


def test_rewrite_paths_respects_component_boundaries() -> None:
    src, dst = "/root/.cache/bisheng/linsight/ab12cd34", "/tmp/run-x"
    text = f'open("{src}/a.txt"); os.chdir("{src}"); print("{src}ef/b"); x = {src}\n'
    out = local_isolation.rewrite_paths(text, src, dst)
    assert f'"{dst}/a.txt"' in out
    assert f'"{dst}"' in out
    assert f"{src}ef/b" in out
    assert out.endswith(f"x = {dst}\n")


def test_rewrite_paths_round_trip() -> None:
    src, dst = "/w/task", "/r/run-1"
    text = "File /w/task/output/a.png written"
    assert local_isolation.rewrite_paths(local_isolation.rewrite_paths(text, src, dst), dst, src) == text


# --- output bounding -------------------------------------------------------


def test_head_tail_keeps_both_ends() -> None:
    buf = local_isolation._HeadTail(head=4, tail=4)
    for chunk in (b"ab", b"cdEFGH", b"ijkl"):
        buf.feed(chunk)
    text = buf.text()
    assert text.startswith("abcd")
    assert text.endswith("ijkl")
    assert "4 bytes of output omitted" in text


def test_head_tail_untouched_when_small() -> None:
    buf = local_isolation._HeadTail(head=8, tail=8)
    buf.feed(b"hello")
    assert buf.text() == "hello"


# --- environment -----------------------------------------------------------


def test_child_env_is_an_allowlist(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("BS_MYSQL_PASSWORD", "x")
    monkeypatch.setenv("PYTHONPATH", "/app")
    monkeypatch.setenv("LD_PRELOAD", "/evil.so")
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    env = local_isolation.child_env(str(tmp_path))
    assert set(env) == {
        "PATH",
        "LANG",
        "LC_ALL",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "MPLCONFIGDIR",
        "USER",
        "LOGNAME",
        "TZ",
    }
    assert env["HOME"] == str(tmp_path)
    assert env["TMPDIR"] == os.path.join(str(tmp_path), ".tmp")
    assert env["MPLCONFIGDIR"] == os.path.join(str(tmp_path), ".mpl")
    assert env["USER"] == "sandbox"


# --- copy in ---------------------------------------------------------------


def _write(path, data: bytes = b"x") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def test_copy_in_takes_regular_files_only(tmp_path) -> None:
    src, dst = tmp_path / "w", tmp_path / "r"
    dst.mkdir()
    _write(str(src / "uploads" / "a.csv"), b"1,2")
    _write(str(src / "run.sh"), b"#!/bin/sh")
    os.chmod(src / "run.sh", 0o755)
    _write(str(src / ".hidden"), b"h")
    _write(str(src / "__pycache__" / "m.pyc"), b"c")
    os.symlink("/etc/passwd", src / "link")
    os.symlink(str(src / "uploads"), src / "dirlink")
    os.mkfifo(src / "fifo")

    result = workspace_copy.copy_in(str(src), str(dst), None, 1024, 1024)

    assert set(result.index) == {os.path.join("uploads", "a.csv"), "run.sh"}
    assert (dst / "uploads" / "a.csv").read_bytes() == b"1,2"
    assert os.stat(dst / "run.sh").st_mode & 0o777 == 0o755
    assert os.stat(dst / "uploads" / "a.csv").st_mode & 0o777 == 0o644
    for name in (".hidden", "__pycache__", "link", "dirlink", "fifo"):
        assert not os.path.lexists(dst / name)
    st = os.stat(src / "run.sh")
    assert result.index["run.sh"] == (st.st_size, st.st_mtime_ns)
    assert os.stat(dst / "run.sh").st_mtime_ns == st.st_mtime_ns


def test_copy_in_reports_oversized_and_over_total(tmp_path) -> None:
    src, dst = tmp_path / "w", tmp_path / "r"
    dst.mkdir()
    _write(str(src / "a.bin"), b"a" * 6)
    _write(str(src / "b.bin"), b"b" * 20)
    _write(str(src / "c.bin"), b"c" * 6)

    result = workspace_copy.copy_in(str(src), str(dst), None, file_limit=10, total_limit=10)

    assert list(result.index) == ["a.bin"]
    assert result.skipped == ["b.bin", "c.bin"]
    assert result.copied_bytes == 6


# --- copy back -------------------------------------------------------------


def _seeded(tmp_path):
    w, r = tmp_path / "w", tmp_path / "r"
    w.mkdir()
    r.mkdir()
    _write(str(w / "uploads" / "in.txt"), b"source")
    index = workspace_copy.copy_in(str(w), str(r), None, 1 << 20, 1 << 20).index
    return w, r, index


def test_copy_out_harvests_new_and_changed_files(tmp_path) -> None:
    w, r, index = _seeded(tmp_path)
    _write(str(r / "output" / "report.md"), b"# done")
    _write(str(r / "uploads" / "in.txt"), b"changed!")
    os.utime(r / "output" / "report.md", ns=(1_000_000_000, 1_000_000_000))

    written = workspace_copy.copy_out(str(r), str(w), index, set(), 1 << 20, 1 << 20)

    assert sorted(written) == [os.path.join("output", "report.md"), os.path.join("uploads", "in.txt")]
    assert (w / "output" / "report.md").read_bytes() == b"# done"
    assert (w / "uploads" / "in.txt").read_bytes() == b"changed!"
    assert os.stat(w / "output" / "report.md").st_mtime_ns == 1_000_000_000
    assert not [n for n in os.listdir(w / "output") if n.endswith(".tmp")]


def test_copy_out_skips_unchanged_files(tmp_path) -> None:
    w, r, index = _seeded(tmp_path)
    assert workspace_copy.copy_out(str(r), str(w), index, set(), 1 << 20, 1 << 20) == []


def test_copy_out_never_harvests_planted_entries(tmp_path) -> None:
    w, r, index = _seeded(tmp_path)
    os.symlink("/etc/passwd", r / "passwd")
    os.mkdir(r / "output")
    os.symlink("/etc", r / "output" / "etc")
    os.mkfifo(r / "pipe")
    _write(str(r / "orig.txt"), b"o")
    os.link(r / "orig.txt", r / "hard.txt")
    _write(str(r / "tmp_code_abc.py"), b"print(1)")
    _write(str(r / ".secret"), b"s")
    _write(str(r / "big.bin"), b"z" * 100)

    written = workspace_copy.copy_out(str(r), str(w), index, {"tmp_code_abc.py"}, 50, 1 << 20)

    assert written == []
    for name in ("passwd", "pipe", "orig.txt", "hard.txt", "tmp_code_abc.py", ".secret", "big.bin"):
        assert not os.path.lexists(w / name)
    assert not os.path.lexists(w / "output" / "etc")


def test_copy_out_refuses_a_symlinked_dir_in_the_workspace(tmp_path) -> None:
    w, r, index = _seeded(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, w / "output")
    _write(str(r / "output" / "a.txt"), b"a")

    assert workspace_copy.copy_out(str(r), str(w), index, set(), 1 << 20, 1 << 20) == []
    assert os.listdir(outside) == []


def test_copy_out_stops_at_the_total_budget(tmp_path) -> None:
    w, r, index = _seeded(tmp_path)
    _write(str(r / "a.bin"), b"a" * 30)
    _write(str(r / "b.bin"), b"b" * 30)

    written = workspace_copy.copy_out(str(r), str(w), index, set(), 1 << 20, 40)

    assert written == ["a.bin"]


# --- uid pool markers ------------------------------------------------------


def test_concurrent_acquire_hands_out_distinct_uids(tmp_path) -> None:
    markers, runs = str(tmp_path / "m"), str(tmp_path / "runs")
    got: list[int | None] = []
    lock = threading.Lock()

    def claim() -> None:
        uid = local_uid_pool.acquire(runs, marker_dir=markers)
        with lock:
            got.append(uid)

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert None not in got
    assert len(set(got)) == 8
    if HAS_PROC:
        assert local_uid_pool.held_uids(markers) == set(got)


@pytest.mark.skipif(not HAS_PROC, reason="without /proc every marker looks stale")
def test_stale_marker_is_reclaimed_live_one_is_not(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    markers, runs = tmp_path / "m", str(tmp_path / "runs")
    markers.mkdir()
    reaped: list[int] = []
    monkeypatch.setattr(local_uid_pool, "reap_uid", lambda uid: reaped.append(uid) or True)
    live = f"{os.getpid()} {local_uid_pool.proc_starttime(os.getpid()) or 0}"
    (markers / str(local_uid_pool.UID_MIN)).write_text(live)
    (markers / str(local_uid_pool.UID_MIN + 1)).write_text("999999999 1")

    uid = local_uid_pool.acquire(runs, marker_dir=str(markers))

    assert uid == local_uid_pool.UID_MIN + 1
    assert reaped == [local_uid_pool.UID_MIN + 1]


def test_free_removes_marker(tmp_path) -> None:
    markers, runs = str(tmp_path / "m"), str(tmp_path / "runs")
    uid = local_uid_pool.acquire(runs, marker_dir=markers)
    local_uid_pool.free(uid, runs, marker_dir=markers)
    assert not os.path.exists(os.path.join(markers, str(uid)))


def test_reap_refuses_uids_outside_the_pool() -> None:
    with pytest.raises(ValueError):
        local_uid_pool.reap_uid(0)


# --- probe evaluation and permission tightening ----------------------------


def _good_probe(uid: int) -> dict:
    return {
        "uid": uid,
        "euid": uid,
        "gid": uid,
        "groups": [],
        "environ": True,
        "root_home": True,
        "config": True,
        "pkg": True,
        "data": True,
        "imports": None,
        "write": None,
    }


def test_probe_accepts_expected_denials() -> None:
    local_isolation.evaluate_probe(_good_probe(30001), 30001)


@pytest.mark.parametrize(
    ("key", "value", "fragment"),
    [
        ("config", False, "config.yaml"),
        ("pkg", False, "backend package dir"),
        ("environ", False, "/proc/1/environ"),
        ("groups", [0], "supplementary groups"),
        ("uid", 0, "child identity"),
        ("imports", "ImportError('numpy')", "numpy"),
        ("write", "PermissionError()", "cannot write"),
    ],
)
def test_probe_rejects_leaks(key: str, value, fragment: str) -> None:
    probe = _good_probe(30001)
    probe[key] = value
    with pytest.raises(LocalIsolationUnavailable, match=fragment):
        local_isolation.evaluate_probe(probe, 30001)


def test_probe_only_warns_on_readable_data_dir() -> None:
    probe = _good_probe(30001)
    probe["data"] = False
    local_isolation.evaluate_probe(probe, 30001)


def test_tighten_permissions_closes_both_dirs(tmp_path) -> None:
    pkg, data = tmp_path / "bisheng", tmp_path / "data"
    pkg.mkdir(mode=0o755)
    data.mkdir(mode=0o755)
    (pkg / "config.yaml").write_text("x: 1")

    local_isolation.tighten_permissions(str(pkg), str(data))

    assert os.stat(pkg).st_mode & 0o777 == 0o700
    assert os.stat(data).st_mode & 0o777 == 0o700


# --- fail closed -----------------------------------------------------------


@pytest.mark.skipif(IS_LINUX_ROOT, reason="preflight can succeed here")
def test_preflight_fails_closed_without_root(conf: SandboxConf) -> None:
    with pytest.raises(LocalIsolationUnavailable):
        local_isolation.preflight()


@pytest.mark.skipif(IS_LINUX_ROOT, reason="preflight can succeed here")
def test_run_reports_unavailable_and_executes_nothing(conf: SandboxConf, tmp_path) -> None:
    marker = tmp_path / "ran"
    executor = LocalExecutor(minio={}, local_sync_path=str(tmp_path))
    result = executor.run(f"open({str(marker)!r}, 'w').write('x')")
    assert result == {"exitcode": 1, "log": ISOLATION_UNAVAILABLE_MSG, "file_list": []}
    assert not marker.exists()


def test_isolated_execute_needs_a_work_dir(conf: SandboxConf) -> None:
    with pytest.raises(AssertionError, match="work_dir"):
        LocalExecutor.execute_code(code="print(1)", work_dir=None)


def test_font_cache_is_only_dropped_when_off(monkeypatch: pytest.MonkeyPatch, conf: SandboxConf) -> None:
    drops: list[int] = []
    monkeypatch.setattr(LocalExecutor, "_drop_font_cache", staticmethod(lambda: drops.append(1)))
    LocalExecutor.insert_set_font_code("import matplotlib\n")
    assert drops == []
    conf.local_isolation = "off"
    LocalExecutor.insert_set_font_code("import matplotlib\n")
    assert drops == [1]


# --- result formatting -----------------------------------------------------


def test_format_reports_disk_limit_and_skipped_files(tmp_path) -> None:
    outcome = IsolatedOutcome(returncode=1, stdout="", stderr="", disk_exceeded=True, skipped=["big.bin"])
    code, logs, _ = LocalExecutor._format_isolated(outcome, 10, "tmp_code_x.py", str(tmp_path))
    assert code == 1
    assert logs.startswith(DISK_LIMIT_MSG)
    assert COPY_IN_SKIPPED_NOTICE in logs and "big.bin" in logs


def test_format_strips_the_script_path_from_a_traceback(tmp_path) -> None:
    script = os.path.join(str(tmp_path), "tmp_code_x.py")
    stderr = f'File "{script}", line 1\nValueError: boom\n'
    outcome = IsolatedOutcome(returncode=1, stdout="", stderr=stderr)
    code, logs, _ = LocalExecutor._format_isolated(outcome, 10, "tmp_code_x.py", str(tmp_path))
    assert code == 1
    assert str(tmp_path) not in logs
    assert "ValueError: boom" in logs
