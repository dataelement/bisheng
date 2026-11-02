"""Task-mode Excel ingest: the original workbook only, no ETL, no text view.

An uploaded .xlsx / .xls no longer goes through ``ExcelLoader`` (the RAG
chunker). It lands in the workspace as itself and the model reads it through
the code interpreter; ``read_file`` refuses binary content. Without a code
interpreter the model is told it cannot open the workbook and must ask the user
to add the tool.

``asyncio_mode = auto`` — async tests need no decorator.
"""

import os
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook

from bisheng.linsight.domain.schemas.linsight_schema import SubmitFileSchema
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl as Impl

MODE = "spreadsheet_original"


def _xlsx(tmp_path) -> str:
    wb = Workbook()
    wb.active.append(["日期", "金额"])
    wb.active.append(["2025-01-01", 1.5])
    path = tmp_path / "book.xlsx"
    wb.save(path)
    return str(path)


class _ExplodingPipeline:
    def __init__(self, **_kwargs):
        raise AssertionError("an Excel upload must not reach the knowledge ETL")


class _FakeMinio:
    bucket = "bisheng"
    tmp_bucket = "tmp-dir"

    def __init__(self):
        self.store: dict[tuple[str, str], bytes] = {}
        self.tmp: dict[str, bytes] = {}

    async def put_object(self, bucket_name=None, object_name=None, file=None, content_type=None):
        self.store[(bucket_name or self.bucket, object_name)] = file

    async def get_object(self, bucket_name=None, object_name=None):
        return self.store.get((bucket_name or self.bucket, object_name))

    async def object_exists(self, bucket_name=None, object_name=None):
        return (bucket_name or self.bucket, object_name) in self.store

    async def copy_object(self, source_bucket=None, source_object=None, dest_bucket=None, dest_object=None):
        data = (
            self.tmp[source_object] if source_bucket == self.tmp_bucket else self.store[(source_bucket, source_object)]
        )
        self.store[(dest_bucket, dest_object)] = data

    async def put_object_tmp(self, key, data):
        self.tmp[key] = data


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------


def test_original_route_falls_back_to_parse_past_the_carry_ceiling(tmp_path, monkeypatch):
    path = _xlsx(tmp_path)

    assert Impl._spreadsheet_original_applies("a.xlsx", path)
    assert Impl._spreadsheet_original_applies("a.XLS", path)
    assert not Impl._spreadsheet_original_applies("a.csv", path)
    assert not Impl._spreadsheet_original_applies("a.et", path)

    # Over the ceiling the original never reaches the workspace, so the parsed
    # markdown is the only data the model could get.
    monkeypatch.setattr(Impl, "_RAW_KEEP_MAX_BYTES", os.path.getsize(path) - 1)
    assert not Impl._spreadsheet_original_applies("a.xlsx", path)


# --------------------------------------------------------------------------
# ingest paths
# --------------------------------------------------------------------------


async def test_daily_upload_lands_only_the_original(tmp_path, monkeypatch):
    path = _xlsx(tmp_path)
    minio = _FakeMinio()
    monkeypatch.setattr("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", _ExplodingPipeline)

    async def _download(_url):
        return path, "book.xlsx"

    monkeypatch.setattr("bisheng.core.cache.utils.async_file_download", _download)
    submit = SimpleNamespace(file_id="f1", file_name="销售.xlsx", file_url="http://x", relative_path=None)

    entry = await Impl._ingest_daily_file(submit, "chat1", minio, user_id=1, used_names=set())

    assert entry["parsing_status"] == "completed"
    assert entry["valid"] is True
    assert entry["ingest_mode"] == MODE
    assert entry["line_count"] == 0
    # No text view: the reading path and the raw path are the same workbook.
    assert entry["workspace_path"] == "/uploads/销售.xlsx"
    assert entry["raw_workspace_path"] == "/uploads/销售.xlsx"
    assert entry["markdown_file_path"] == entry["original_file_path"] == "linsight/chat1/f1.xlsx"
    original = Path(path).read_bytes()
    assert minio.store[("bisheng", "workspace/chat1/uploads/销售.xlsx")] == original
    assert not any(key.endswith(".md") for _, key in minio.store)


