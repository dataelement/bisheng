"""Root-level code-interpreter output must be normalised into ``output/``.

Second half of the "deliverable vanished" story. The absolute-path case
(``/output/report.pdf``) is covered by ``test_code_interpreter_output_path``; this
one covers the far more common RELATIVE-but-zoneless case:

    open("report.xlsx", "w")        # lands at the working-dir ROOT

The LocalExecutor runs code with ``cwd`` = the linsight task's ``file_dir``, and
``get_final_result_file`` only harvests ``file_dir/output/``. So a root-level write
produced a real file that was never delivered — the result panel fell back to a
synthesized ``报告.md`` while the model's own answer claimed an Excel file existed.

The fix diffs a pre/post-run snapshot of the working dir, moves files THIS RUN
created at the root into ``output/``, and appends a notice with the new paths so the
model's follow-up reads do not hit a path that no longer resolves.

Real subprocess execution (so the ``cwd`` contract is exercised for real); MinIO is
disabled via ``minio={}`` so ``upload_minio`` short-circuits to "".
"""

from __future__ import annotations

import os

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import (
    RELOCATED_PATH_NOTICE_HEADER,
    BaseExecutor,
)
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor


def _executor(tmp_path) -> LocalExecutor:
    exe = LocalExecutor(minio={})
    exe.local_sync_path = str(tmp_path)
    return exe


def _run(exe: LocalExecutor, tmp_path, code: str):
    return exe.run_with_dir(code, dir_path=str(tmp_path), lang="python")


# ---------------------------------------------------------------------------
# relocation_advisory: pure formatting helper
# ---------------------------------------------------------------------------
def test_relocation_advisory_empty_when_nothing_moved():
    assert BaseExecutor.relocation_advisory([]) == ""


def test_relocation_advisory_lists_old_and_new_paths():
    notice = BaseExecutor.relocation_advisory([("a.xlsx", "output/a.xlsx")])
    assert notice.startswith(RELOCATED_PATH_NOTICE_HEADER)
    assert "- a.xlsx -> output/a.xlsx" in notice


# ---------------------------------------------------------------------------
# _snapshot_files: what counts as workspace content
# ---------------------------------------------------------------------------
def test_snapshot_skips_hidden_and_pycache(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "m.pyc").write_text("x")
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "r.md").write_text("x")

    snap = LocalExecutor._snapshot_files(str(tmp_path))

    assert set(snap) == {"keep.txt", os.path.join("output", "r.md")}


# ---------------------------------------------------------------------------
# the actual bug: root-level write becomes a deliverable
# ---------------------------------------------------------------------------
def test_root_level_new_file_is_moved_into_output(tmp_path):
    exe = _executor(tmp_path)
    exitcode, logs, _ = _run(exe, tmp_path, "open('report.xlsx', 'w').write('data')")

    assert exitcode == 0
    assert not (tmp_path / "report.xlsx").exists()
    assert (tmp_path / "output" / "report.xlsx").read_text() == "data"
    # the model is told where the file went, so its next read does not 404
    assert RELOCATED_PATH_NOTICE_HEADER in logs
    assert "- report.xlsx -> output/report.xlsx" in logs


def test_files_written_into_zones_are_left_alone(tmp_path):
    exe = _executor(tmp_path)
    code = (
        "import os\n"
        "os.makedirs('output', exist_ok=True)\n"
        "os.makedirs('scratch', exist_ok=True)\n"
        "open('output/final.md', 'w').write('final')\n"
        "open('scratch/tmp.png', 'w').write('tmp')\n"
    )
    exitcode, logs, _ = _run(exe, tmp_path, code)

    assert exitcode == 0
    assert (tmp_path / "output" / "final.md").read_text() == "final"
    assert (tmp_path / "scratch" / "tmp.png").read_text() == "tmp"
    # nothing was at the root, so no relocation and no notice
    assert RELOCATED_PATH_NOTICE_HEADER not in logs


def test_preexisting_root_files_are_never_moved(tmp_path):
    """The prefetched uploaded sources live at the working-dir root. Moving them
    would both corrupt the source zone and make them impersonate deliverables —
    only files the run CREATED are eligible."""
    (tmp_path / "需求文档.md").write_text("user upload")
    exe = _executor(tmp_path)

    exitcode, logs, _ = _run(exe, tmp_path, "print(open('需求文档.md').read())")

    assert exitcode == 0
    assert (tmp_path / "需求文档.md").exists()
    assert not (tmp_path / "output" / "需求文档.md").exists()
    assert RELOCATED_PATH_NOTICE_HEADER not in logs


def test_rerun_overwrites_instead_of_accumulating(tmp_path):
    """ "运行代码 3 次" must leave ONE deliverable, not report.xlsx + copies."""
    exe = _executor(tmp_path)
    for payload in ("v1", "v2", "v3"):
        exitcode, _, _ = _run(exe, tmp_path, f"open('report.xlsx', 'w').write({payload!r})")
        assert exitcode == 0

    produced = sorted(p.name for p in (tmp_path / "output").iterdir())
    assert produced == ["report.xlsx"]
    assert (tmp_path / "output" / "report.xlsx").read_text() == "v3"


def test_failed_run_relocates_nothing(tmp_path):
    exe = _executor(tmp_path)
    exitcode, logs, file_list = _run(exe, tmp_path, "open('half.txt', 'w').write('x')\nraise SystemExit(3)")

    assert exitcode != 0
    assert file_list == []
    assert RELOCATED_PATH_NOTICE_HEADER not in logs
    # the partial write stays where the script put it; a failed run has no deliverable
    assert (tmp_path / "half.txt").exists()


# ---------------------------------------------------------------------------
# file_list is scoped to THIS run
# ---------------------------------------------------------------------------
def test_file_list_covers_only_this_runs_files(tmp_path, monkeypatch):
    """Previously every run re-uploaded the whole working dir, so the tool result
    grew with the task and said nothing about what the code just wrote."""
    (tmp_path / "preexisting.md").write_text("old")
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "earlier.md").write_text("earlier step")

    uploaded: list[str] = []
    exe = _executor(tmp_path)
    monkeypatch.setattr(exe, "upload_minio", lambda object_name, file_path: uploaded.append(file_path) or "url")

    exitcode, _, file_list = _run(exe, tmp_path, "open('fresh.csv', 'w').write('a,b')")

    assert exitcode == 0
    assert len(file_list) == 1
    assert [os.path.relpath(p, str(tmp_path)) for p in uploaded] == [os.path.join("output", "fresh.csv")]


def test_modified_preexisting_file_is_reported_but_not_moved(tmp_path, monkeypatch):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "final.md").write_text("v1")

    uploaded: list[str] = []
    exe = _executor(tmp_path)
    monkeypatch.setattr(exe, "upload_minio", lambda object_name, file_path: uploaded.append(file_path) or "url")

    exitcode, logs, _ = _run(exe, tmp_path, "open('output/final.md', 'w').write('v2-longer')")

    assert exitcode == 0
    assert (tmp_path / "output" / "final.md").read_text() == "v2-longer"
    assert [os.path.relpath(p, str(tmp_path)) for p in uploaded] == [os.path.join("output", "final.md")]
    assert RELOCATED_PATH_NOTICE_HEADER not in logs
