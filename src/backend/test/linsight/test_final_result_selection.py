"""Deliverable selection must not depend on the answer text or on walk order.

The legacy rule in ``get_final_result_file`` accepted a file as a deliverable when
its path was under ``output/`` **OR its name appeared verbatim in the model's final
answer**. That second clause failed in both directions:

* too weak — a model that finishes with "最终交付物是一个 Excel 格式的文件" (no file
  name) matched nothing, so a real deliverable was dropped and the result panel fell
  back to a synthesized ``报告.md`` that contradicted the answer;
* too strong — an uploaded source the model merely referenced was promoted to
  deliverable, and because ``os.walk`` is top-down the root-level source outranked
  the real ``output/`` file and became the "已为您整理好 X" headline.

The replacement is structural: the ``output/`` zone, falling back to "files this run
created" (diffed against a start-of-task baseline), never ``scratch/``/``uploads/``,
ordered newest-first.
"""

from __future__ import annotations

import os

from bisheng.linsight.domain.utils import read_file_directory, select_deliverables, snapshot_file_paths


def _detail(rel_path: str, *, mtime: float = 0.0, root: str = "/ws") -> dict:
    return {
        "file_name": os.path.basename(rel_path),
        "file_path": os.path.join(root, rel_path),
        "rel_path": rel_path,
        "file_mtime": mtime,
        "file_md5": "md5-" + rel_path,
        "file_id": "id-" + rel_path,
    }


def _names(selected: list[dict]) -> list[str]:
    return [f["rel_path"] for f in selected]


# ---------------------------------------------------------------------------
# criterion 1: the output/ zone
# ---------------------------------------------------------------------------
def test_output_zone_files_are_the_deliverables():
    details = [
        _detail("需求文档.md"),
        _detail("output/报告.xlsx"),
        _detail("scratch/tmp.png"),
    ]
    assert _names(select_deliverables(details)) == ["output/报告.xlsx"]


def test_scratch_and_uploads_are_never_deliverables():
    """Even with output/ empty and everything newly created, intermediate state and
    the user's own sources stay out of the result panel."""
    details = [_detail("scratch/step1.csv"), _detail("uploads/source.md")]
    baseline: set[str] = set()
    assert select_deliverables(details, baseline_paths=baseline) == []


def test_output_zone_wins_over_newer_root_file():
    """Criteria are ordered, not merged: a newer root file does not displace the
    output/ deliverable."""
    details = [
        _detail("output/报告.xlsx", mtime=100.0),
        _detail("draft.txt", mtime=999.0),
    ]
    assert _names(select_deliverables(details, baseline_paths=set())) == ["output/报告.xlsx"]


# ---------------------------------------------------------------------------
# criterion 2: files this run created
# ---------------------------------------------------------------------------
def test_run_created_file_outside_output_is_still_delivered():
    """A deliverable written to an off-contract path is still a deliverable —
    this is what used to depend on the model naming the file in its answer."""
    details = [_detail("卢旺达市场工程基线.xlsx", mtime=10.0)]
    assert _names(select_deliverables(details, baseline_paths=set())) == ["卢旺达市场工程基线.xlsx"]


def test_preexisting_upload_source_is_not_a_deliverable():
    """The exact false positive the answer-match clause produced: a prefetched
    upload source sitting at the working-dir root."""
    details = [_detail("需求文档.md", mtime=10.0)]
    baseline = {os.path.join("/ws", "需求文档.md")}
    assert select_deliverables(details, baseline_paths=baseline) == []


def test_answer_text_has_no_influence():
    """select_deliverables takes no answer argument at all — mentioning a source
    file in the final message can no longer promote it."""
    details = [_detail("需求文档.md", mtime=10.0), _detail("output/报告.md", mtime=1.0)]
    baseline = {os.path.join("/ws", "需求文档.md")}
    assert _names(select_deliverables(details, baseline_paths=baseline)) == ["output/报告.md"]


def test_without_baseline_the_second_criterion_is_skipped():
    """No baseline (older sessions / defensive callers) => do not guess. Returning
    the whole working dir would deliver the user's own uploads back to them."""
    details = [_detail("需求文档.md", mtime=10.0)]
    assert select_deliverables(details, baseline_paths=None) == []


# ---------------------------------------------------------------------------
# ordering: type first, recency second — [0] is the frontend's headline file
# ---------------------------------------------------------------------------
def test_same_type_files_are_ordered_newest_first():
    details = [
        _detail("output/a.md", mtime=1.0),
        _detail("output/c.md", mtime=3.0),
        _detail("output/b.md", mtime=2.0),
    ]
    assert _names(select_deliverables(details)) == ["output/c.md", "output/b.md", "output/a.md"]


def test_report_outranks_the_charts_it_generated_last():
    """The exact case recency-only ordering gets wrong: a task writes its report,
    then renders charts into output/. Newest is a PNG; the deliverable is not."""
    details = [
        _detail("output/报告.docx", mtime=100.0),
        _detail("output/chart1.png", mtime=200.0),
        _detail("output/chart2.png", mtime=300.0),
    ]
    assert _names(select_deliverables(details))[0] == "output/报告.docx"


def test_type_ranking_orders_document_sheet_unknown_image():
    details = [
        _detail("output/pic.png", mtime=50.0),
        _detail("output/bundle.zip", mtime=50.0),
        _detail("output/data.xlsx", mtime=50.0),
        _detail("output/report.pdf", mtime=50.0),
    ]
    assert _names(select_deliverables(details)) == [
        "output/report.pdf",
        "output/data.xlsx",
        "output/bundle.zip",
        "output/pic.png",
    ]


def test_unknown_extension_still_outranks_an_image():
    """A .zip/.ipynb can legitimately BE the deliverable; a chart never is."""
    details = [_detail("output/chart.png", mtime=999.0), _detail("output/export.zip", mtime=1.0)]
    assert _names(select_deliverables(details))[0] == "output/export.zip"


def test_missing_mtime_sorts_last_without_crashing():
    details = [{"file_name": "x.md", "file_path": "/ws/output/x.md", "rel_path": "output/x.md"}]
    details.append(_detail("output/y.md", mtime=5.0))
    assert _names(select_deliverables(details)) == ["output/y.md", "output/x.md"]


def test_rel_path_falls_back_to_basename_when_absent():
    """Defensive: a caller-built detail dict without rel_path must not crash, and a
    bare basename reads as a root-level file (no zone)."""
    details = [{"file_name": "x.md", "file_path": "/ws/x.md", "file_mtime": 1.0}]
    assert select_deliverables(details, baseline_paths=set())[0]["file_name"] == "x.md"


# ---------------------------------------------------------------------------
# the inputs those criteria rely on
# ---------------------------------------------------------------------------
def test_snapshot_file_paths_lists_absolute_paths(tmp_path):
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "b.md").write_text("b")

    snap = snapshot_file_paths(str(tmp_path))

    assert snap == {str(tmp_path / "a.md"), str(tmp_path / "output" / "b.md")}


def test_snapshot_file_paths_tolerates_missing_dir():
    assert snapshot_file_paths("/tmp/definitely-not-a-linsight-dir-xyz") == set()
    assert snapshot_file_paths("") == set()


async def test_read_file_directory_carries_zone_and_mtime(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "报告.md").write_text("hi")

    details = await read_file_directory(str(tmp_path))

    assert len(details) == 1
    assert details[0]["rel_path"] == os.path.join("output", "报告.md")
    assert details[0]["file_mtime"] > 0
    # and that detail flows straight into selection as an output/ deliverable
    assert _names(select_deliverables(details)) == [os.path.join("output", "报告.md")]
