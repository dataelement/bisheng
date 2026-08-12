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
    # RELATIVE: the code interpreter resolves against its working directory, where
    # the original sits at uploads/<name>. A leading slash would point at the
    # filesystem root and fail — the model can only reach it via the relative form.
    assert "raw: uploads/销售数据.xlsx" in block
    assert "raw: /uploads/销售数据.xlsx" not in block
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

    assert "raw: uploads/销售数据.xlsx" in block  # still disclosed
    assert "bisheng_code_interpreter" not in block
    assert "没有可用的代码执行工具" in block


# --------------------------------------------------------------------------
# unsupported originals (P5): nothing in the workspace can open them
# --------------------------------------------------------------------------


def test_original_is_usable_gate():
    assert Impl._original_is_usable("data.xlsx")  # code interpreter
    assert Impl._original_is_usable("notes.txt")  # read_file
    assert Impl._original_is_usable("表格.CSV")  # case-insensitive
    assert Impl._original_is_usable("photo.png")  # image block
    assert not Impl._original_is_usable("song.mp3")
    assert not Impl._original_is_usable("clip.mp4")
    assert not Impl._original_is_usable("bundle.zip")
    assert not Impl._original_is_usable("")


async def test_unsupported_original_is_not_written_to_workspace():
    """An mp3 no parser, no read_file and no code interpreter can open is pure
    cost: storage, a confusing ls entry, and a wasted tool call."""
    minio = FakeMinio({})
    submit = SimpleNamespace(file_id="f7", file_name="访谈录音.mp3", relative_path=None)
    local = __import__("tempfile").NamedTemporaryFile(suffix=".mp3", delete=False)
    local.write(b"ID3\x03\x00\x00\x00")
    local.close()

    entry = await Impl._keep_original_in_workspace(
        submit, "访谈录音.mp3", "chat1", minio, local.name, RuntimeError("no loader"), set()
    )

    assert entry["parsing_status"] == "unsupported"
    assert entry["valid"] is False
    assert "workspace_path" not in entry
    assert not any(k.startswith("workspace/") for k in minio.puts)
    # still recoverable by the user from the formal bucket
    assert "linsight/chat1/f7.mp3" in minio.puts


async def test_usable_unparsed_original_still_lands():
    minio = FakeMinio({})
    submit = SimpleNamespace(file_id="f8", file_name="扫描件.pdf", relative_path=None)
    local = __import__("tempfile").NamedTemporaryFile(suffix=".pdf", delete=False)
    local.write(b"%PDF-1.4 broken")
    local.close()

    entry = await Impl._keep_original_in_workspace(
        submit, "扫描件.pdf", "chat1", minio, local.name, RuntimeError("etl 403"), set()
    )

    assert entry["parsing_status"] == "failed"
    assert entry["workspace_path"] == "/uploads/扫描件.pdf"


async def test_pointer_block_announces_unsupported_type():
    """Silence here means the user sees the attachment accepted while the model
    never hears of it."""
    files = [{"valid": False, "original_filename": "访谈录音.mp3", "parsing_status": "unsupported"}]
    block = (await Impl.prepare_file_list(session_with(files), has_code_interpreter=True))[0]

    assert "访谈录音.mp3" in block
    assert "无法解析" in block


def test_content_type_is_platform_independent():
    """`mimetypes` reads the SYSTEM database: a stock Linux image (every deploy
    target, and CI) returns None for OOXML, so relying on it stored every original
    as octet-stream off the dev machine."""
    assert "spreadsheetml" in Impl._content_type_for("销售数据.xlsx")
    assert "wordprocessingml" in Impl._content_type_for("报告.DOCX")  # case-insensitive
    assert Impl._content_type_for("合同.pdf") == "application/pdf"
    assert Impl._content_type_for("data.csv") == "text/csv"
    assert Impl._content_type_for("unknown.bin") == "application/octet-stream"


# --------------------------------------------------------------------------
# passthrough ingest: data/code files whose original IS the workspace file
# --------------------------------------------------------------------------


