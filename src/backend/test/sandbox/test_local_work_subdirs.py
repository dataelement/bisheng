"""D12: local runs see output/ and scratch/ before the script starts, like container runs."""

from __future__ import annotations

import os

import pytest

from bisheng_langchain.gpts.tools.code_interpreter import local_executor, local_isolation
from bisheng_langchain.gpts.tools.code_interpreter.base_executor import BaseExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_isolation import ensure_work_subdirs


def test_creates_both_dirs_and_hands_them_to_the_uid(tmp_path) -> None:
    calls: list[tuple[str, int, int]] = []
    ensure_work_subdirs(str(tmp_path), 10042, chown=lambda p, u, g: calls.append((p, u, g)))
    assert (tmp_path / "output").is_dir()
    assert (tmp_path / "scratch").is_dir()
    assert sorted(calls) == [
        (str(tmp_path / "output"), 10042, 10042),
        (str(tmp_path / "scratch"), 10042, 10042),
    ]


def test_existing_entries_are_left_alone(tmp_path) -> None:
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "keep.txt").write_text("x")
    (tmp_path / "scratch").write_text("the script's own file")
    calls: list = []
    ensure_work_subdirs(str(tmp_path), 10001, chown=lambda *a: calls.append(a))
    assert (tmp_path / "output" / "keep.txt").read_text() == "x"
    assert (tmp_path / "scratch").read_text() == "the script's own file"
    assert calls == []


def test_planted_symlink_is_not_followed(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    os.symlink(outside, run_dir / "output")
    calls: list = []
    ensure_work_subdirs(str(run_dir), 10001, chown=lambda *a: calls.append(a))
    # The link is kept as is and never chowned through.
    assert os.path.islink(run_dir / "output")
    assert [c[0] for c in calls] == [str(run_dir / "scratch")]


def test_no_uid_skips_chown(tmp_path) -> None:
    ensure_work_subdirs(str(tmp_path), None, chown=lambda *a: pytest.fail("chown must not run"))
    assert (tmp_path / "output").is_dir() and (tmp_path / "scratch").is_dir()


def test_empty_subdirs_are_not_artifacts(tmp_path) -> None:
    ensure_work_subdirs(str(tmp_path), None)
    assert BaseExecutor._snapshot_files(str(tmp_path)) == {}


def test_off_mode_first_write_into_output_and_scratch_succeeds(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(local_executor, "isolation_mode", lambda: "off")
    code = "open('output/report.txt', 'w').write('r')\nopen('scratch/tmp.txt', 'w').write('t')\nprint('done')\n"
    exitcode, logs, _ = LocalExecutor.execute_code(code=code, work_dir=str(tmp_path), lang="python")
    assert exitcode == 0, logs
    assert (tmp_path / "output" / "report.txt").read_text() == "r"
    assert (tmp_path / "scratch" / "tmp.txt").read_text() == "t"


def test_isolated_paths_call_the_helper() -> None:
    # Both uid-mode entry points (fresh and retained run dir) create the dirs
    # after copy-in and before the script is written.
    import inspect

    for fn in (local_isolation.run_isolated, local_isolation._run_retained_once):
        src = inspect.getsource(fn)
        assert "ensure_work_subdirs(run_dir, uid)" in src
        assert src.index("ensure_work_subdirs(run_dir, uid)") < src.index("_write_script(")
