"""Code-interpreter deliverables must land under the RELATIVE ``output/`` dir.

Root cause of the "PDF vanished from the workspace" bug: the model wrote the
deliverable to an ABSOLUTE path (``/output/report.pdf``) which resolves to the
container filesystem root — outside the per-task working dir the executor harvests
into the linsight workspace. The file was uploaded nowhere (``file_list == []``),
never synced, never picked up by ``get_final_result_file``, and the result panel
fell back to a synthesized ``报告.md``.

The shared LocalExecutor cannot safely rescue container-root files (that would leak
one task's output into another), so the fix is: (1) a strict relative-path contract
in the tool description, and (2) a deterministic, non-blocking corrective notice
appended to the tool result whenever a run wrote to an absolute ``/output``/
``/scratch`` path, so the model self-corrects on the next step.

These tests cover the detection helper and the LocalExecutor notice wiring; no real
subprocess / matplotlib / MinIO is involved.
"""

from __future__ import annotations

import pytest

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import (
    ABSOLUTE_PATH_NOTICE,
    BaseExecutor,
)
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor


# ---------------------------------------------------------------------------
# absolute_path_advisory: flags leading-slash /output|/scratch string literals only
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code",
    [
        "with open('/output/report.pdf', 'wb') as f: f.write(b'x')",
        'plt.savefig("/scratch/chart.png")',
        "pdf.output('/output/油脂油料市场早报.pdf')",
        "open('/output')",  # no trailing slash, still absolute deliverable root
        "open('/scratch')",
    ],
)
def test_advisory_flags_absolute_deliverable_paths(code):
    assert BaseExecutor.absolute_path_advisory(code) == ABSOLUTE_PATH_NOTICE


@pytest.mark.parametrize(
    "code",
    [
        "with open('output/report.pdf', 'wb') as f: f.write(b'x')",  # relative — correct
        "plt.savefig('scratch/chart.png')",  # relative — correct
        "open('./output/report.pdf')",  # relative with ./
        "url = 'https://host/output/y'",  # /output mid-string, not a path root
        "open('/data/output/x')",  # path root is /data, not /output
        "p = '/outputs/x'",  # different word (/outputs), not /output
        "print('hello world')",
        "",
        None,
    ],
)
def test_advisory_silent_for_relative_or_unrelated(code):
    assert BaseExecutor.absolute_path_advisory(code) == ""


# ---------------------------------------------------------------------------
# LocalExecutor.run: appends the corrective notice for absolute-path writes
# ---------------------------------------------------------------------------
def _make_executor(monkeypatch):
    """LocalExecutor with subprocess execution + matplotlib font side effects
    stubbed out, so run() exercises only the loop + notice-append logic."""
    exe = LocalExecutor(minio={})
    exe.local_sync_path = None  # take the TemporaryDirectory branch
    # stub the actual run so no python subprocess is spawned
    monkeypatch.setattr(exe, "run_with_dir", lambda code, dir_path, lang: (0, "stdout-ok\n", []))
    # stub the matplotlib font injection (touches the mpl cache otherwise)
    monkeypatch.setattr(exe, "insert_set_font_code", lambda code: code)
    return exe


def test_run_appends_notice_for_absolute_output(monkeypatch):
    exe = _make_executor(monkeypatch)
    result = exe.run("with open('/output/report.pdf', 'wb') as f:\n    f.write(b'x')")
    assert result["exitcode"] == 0
    assert ABSOLUTE_PATH_NOTICE in result["log"]
    # original stdout is preserved alongside the notice
    assert "stdout-ok" in result["log"]


def test_run_no_notice_for_relative_output(monkeypatch):
    exe = _make_executor(monkeypatch)
    result = exe.run("with open('output/report.pdf', 'wb') as f:\n    f.write(b'x')")
    assert result["exitcode"] == 0
    assert ABSOLUTE_PATH_NOTICE not in result["log"]
    assert "stdout-ok" in result["log"]


def test_run_notice_uses_original_code_not_last_block(monkeypatch):
    """The notice keys off the full submitted script, not the loop's reassigned
    ``code`` var (which would otherwise hold only the last code block)."""
    exe = _make_executor(monkeypatch)
    result = exe.run("import os\nos.makedirs('/scratch/charts', exist_ok=True)\nprint('done')")
    assert ABSOLUTE_PATH_NOTICE in result["log"]


def test_run_failure_path_returns_without_notice(monkeypatch):
    exe = LocalExecutor(minio={})
    exe.local_sync_path = None
    monkeypatch.setattr(exe, "insert_set_font_code", lambda code: code)
    monkeypatch.setattr(exe, "run_with_dir", lambda code, dir_path, lang: (1, "boom\n", []))
    result = exe.run("open('/output/x.pdf', 'wb')")
    assert result["exitcode"] == 1
    assert "log" in result
    # failure path returns early — no file_list, no notice appended
    assert "file_list" not in result
