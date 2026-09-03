"""Task-mode FOLDER upload: keep the user's directory tree inside the workspace.

Before this, every attachment landed flat in ``uploads/`` because
``_safe_basename`` collapsed path separators to ``_``. These tests pin the three
things that had to change for a folder to survive the trip:

  - ``_safe_relpath`` — a path-PRESERVING sanitizer (traversal still neutralized)
  - ``_dedupe_workspace_name`` — uniqueness scoped to the full relative path, so
    two ``summary.md`` in different directories stop overwriting each other
  - ``_write_attachment_to_workspace`` — nested object keys for both tracks
    (markdown view + raw original)

plus the submit-time batch gate (`_validate_folder_upload`) and the pointer-block
rendering that keeps a large folder from flooding the first user message.

External services (Redis, MinIO) are mocked; no live middleware required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.linsight import (
    LinsightFolderDepthExceededError,
    LinsightFolderFileCountExceededError,
    LinsightFolderTotalSizeExceededError,
)
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.schemas.linsight_schema import SubmitFileSchema
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl as Impl


class FakeMinio:
    def __init__(self) -> None:
        self.bucket = "bisheng"
        self.tmp_bucket = "tmp-dir"
        self.store: dict[tuple[str, str], bytes] = {}

    async def object_exists(self, bucket_name=None, object_name=None):
        return (bucket_name or self.bucket, object_name) in self.store

    async def copy_object(self, source_bucket=None, source_object=None, dest_bucket=None, dest_object=None):
        src = self.store.get((source_bucket or self.tmp_bucket, source_object), b"parsed-md")
        self.store[(dest_bucket or self.bucket, dest_object)] = src

    async def get_object(self, bucket_name=None, object_name=None):
        return self.store.get((bucket_name or self.bucket, object_name))

    async def put_object(self, *, bucket_name=None, object_name, file, **kwargs):
        self.store[(bucket_name or self.bucket, object_name)] = file if isinstance(file, bytes) else bytes(file)


def _submit(file_id="f1", name="Q1.xlsx", rel=None, size=0):
    return SubmitFileSchema(
        file_id=file_id,
        file_name=name,
        parsing_status="completed",
        relative_path=rel,
        size=size,
    )


def _temp_info(file_id="f1", name="Q1.xlsx"):
    return {
        "file_id": file_id,
        "original_filename": name,
        "parsing_status": "completed",
        "markdown_filename": f"{file_id}.md",
        "markdown_file_path": f"{file_id}.md",
    }


def _session(files):
    return LinsightSessionVersion(session_id="chat1", user_id=1, question="q", files=files)


# ---------------------------------------------------------------------------
# _safe_relpath — preserve the tree, neutralize traversal
# ---------------------------------------------------------------------------
def test_safe_relpath_keeps_nested_directories():
    assert Impl._safe_relpath("年报/2024/Q1.xlsx") == "年报/2024"
    assert Impl._safe_relpath("Docs/a.pdf") == "Docs"


def test_safe_relpath_flat_inputs_yield_no_directory():
    """A plain single-file upload must keep the historical flat layout."""
    assert Impl._safe_relpath(None) == ""
    assert Impl._safe_relpath("") == ""
    assert Impl._safe_relpath("   ") == ""
    assert Impl._safe_relpath("report.pdf") == ""


@pytest.mark.parametrize(
    "crafted",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "a/../../../b/c.pdf",
        "./x/./y/z.pdf",
        "..\\..\\windows\\system32\\cfg.txt",
    ],
)
def test_safe_relpath_cannot_escape_uploads(crafted):
    """Every `.`/`..`/empty segment is dropped, so the result is always relative
    and always lands under ``uploads/``."""
    result = Impl._safe_relpath(crafted)
    assert not result.startswith("/")
    assert ".." not in result.split("/")
    assert "." not in result.split("/")


def test_safe_relpath_clamps_depth():
    deep = "/".join(f"d{i}" for i in range(20)) + "/f.txt"
    assert len(Impl._safe_relpath(deep).split("/")) == Impl._FOLDER_MAX_DEPTH


def test_safe_relpath_sanitizes_each_segment():
    """Control characters die per segment, non-ASCII names survive."""
    assert Impl._safe_relpath("年\x01报/2024/a.pdf") == "年报/2024"


# ---------------------------------------------------------------------------
# _dedupe_workspace_name — uniqueness namespace is the FULL relative path
# ---------------------------------------------------------------------------
def test_same_name_in_different_directories_does_not_collide():
    used: set[str] = set()
    a = Impl._dedupe_workspace_name("报告/summary.md", used)
    b = Impl._dedupe_workspace_name("附件/summary.md", used)
    assert a == "报告/summary.md"
    assert b == "附件/summary.md"


def test_real_collision_suffixes_the_filename_not_the_directory():
    used: set[str] = set()
    Impl._dedupe_workspace_name("v1.2/report.pdf", used)
    second = Impl._dedupe_workspace_name("v1.2/report.pdf", used)
    # The directory keeps its dot; only the file name gets the -2 marker.
    assert second == "v1.2/report-2.pdf"


def test_flat_dedupe_behaviour_unchanged():
    used: set[str] = set()
    assert Impl._dedupe_workspace_name("a.md", used) == "a.md"
    assert Impl._dedupe_workspace_name("a.md", used) == "a-2.md"
    assert Impl._dedupe_workspace_name("a.md", used) == "a-3.md"


# ---------------------------------------------------------------------------
# _validate_folder_upload — all-or-nothing batch gate
# ---------------------------------------------------------------------------
def test_plain_multi_file_selection_is_not_gated():
    """No relative_path anywhere => not a folder upload => historical behaviour."""
    files = [_submit(file_id=f"f{i}", name=f"{i}.pdf") for i in range(Impl._FOLDER_MAX_FILES + 5)]
    Impl._validate_folder_upload(files)  # must not raise


def test_folder_file_count_is_capped():
    files = [_submit(file_id=f"f{i}", name=f"{i}.pdf", rel=f"docs/{i}.pdf") for i in range(Impl._FOLDER_MAX_FILES + 1)]
    with pytest.raises(LinsightFolderFileCountExceededError):
        Impl._validate_folder_upload(files)


def test_folder_total_size_is_capped():
    half = Impl._FOLDER_MAX_TOTAL_BYTES // 2 + 1
    files = [
        _submit(file_id="f1", name="a.pdf", rel="docs/a.pdf", size=half),
        _submit(file_id="f2", name="b.pdf", rel="docs/b.pdf", size=half),
    ]
    with pytest.raises(LinsightFolderTotalSizeExceededError):
        Impl._validate_folder_upload(files)


def test_folder_depth_is_capped():
    deep = "/".join(f"d{i}" for i in range(Impl._FOLDER_MAX_DEPTH + 1)) + "/f.pdf"
    with pytest.raises(LinsightFolderDepthExceededError):
        Impl._validate_folder_upload([_submit(rel=deep)])


def test_folder_at_exactly_the_limits_is_accepted():
    deep = "/".join(f"d{i}" for i in range(Impl._FOLDER_MAX_DEPTH)) + "/f.pdf"
    files = [_submit(file_id=f"f{i}", name=f"{i}.pdf", rel=deep) for i in range(Impl._FOLDER_MAX_FILES)]
    Impl._validate_folder_upload(files)  # must not raise


# ---------------------------------------------------------------------------
# End-to-end ingestion: nested object keys for both tracks
# ---------------------------------------------------------------------------
async def _ingest(submits, temp_infos):
    fake_minio = FakeMinio()
    fake_redis = AsyncMock()
    for info in temp_infos:
        fake_minio.store[(fake_minio.tmp_bucket, info["markdown_file_path"])] = b"# T\nbody\n"
    fake_redis.amget.return_value = temp_infos

    with (
        patch.object(Impl, "_get_redis", return_value=fake_redis),
        patch(
            "bisheng.linsight.domain.services.workbench_impl.get_minio_storage",
            new=AsyncMock(return_value=fake_minio),
        ),
    ):
        result = await Impl._process_submitted_files(submits, "svid1")
    return result, fake_minio


async def test_folder_upload_rebuilds_the_tree_in_the_workspace():
    submits = [_submit(file_id="f1", name="Q1.xlsx", rel="年报/2024/Q1.xlsx")]
    result, minio = await _ingest(submits, [_temp_info("f1", "Q1.xlsx")])

    assert result[0]["workspace_path"] == "/uploads/年报/2024/Q1.md"
    assert ("bisheng", "workspace/svid1/uploads/年报/2024/Q1.md") in minio.store


async def test_flat_upload_layout_is_untouched():
    submits = [_submit(file_id="f1", name="My Report.pdf")]
    result, minio = await _ingest(submits, [_temp_info("f1", "My Report.pdf")])

    assert result[0]["workspace_path"] == "/uploads/My Report.md"
    assert ("bisheng", "workspace/svid1/uploads/My Report.md") in minio.store


async def test_same_filename_in_two_directories_both_survive():
    """The pre-change flat namespace silently overwrote the first file."""
    submits = [
        _submit(file_id="f1", name="summary.pdf", rel="报告/summary.pdf"),
        _submit(file_id="f2", name="summary.pdf", rel="附件/summary.pdf"),
    ]
    result, minio = await _ingest(submits, [_temp_info("f1", "summary.pdf"), _temp_info("f2", "summary.pdf")])

    assert result[0]["workspace_path"] == "/uploads/报告/summary.md"
    assert result[1]["workspace_path"] == "/uploads/附件/summary.md"
    assert ("bisheng", "workspace/svid1/uploads/报告/summary.md") in minio.store
    assert ("bisheng", "workspace/svid1/uploads/附件/summary.md") in minio.store


async def test_raw_original_lands_beside_its_markdown_view():
    """The code interpreter opens ``raw`` by the path the pointer block prints,
    so the original must sit in the SAME nested directory as the .md."""
    info = _temp_info("f1", "Q1.xlsx")
    info["original_file_path"] = "tmp/f1_original.xlsx"

    fake_minio = FakeMinio()
    fake_redis = AsyncMock()
    fake_minio.store[(fake_minio.tmp_bucket, info["markdown_file_path"])] = b"# T\n"
    fake_minio.store[(fake_minio.tmp_bucket, "tmp/f1_original.xlsx")] = b"PK\x03\x04xlsx"
    fake_redis.amget.return_value = [info]

    with (
        patch.object(Impl, "_get_redis", return_value=fake_redis),
        patch(
            "bisheng.linsight.domain.services.workbench_impl.get_minio_storage",
            new=AsyncMock(return_value=fake_minio),
        ),
    ):
        result = await Impl._process_submitted_files(
            [_submit(file_id="f1", name="Q1.xlsx", rel="年报/2024/Q1.xlsx")], "svid1"
        )

    assert result[0]["raw_workspace_path"] == "/uploads/年报/2024/Q1.xlsx"
    assert ("bisheng", "workspace/svid1/uploads/年报/2024/Q1.xlsx") in fake_minio.store


async def test_crafted_relative_path_stays_inside_uploads():
    submits = [_submit(file_id="f1", name="evil.pdf", rel="../../../../etc/evil.pdf")]
    _, minio = await _ingest(submits, [_temp_info("f1", "evil.pdf")])

    written = [key for (_, key) in minio.store if key.startswith("workspace/")]
    assert written
    for key in written:
        assert key.startswith("workspace/svid1/uploads/")
        assert ".." not in key


# ---------------------------------------------------------------------------
# prepare_file_list rendering
# ---------------------------------------------------------------------------
async def test_pointer_block_groups_by_directory():
    files = [
        {
            "file_id": "f1",
            "original_filename": "Q1.xlsx",
            "relative_path": "年报/2024/Q1.xlsx",
            "workspace_path": "/uploads/年报/2024/Q1.md",
            "line_count": 5,
        },
        {
            "file_id": "f2",
            "original_filename": "note.md",
            "relative_path": "附件/note.md",
            "workspace_path": "/uploads/附件/note.md",
            "line_count": 3,
        },
    ]
    block = (await Impl.prepare_file_list(_session(files)))[0]

    assert "说明（文件夹）" in block
    assert "[目录] /uploads/年报/2024/" in block
    assert "[目录] /uploads/附件/" in block
    assert "path: /uploads/年报/2024/Q1.md" in block


async def test_flat_pointer_block_has_no_folder_scaffolding():
    """A plain submission must render exactly as it always did."""
    files = [
        {
            "file_id": "f1",
            "original_filename": "My Report.pdf",
            "workspace_path": "/uploads/My Report.md",
            "line_count": 42,
            "image_count": 3,
        }
    ]
    block = (await Impl.prepare_file_list(_session(files)))[0]

    assert "说明（文件夹）" not in block
    assert "[目录]" not in block
    assert "path: /uploads/My Report.md" in block


async def test_legacy_index_md_path_is_not_mistaken_for_a_directory():
    """``/uploads/<name>/index.md`` is a legacy fallback shape, not a folder —
    grouping reads ``relative_path``, never the workspace path."""
    files = [
        {
            "file_id": "f1",
            "original_filename": "My Report.pdf",
            "workspace_path": "/uploads/my-report.pdf/index.md",
            "line_count": 42,
        }
    ]
    block = (await Impl.prepare_file_list(_session(files)))[0]
    assert "[目录]" not in block


async def test_large_folder_degrades_to_a_directory_summary():
    files = [
        {
            "file_id": f"f{i}",
            "original_filename": f"doc{i}.pdf",
            "relative_path": f"资料/{i}.pdf",
            "workspace_path": f"/uploads/资料/doc{i}.md",
            "line_count": 1,
        }
        for i in range(Impl._FILE_LIST_MAX_ITEMS + 1)
    ]
    block = (await Impl.prepare_file_list(_session(files)))[0]

    assert "dir: /uploads/资料/" in block
    assert f"files: {Impl._FILE_LIST_MAX_ITEMS + 1}" in block
    assert "pdf×" in block
    # The per-file pointers are exactly what the summary replaces.
    assert "path: /uploads/资料/doc0.md" not in block
    assert "glob" in block