def test_ingest_route_truth_table():
    """The route decides whether a file is parsed, passed through, or refused.

    Pinned as a table because the sets genuinely overlap and the tie-break lives
    in ``_PARSE_WINS_EXTS``; an implicit ordering here would invert silently the
    next time someone adds a key to ``FileExtensionMap``.
    """
    # No loader exists, and none is wanted — the file is already final.
    assert Impl._ingest_route("analyze.py") == "passthrough"
    assert Impl._ingest_route("data.json") == "passthrough"
    assert Impl._ingest_route("rows.jsonl") == "passthrough"
    assert Impl._ingest_route("conf.yaml") == "passthrough"
    assert Impl._ingest_route("query.sql") == "passthrough"
    assert Impl._ingest_route("table.tsv") == "passthrough"
    assert Impl._ingest_route("SETUP.SH") == "passthrough"  # case-insensitive

    # Parseable AND passthrough-able -> the parse carve-out wins, because the
    # markdown view is a cheap extra on top of the original, not a replacement.
    assert Impl._ingest_route("data.csv") == "parse"
    assert Impl._ingest_route("page.html") == "parse"
    assert Impl._ingest_route("notes.txt") == "parse"
    assert Impl._ingest_route("readme.md") == "parse"
    # ...but only where a loader actually exists: the parser registers `md`, not
    # `markdown`, so the long spelling passes through instead of failing a parse.
    assert Impl._ingest_route("readme.markdown") == "passthrough"

    # Parser-only types are untouched by any of this.
    assert Impl._ingest_route("book.xlsx") == "parse"
    assert Impl._ingest_route("scan.pdf") == "parse"
    assert Impl._ingest_route("photo.png") == "parse"

    # REGRESSION GUARD: media must never become passthrough. Their "parse" is the
    # ASR transcription that makes them usable at all — passing an mp3 through
    # would hand the model an unreadable binary instead of the transcript.
    assert Impl._ingest_route("访谈录音.mp3") == "parse"
    assert Impl._ingest_route("clip.mp4") == "parse"

    # No loader, no consumer: refused up front rather than after a failed ETL.
    assert Impl._ingest_route("setup.exe") == "unsupported"
    assert Impl._ingest_route("bundle.zip") == "unsupported"
    assert Impl._ingest_route("") == "unsupported"


def test_parse_wins_exts_are_actually_parseable():
    """Every carve-out must have a loader, or it silently routes to a failure."""
    from bisheng.knowledge.rag.base_file_pipeline import FileExtensionMap

    assert Impl._PARSE_WINS_EXTS <= set(FileExtensionMap)
    # And the carve-out only makes sense for types we would otherwise pass through.
    assert Impl._PARSE_WINS_EXTS <= Impl._PASSTHROUGH_TEXT_EXTS


async def test_passthrough_entry_is_reported_as_success():
    """The historical failure marking made the chip cry wolf about a usable file.

    ``parsing_status`` also may not carry a new value: the frontend reads anything
    other than completed/failed as "still parsing" and disables send, and
    ``_process_submitted_files`` rejects the submission outright.
    """
    minio = FakeMinio({})
    submit = SimpleNamespace(file_id="f9", file_name="analyze.py", relative_path=None)

    entry = await Impl._finalize_passthrough(submit, "analyze.py", "chat1", minio, b"import os\nprint(1)\n", set())

    assert entry["parsing_status"] == "completed"
    assert entry["valid"] is True
    assert entry["ingest_mode"] == "passthrough"
    assert entry["line_count"] == 3
    # The reading track and the raw track are the same file — that IS passthrough.
    assert entry["workspace_path"] == "/uploads/analyze.py"
    assert entry["raw_workspace_path"] == entry["workspace_path"]
    assert entry["raw_filename"] == entry["markdown_filename"] == "analyze.py"
    # Formal key keeps the real extension: the drawer builds its preview URL from
    # it, and a .py served as .md would reach the markdown renderer.
    assert entry["markdown_file_path"] == "linsight/chat1/f9.py"
    assert entry["original_file_path"] == entry["markdown_file_path"]
    # Exactly one workspace object — no phantom second copy.
    assert [k for k in minio.puts if k.startswith("workspace/")] == ["workspace/chat1/uploads/analyze.py"]