async def test_daily_upload_over_the_ceiling_keeps_the_old_parse_path(tmp_path, monkeypatch):
    path = _xlsx(tmp_path)
    monkeypatch.setattr(Impl, "_RAW_KEEP_MAX_BYTES", 1)

    class _Reached(Exception):
        pass

    class _RecordingPipeline:
        def __init__(self, **_kwargs):
            raise _Reached

    monkeypatch.setattr("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", _RecordingPipeline)

    async def _download(_url):
        return path, "book.xlsx"

    monkeypatch.setattr("bisheng.core.cache.utils.async_file_download", _download)
    submit = SimpleNamespace(file_id="f2", file_name="big.xlsx", file_url="http://x", relative_path=None)

    entry = await Impl._ingest_daily_file(submit, "chat1", _FakeMinio(), user_id=1, used_names=set())

    # The ETL was attempted (and here made to fail): the old parse-failure shape,
    # not the original route.
    assert entry.get("ingest_mode") is None
    assert entry["parsing_status"] == "failed"
    assert entry["error_message"].startswith("file parse failed")


async def test_follow_up_upload_then_ingest_lands_only_the_original(tmp_path, monkeypatch):
    path = _xlsx(tmp_path)
    minio = _FakeMinio()
    monkeypatch.setattr("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", _ExplodingPipeline)

    async def _get_minio():
        return minio

    async def _md5(_data):
        return "md5"

    monkeypatch.setattr("bisheng.linsight.domain.services.workbench_impl.get_minio_storage", _get_minio)
    monkeypatch.setattr("bisheng.linsight.domain.services.workbench_impl.async_calculate_md5", _md5)

    temp_info = await Impl._parse_file(1, "fid", path, "销售.xlsx")

    assert temp_info["parsing_status"] == "completed"
    assert temp_info["ingest_mode"] == MODE
    assert temp_info["markdown_file_path"] == "fid.xlsx"
    assert temp_info["line_count"] == 0
    assert "original_file_path" not in temp_info
    assert minio.tmp["fid.xlsx"] == Path(path).read_bytes()

    submit = SubmitFileSchema(file_id="fid", file_name="销售.xlsx", parsing_status="completed")
    entry = await Impl._ingest_one_file(submit, temp_info, "chat1", minio, used_names=set())

    assert entry["markdown_file_path"] == entry["original_file_path"] == "linsight/chat1/fid.xlsx"
    assert entry["workspace_path"] == entry["raw_workspace_path"] == "/uploads/销售.xlsx"
    assert minio.store[("bisheng", "workspace/chat1/uploads/销售.xlsx")] == Path(path).read_bytes()


# --------------------------------------------------------------------------
# pointer block
# --------------------------------------------------------------------------


def _sheet_entry() -> dict:
    return {
        "valid": True,
        "original_filename": "销售.xlsx",
        "ingest_mode": MODE,
        "workspace_path": "/uploads/销售.xlsx",
        "raw_workspace_path": "/uploads/销售.xlsx",
        "line_count": 0,
        "image_count": 0,
    }


async def test_pointer_block_routes_excel_to_the_code_interpreter():
    block = (await Impl.prepare_file_list(SimpleNamespace(files=[_sheet_entry()]), has_code_interpreter=True))[0]

    assert "raw: uploads/销售.xlsx" in block
    assert "不可 read_file" in block
    assert "lines:" not in block
    assert "bisheng_code_interpreter" in block
    assert "sheet_name" in block and "header" in block
    # Text-passthrough wording ("read_file works") must not leak onto a binary.
    assert "read_file 与代码工具都可直接使用" not in block


async def test_pointer_block_without_code_interpreter_asks_user_to_add_the_tool():
    block = (await Impl.prepare_file_list(SimpleNamespace(files=[_sheet_entry()]), has_code_interpreter=False))[0]

    assert "无法读取 Excel 原件" in block
    assert "需要添加代码执行器工具" in block
    # Prompt <-> tool lockstep: never point at a tool that is not bound.
    assert "bisheng_code_interpreter" not in block
