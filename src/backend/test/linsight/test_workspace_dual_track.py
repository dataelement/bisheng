"""Unit tests for the dual-track workspace write (markdown view + original).

The originals exist so ``bisheng_code_interpreter`` can compute on real data:
a spreadsheet flattened to markdown loses cell types, sheets and formulas, which
is precisely what a user uploading a spreadsheet wants to work with.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from types import SimpleNamespace

from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl as Impl


class FakeMinio:
    """Minimal MinIO stand-in recording every put, with optional read failures."""

    def __init__(self, objects=None, fail_on_get=()):
        self.bucket = "bisheng"
        self.tmp_bucket = "tmp-dir"
        self.objects = dict(objects or {})
        self.puts = {}
        self.fail_on_get = set(fail_on_get)

    async def get_object(self, bucket_name=None, object_name=None):
        if object_name in self.fail_on_get:
            raise RuntimeError(f"boom: {object_name}")
        return self.objects.get(object_name)

    async def put_object(self, bucket_name=None, object_name=None, file=None, content_type=None):
        self.puts[object_name] = (file, content_type)


def entry_for(name, *, file_id="f1", with_original=True, ext=None):
    ext = ext or name.rsplit(".", 1)[-1]
    e = {
        "file_id": file_id,
        "original_filename": name,
        "parsing_status": "completed",
        "valid": True,
        "markdown_file_path": f"linsight/chat1/{file_id}.md",
    }
    if with_original:
        e["original_file_path"] = f"linsight/chat1/{file_id}_original.{ext}"
    return e


def make_minio(entry, raw_bytes=b"\x50\x4b\x03\x04binary"):
    objects = {entry["markdown_file_path"]: b"# Title\nrow\n"}
    if entry.get("original_file_path"):
        objects[entry["original_file_path"]] = raw_bytes
    return FakeMinio(objects)


# --------------------------------------------------------------------------
# _should_keep_raw
# --------------------------------------------------------------------------


def test_keep_raw_extension_gate():
    assert Impl._should_keep_raw("data.xlsx")
    assert Impl._should_keep_raw("报告.PDF")  # case-insensitive
    assert Impl._should_keep_raw("spec.docx")
    assert not Impl._should_keep_raw("notes.md")
    assert not Impl._should_keep_raw("photo.png")  # images stay single-track
    assert not Impl._should_keep_raw("clip.mp4")
    assert not Impl._should_keep_raw("")


def test_keep_raw_size_ceiling():
    assert not Impl._should_keep_raw("huge.xlsx", size=Impl._RAW_KEEP_MAX_BYTES + 1)
    assert Impl._should_keep_raw("fine.xlsx", size=Impl._RAW_KEEP_MAX_BYTES)
    # Un-measurable file: carry it rather than fail closed.
    assert Impl._should_keep_raw("unknown.xlsx", local_path="/no/such/path")


# --------------------------------------------------------------------------
# dual-track write
# --------------------------------------------------------------------------


async def test_original_lands_next_to_markdown():
    entry = entry_for("销售数据.xlsx")
    minio = make_minio(entry)
    used = set()

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, used_names=used)

    assert entry["workspace_path"] == "/uploads/销售数据.md"
    assert entry["raw_workspace_path"] == "/uploads/销售数据.xlsx"
    assert entry["raw_filename"] == "销售数据.xlsx"
    assert "workspace/chat1/uploads/销售数据.md" in minio.puts
    raw_body, raw_ct = minio.puts["workspace/chat1/uploads/销售数据.xlsx"]
    assert raw_body == b"\x50\x4b\x03\x04binary"
    assert "spreadsheet" in raw_ct  # real mime, not octet-stream
    # both names reserved, so a second same-named upload cannot clobber either
    assert used == {"销售数据.md", "销售数据.xlsx"}


async def test_non_whitelisted_type_stays_single_track():
    entry = entry_for("photo.png")
    minio = make_minio(entry)

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, used_names=set())

    assert entry["workspace_path"] == "/uploads/photo.md"
    assert "raw_workspace_path" not in entry
    assert "workspace/chat1/uploads/photo.png" not in minio.puts


async def test_no_original_persisted_stays_single_track():
    entry = entry_for("report.pdf", with_original=False)
    minio = make_minio(entry)

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, used_names=set())

    assert entry["workspace_path"] == "/uploads/report.md"
    assert "raw_workspace_path" not in entry


async def test_raw_failure_never_sinks_the_markdown_view():
    """Best-effort contract: losing the precise-data track must not lose the task."""
    entry = entry_for("data.xlsx")
    minio = make_minio(entry)
    minio.fail_on_get.add(entry["original_file_path"])

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, used_names=set())

    assert entry["workspace_path"] == "/uploads/data.md"
    assert "raw_workspace_path" not in entry
    assert "workspace/chat1/uploads/data.md" in minio.puts


async def test_unparsed_original_path_unchanged():
    """as_markdown=False (parse failed) keeps the legacy single-file behaviour."""
    entry = {
        "file_id": "f9",
        "original_filename": "scan.pdf",
        "valid": False,
        "markdown_file_path": "linsight/chat1/f9.pdf",
    }
    minio = FakeMinio({"linsight/chat1/f9.pdf": b"%PDF-1.4"})

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, as_markdown=False, used_names=set())

    assert entry["workspace_path"] == "/uploads/scan.pdf"
    assert "raw_workspace_path" not in entry


# --------------------------------------------------------------------------
# pointer block
# --------------------------------------------------------------------------


def session_with(files):
    return SimpleNamespace(files=files)


async def test_pointer_block_exposes_raw_and_guidance():
    files = [
        {
            "valid": True,
            "original_filename": "销售数据.xlsx",
            "workspace_path": "/uploads/销售数据.md",
            "raw_workspace_path": "/uploads/销售数据.xlsx",
            "line_count": 40,
            "image_count": 0,
        }
    ]
    block = (await Impl.prepare_file_list(session_with(files), has_code_interpreter=True))[0]

    assert "path: /uploads/销售数据.md" in block
    assert "raw: /uploads/销售数据.xlsx" in block
    assert "bisheng_code_interpreter" in block
    assert "pandas" in block


async def test_pointer_block_stays_lean_without_raw():
    files = [
        {
            "valid": True,
            "original_filename": "notes.txt",
            "workspace_path": "/uploads/notes.md",
            "line_count": 3,
            "image_count": 0,
        }
    ]
    block = (await Impl.prepare_file_list(session_with(files), has_code_interpreter=True))[0]

    # No dual-track guidance paragraph when there is nothing dual about it.
    assert "bisheng_code_interpreter" not in block
    assert "raw:" not in block


async def test_unparsed_file_announced_instead_of_hidden():
    """Previously skipped outright — the model then met it via `ls` and read_file'd
    it, which is exactly how a 400 took down the whole task."""
    files = [
        {
            "valid": False,
            "original_filename": "TDS-33kv SA.pdf",
            "workspace_path": "/uploads/TDS-33kv SA.pdf",
        }
    ]
    block = (await Impl.prepare_file_list(session_with(files), has_code_interpreter=True))[0]

    assert "/uploads/TDS-33kv SA.pdf" in block
    assert "不可 read_file" in block
    assert "bisheng_code_interpreter" in block


async def test_invalid_file_without_workspace_path_still_skipped():
    """Expired metadata has nothing in the workspace to point at."""
    files = [{"valid": False, "original_filename": "gone.pdf", "parsing_status": "expired"}]
    assert await Impl.prepare_file_list(session_with(files), has_code_interpreter=True) == []


async def test_pointer_block_omits_unbound_code_interpreter():
    """prompt ⟺ tool lockstep: without the tool, do not send the model chasing it."""
    files = [
        {
            "valid": True,
            "original_filename": "销售数据.xlsx",
            "workspace_path": "/uploads/销售数据.md",
            "raw_workspace_path": "/uploads/销售数据.xlsx",
            "line_count": 40,
            "image_count": 0,
        }
    ]
    block = (await Impl.prepare_file_list(session_with(files), has_code_interpreter=False))[0]

    assert "raw: /uploads/销售数据.xlsx" in block  # still disclosed
    assert "bisheng_code_interpreter" not in block
    assert "没有可用的代码执行工具" in block