async def test_text_parse_failure_degrades_to_passthrough():
    """A large csv hard-fails ExcelLoader past 10k chars, yet the csv sitting in
    the workspace is exactly what the user wanted analysed."""
    minio = FakeMinio({})
    submit = SimpleNamespace(file_id="f10", file_name="big.csv", relative_path=None)
    local = __import__("tempfile").NamedTemporaryFile(suffix=".csv", delete=False)
    local.write(b"a,b\n1,2\n")
    local.close()

    entry = await Impl._keep_original_in_workspace(
        submit, "big.csv", "chat1", minio, local.name, RuntimeError("chunk too large"), set()
    )

    assert entry["parsing_status"] == "completed"
    assert entry["valid"] is True
    assert entry["ingest_mode"] == "passthrough"
    assert entry["workspace_path"] == "/uploads/big.csv"
    # The cause is kept for diagnosis even though the outcome is a success.
    assert "chunk too large" in entry["error_message"]


async def test_binary_parse_failure_still_reports_failure():
    """A broken pdf really is broken: no text view, only the code interpreter."""
    minio = FakeMinio({})
    submit = SimpleNamespace(file_id="f11", file_name="扫描件.pdf", relative_path=None)
    local = __import__("tempfile").NamedTemporaryFile(suffix=".pdf", delete=False)
    local.write(b"%PDF-1.4 broken")
    local.close()

    entry = await Impl._keep_original_in_workspace(
        submit, "扫描件.pdf", "chat1", minio, local.name, RuntimeError("etl 403"), set()
    )

    assert entry["parsing_status"] == "failed"
    assert entry["valid"] is False
    assert entry.get("ingest_mode") is None


async def test_pointer_block_tells_the_truth_about_passthrough():
    files = [
        {
            "valid": True,
            "original_filename": "analyze.py",
            "workspace_path": "/uploads/analyze.py",
            "raw_workspace_path": "/uploads/analyze.py",
            "ingest_mode": "passthrough",
            "line_count": 12,
            "image_count": 0,
        }
    ]
    block = (await Impl.prepare_file_list(session_with(files), has_code_interpreter=True))[0]

    assert "path 与 raw 指向同一个文本原件" in block
    # The dual-track wording ends in "do not read_file the original", which would
    # be exactly wrong here.
    assert "不要 read_file 二进制原件" not in block
    assert "解析失败" not in block


async def test_pointer_block_keeps_one_explanation_paragraph():
    """All three kinds can co-occur; a paragraph each would bloat and contradict."""
    files = [
        {
            "valid": True,
            "original_filename": "book.xlsx",
            "workspace_path": "/uploads/book.md",
            "raw_workspace_path": "/uploads/book.xlsx",
            "line_count": 5,
            "image_count": 0,
        },
        {
            "valid": True,
            "original_filename": "analyze.py",
            "workspace_path": "/uploads/analyze.py",
            "raw_workspace_path": "/uploads/analyze.py",
            "ingest_mode": "passthrough",
            "line_count": 12,
            "image_count": 0,
        },
        {
            "valid": False,
            "original_filename": "扫描件.pdf",
            "workspace_path": "/uploads/扫描件.pdf",
            "parsing_status": "failed",
        },
    ]
    block = (await Impl.prepare_file_list(session_with(files), has_code_interpreter=True))[0]

    assert block.count("说明：") == 1
    assert "raw 指向同名原件" in block
    assert "path 与 raw 指向同一个文本原件" in block
    assert "只有二进制原件" in block


async def test_passthrough_inside_a_folder_upload_keeps_the_tree():
    """Passthrough and folder upload compose: the raw mirror must carry the
    sub-path, or the prefetch would land the file somewhere the pointer block
    never mentioned."""
    minio = FakeMinio({})
    submit = SimpleNamespace(file_id="f12", file_name="Q1.py", relative_path="年报/2024/Q1.py")

    entry = await Impl._finalize_passthrough(submit, "Q1.py", "chat1", minio, b"print(1)\n", set())

    assert entry["workspace_path"] == "/uploads/年报/2024/Q1.py"
    assert entry["raw_workspace_path"] == entry["workspace_path"]
    assert entry["raw_filename"] == "年报/2024/Q1.py"
    assert "workspace/chat1/uploads/年报/2024/Q1.py" in minio.puts
