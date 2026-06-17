"""TC-3 / TC-5: attachment ingestion + idempotency for the linsight workbench.

These tests cover only the two methods owned by Track C in
``LinsightWorkbenchImpl``:

  - ``_process_submitted_files`` — write parsed markdown into the workspace
    (``uploads/<name>/index.md``), add pointer-block metadata, and be
    **idempotent** on re-submission of the same ``file_id`` within a session
    (TC-5). When a temp metadata entry has expired and no formal product
    exists, the file is flagged invalid (not silently dropped).
  - ``prepare_file_list`` — emit the zero-body ``<uploaded_files>`` pointer
    block (TC-3 contract format).

External services (Redis, MinIO) are mocked; no live middleware required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from bisheng.linsight.domain.schemas.linsight_schema import SubmitFileSchema
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl


# ---------------------------------------------------------------------------
# Fake MinIO with object_exists / copy_object / put_object surface
# ---------------------------------------------------------------------------
class FakeMinio:
    def __init__(self) -> None:
        self.bucket = "bisheng"
        self.tmp_bucket = "tmp-dir"
        self.store: dict[tuple[str, str], bytes] = {}
        self.copies: list[tuple[str, str]] = []

    async def object_exists(self, bucket_name=None, object_name=None):
        bucket = bucket_name or self.bucket
        return (bucket, object_name) in self.store

    async def copy_object(self, source_bucket=None, source_object=None, dest_bucket=None, dest_object=None):
        src = self.store.get((source_bucket or self.tmp_bucket, source_object), b"parsed-md")
        self.store[(dest_bucket or self.bucket, dest_object)] = src
        self.copies.append((source_object, dest_object))

    async def get_object(self, bucket_name=None, object_name=None):
        return self.store.get((bucket_name or self.bucket, object_name))

    async def put_object(self, *, bucket_name=None, object_name, file, **kwargs):
        data = file if isinstance(file, bytes) else bytes(file)
        self.store[(bucket_name or self.bucket, object_name)] = data


def _file_info(file_id="f1", name="My Report.pdf"):
    return {
        "file_id": file_id,
        "original_filename": name,
        "parsing_status": "completed",
        "markdown_filename": f"{file_id}.md",
        "markdown_file_path": f"{file_id}.md",
        "markdown_file_md5": "deadbeef",
        "embedding_model_id": 1,
        "collection_name": "col_linsight_file_x",
    }


def _submit(file_id="f1", name="My Report.pdf", status="completed"):
    return SubmitFileSchema(file_id=file_id, file_name=name, parsing_status=status)


# ---------------------------------------------------------------------------
# TC-3: ingestion writes into workspace + adds pointer metadata
# ---------------------------------------------------------------------------
async def test_process_writes_workspace_and_pointer_meta():
    fake_minio = FakeMinio()
    fake_redis = AsyncMock()
    info = _file_info()
    info_md = b"# Title\nline2\nline3\n"
    # temp markdown present in tmp bucket
    fake_minio.store[(fake_minio.tmp_bucket, info["markdown_file_path"])] = info_md
    fake_redis.amget.return_value = [info]

    with (
        patch.object(LinsightWorkbenchImpl, "_get_redis", return_value=fake_redis),
        patch(
            "bisheng.linsight.domain.services.workbench_impl.get_minio_storage", new=AsyncMock(return_value=fake_minio)
        ),
    ):
        result = await LinsightWorkbenchImpl._process_submitted_files([_submit()], "chat1")

    assert result and len(result) == 1
    entry = result[0]
    # pointer-block metadata present
    assert entry["workspace_path"].startswith("/uploads/")
    assert entry["workspace_path"].endswith("/index.md")
    assert entry["line_count"] >= 1
    assert "image_count" in entry
    assert entry.get("valid", True) is True
    # workspace object written under workspace/{svid}/uploads/<name>/index.md
    ws_keys = [k for (b, k) in fake_minio.store if k.startswith("workspace/chat1/uploads/")]
    assert any(k.endswith("/index.md") for k in ws_keys)


async def test_prepare_file_list_pointer_block_format():
    from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion

    sv = LinsightSessionVersion(
        session_id="chat1",
        user_id=1,
        question="q",
        files=[
            {
                "file_id": "f1",
                "original_filename": "My Report.pdf",
                "workspace_path": "/uploads/my-report.pdf/index.md",
                "line_count": 42,
                "image_count": 3,
            }
        ],
    )
    file_list = await LinsightWorkbenchImpl.prepare_file_list(sv)
    block = "\n".join(file_list)
    assert "<uploaded_files>" in block
    assert "</uploaded_files>" in block
    assert "path: /uploads/my-report.pdf/index.md" in block
    assert "name: My Report.pdf" in block
    assert "lines: 42" in block
    assert "images: 3" in block


async def test_prepare_file_list_empty():
    from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion

    sv = LinsightSessionVersion(session_id="c", user_id=1, question="q", files=None)
    assert await LinsightWorkbenchImpl.prepare_file_list(sv) == []


# ---------------------------------------------------------------------------
# TC-5: idempotency — same file_id resubmitted reuses formal product
# ---------------------------------------------------------------------------
async def test_idempotent_reuse_skips_copy(monkeypatch):
    fake_minio = FakeMinio()
    fake_redis = AsyncMock()
    info = _file_info()
    fake_minio.store[(fake_minio.tmp_bucket, info["markdown_file_path"])] = b"# T\nbody\n"
    fake_redis.amget.return_value = [dict(info)]

    with (
        patch.object(LinsightWorkbenchImpl, "_get_redis", return_value=fake_redis),
        patch(
            "bisheng.linsight.domain.services.workbench_impl.get_minio_storage", new=AsyncMock(return_value=fake_minio)
        ),
    ):
        first = await LinsightWorkbenchImpl._process_submitted_files([_submit()], "chat1")
        copies_after_first = len(fake_minio.copies)

        # second submission of the same file_id in same session
        fake_redis.amget.return_value = [dict(info)]
        second = await LinsightWorkbenchImpl._process_submitted_files([_submit()], "chat1")

    # the formal product already existed -> no new temp->formal copy on resubmit
    assert len(fake_minio.copies) == copies_after_first
    assert second[0]["workspace_path"] == first[0]["workspace_path"]
    assert second[0].get("valid", True) is True


# ---------------------------------------------------------------------------
# Unified-resource: DAILY-bucket file (file_url set) is parsed on-the-fly and
# written into the workspace, so the task agent's ls/read_file sees it.
# ---------------------------------------------------------------------------
def _daily_submit(file_id="d1", name="Report.pdf"):
    return SubmitFileSchema(
        file_id=file_id,
        file_name=name,
        parsing_status="completed",
        file_url="/tmp-dir/abc.pdf?X-Amz-Algorithm=AWS4",
    )


async def test_daily_file_ingested_into_workspace(monkeypatch):
    """A DAILY-bucket file (filepath -> file_url) is parsed via TempFilePipeline
    and lands as ``workspace/{svid}/uploads/<name>/index.md`` so the agent's
    ``ls`` can see it (covers the unified-resource ingestion path)."""

    class _Doc:
        def __init__(self, content):
            self.page_content = content

    class _Result:
        documents = [_Doc("# Heading\nbody line\n")]

    class _FakePipeline:
        def __init__(self, *args, **kwargs):
            pass

        async def arun(self):
            return _Result()

    fake_minio = FakeMinio()

    with (
        patch(
            "bisheng.linsight.domain.services.workbench_impl.get_minio_storage",
            new=AsyncMock(return_value=fake_minio),
        ),
        patch.object(LinsightWorkbenchImpl, "_get_redis", return_value=AsyncMock()),
        patch(
            "bisheng.core.cache.utils.async_file_download",
            new=AsyncMock(return_value=("/tmp/abc.pdf", "Report.pdf")),
        ),
        patch("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", _FakePipeline),
    ):
        result = await LinsightWorkbenchImpl._process_submitted_files([_daily_submit()], "svid1", user_id=7)

    assert result and len(result) == 1
    entry = result[0]
    assert entry.get("valid") is True
    assert entry["parsing_status"] == "completed"
    assert entry["workspace_path"].startswith("/uploads/")
    assert entry["workspace_path"].endswith("/index.md")
    # markdown written into the session workspace where WorkspaceBackend.ls reads
    ws_keys = [k for (b, k) in fake_minio.store if k.startswith("workspace/svid1/uploads/")]
    assert any(k.endswith("/index.md") for k in ws_keys)


async def test_daily_file_ingest_failure_degrades_gracefully(monkeypatch):
    """A DAILY-bucket file that fails to download/parse must NOT abort the task:
    it is marked ``valid=False`` / ``parsing_status='failed'`` (so the caller can
    tell the user it failed) and nothing broken is written into the workspace
    (the agent's ``ls`` won't list a half-ingested file)."""
    fake_minio = FakeMinio()

    with (
        patch(
            "bisheng.linsight.domain.services.workbench_impl.get_minio_storage",
            new=AsyncMock(return_value=fake_minio),
        ),
        patch.object(LinsightWorkbenchImpl, "_get_redis", return_value=AsyncMock()),
        patch(
            "bisheng.core.cache.utils.async_file_download",
            new=AsyncMock(side_effect=ValueError("minio download boom")),
        ),
    ):
        result = await LinsightWorkbenchImpl._process_submitted_files([_daily_submit()], "svid1", user_id=7)

    assert result and len(result) == 1
    entry = result[0]
    assert entry["valid"] is False
    assert entry["parsing_status"] == "failed"
    assert entry["file_id"] == "d1"
    # real cause carried for diagnosis / user-facing message
    assert "boom" in entry["error_message"]
    # nothing half-written into the workspace
    assert not [k for (b, k) in fake_minio.store if k.startswith("workspace/svid1/uploads/")]


def test_annotate_display_files_stamps_parse_result():
    """Persisted attachments are stamped with each file's parse result (by
    file_id) so the chip can show a 'parse failed' state on reload."""
    display = [
        {"file_id": "ok", "filename": "good.txt", "type": "text/plain"},
        {"file_id": "bad", "filename": "broken.pdf", "type": "application/pdf"},
        {"file_id": "unknown", "filename": "x.txt"},  # no processed entry -> untouched
    ]
    processed = [
        {"file_id": "ok", "valid": True, "parsing_status": "completed"},
        {"file_id": "bad", "valid": False, "parsing_status": "failed", "error_message": "boom"},
    ]
    out = LinsightWorkbenchImpl._annotate_display_files(display, processed)
    by_id = {f["file_id"]: f for f in out}
    assert by_id["ok"]["valid"] is True
    assert by_id["ok"]["parsing_status"] == "completed"
    assert by_id["bad"]["valid"] is False
    assert by_id["bad"]["parsing_status"] == "failed"
    assert by_id["bad"]["error_message"] == "boom"
    # original display fields preserved; unmatched file left as-is
    assert by_id["ok"]["filename"] == "good.txt"
    assert "valid" not in by_id["unknown"]


def test_annotate_display_files_handles_empty():
    assert LinsightWorkbenchImpl._annotate_display_files(None, []) is None
    assert LinsightWorkbenchImpl._annotate_display_files([], None) == []


async def test_expired_temp_no_formal_marks_invalid():
    """Temp metadata expired (Redis returns None) and no formal product -> invalid flag."""
    fake_minio = FakeMinio()
    fake_redis = AsyncMock()
    fake_redis.amget.return_value = [None]  # expired temp metadata

    with (
        patch.object(LinsightWorkbenchImpl, "_get_redis", return_value=fake_redis),
        patch(
            "bisheng.linsight.domain.services.workbench_impl.get_minio_storage", new=AsyncMock(return_value=fake_minio)
        ),
    ):
        result = await LinsightWorkbenchImpl._process_submitted_files([_submit()], "chat1")

    assert result and len(result) == 1
    entry = result[0]
    assert entry["valid"] is False
    assert entry["file_id"] == "f1"
    # not silently dropped: carries a status the frontend can branch on
    assert entry.get("parsing_status") in ("expired", "invalid")
