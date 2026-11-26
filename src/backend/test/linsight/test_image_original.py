"""Uploaded images carry their ORIGINAL into the task-mode workspace.

The text view of a picture is only its OCR output. A user who asks to email the
picture, put it in a Word file or a report, or crop it needs the picture itself
(2026-11-20 field report: the model saw only ``x.md`` and told the user the
upload "was actually a markdown file, not an image").

``asyncio_mode = auto`` — async tests need no decorator.
"""

import tempfile
from types import SimpleNamespace

import pytest

from bisheng.linsight.domain.services import binary_content_guard as guard
from bisheng.linsight.domain.services import workbench_impl as wi
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl as Impl

PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeMinio:
    def __init__(self, objects=None):
        self.bucket = "bisheng"
        self.tmp_bucket = "tmp-dir"
        self.objects = dict(objects or {})
        self.puts = {}
        self.tmp_puts = {}

    async def get_object(self, bucket_name=None, object_name=None):
        return self.objects.get(object_name)

    async def put_object(self, bucket_name=None, object_name=None, file=None, content_type=None):
        self.puts[object_name] = (file, content_type)
        self.objects[object_name] = file

    async def put_object_tmp(self, object_name, file):
        self.tmp_puts[object_name] = file

    async def object_exists(self, bucket_name=None, object_name=None):
        return object_name in self.objects

    async def copy_object(self, source_object, dest_object, source_bucket=None, dest_bucket=None):
        self.objects[dest_object] = self.objects.get(source_object, b"copied")


def image_entry(name, file_id, md=b"text in picture\n"):
    ext = name.rsplit(".", 1)[-1]
    entry = {
        "file_id": file_id,
        "original_filename": name,
        "parsing_status": "completed",
        "valid": True,
        "markdown_file_path": f"linsight/chat1/{file_id}.md",
        "original_file_path": f"linsight/chat1/{file_id}_original.{ext}",
    }
    objects = {entry["markdown_file_path"]: md, entry["original_file_path"]: PNG}
    return entry, objects


def local_file(suffix, data):
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.write(data)
    f.close()
    return f.name


# ---------------------------------------------------------------- workspace write


async def test_parsed_image_lands_with_its_original():
    entry, objects = image_entry("截图.png", "f1")
    minio = FakeMinio(objects)

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, used_names=set())

    assert entry["workspace_path"] == "/uploads/截图.md"
    assert entry["raw_workspace_path"] == "/uploads/截图.png"
    body, content_type = minio.puts["workspace/chat1/uploads/截图.png"]
    assert body == PNG
    assert content_type == "image/png"
    assert entry["text_empty"] is False


async def test_empty_ocr_is_flagged():
    entry, objects = image_entry("photo.jpg", "f1", md=b"\n  \n")
    minio = FakeMinio(objects)

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, used_names=set())

    assert entry["text_empty"] is True


async def test_image_over_the_ceiling_keeps_only_the_text_view(monkeypatch):
    monkeypatch.setattr(Impl, "_RAW_KEEP_MAX_BYTES", 4)
    entry, objects = image_entry("big.png", "f1")
    minio = FakeMinio(objects)

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, used_names=set())

    assert "raw_workspace_path" not in entry
    assert "workspace/chat1/uploads/big.png" not in minio.puts


async def test_same_stem_uploads_keep_text_and_original_paired():
    """x.jpg + x.png used to yield x.md+x.jpg and x-2.md+x.png: the hint that
    derives ``<stem>.md`` from an original then pointed at the other picture."""
    used: set[str] = set()
    first, objects1 = image_entry("x.jpg", "f1")
    second, objects2 = image_entry("x.png", "f2")
    minio = FakeMinio({**objects1, **objects2})

    await Impl._write_attachment_to_workspace(first, "chat1", minio, used_names=used)
    await Impl._write_attachment_to_workspace(second, "chat1", minio, used_names=used)

    for entry in (first, second):
        md_stem = entry["workspace_path"].rsplit(".", 1)[0]
        raw_stem = entry["raw_workspace_path"].rsplit(".", 1)[0]
        assert md_stem == raw_stem
    assert second["workspace_path"] == "/uploads/x-2.md"
    assert second["raw_workspace_path"] == "/uploads/x-2.png"


async def test_folder_upload_image_pair_stays_in_its_directory():
    entry, objects = image_entry("图1.png", "f1")
    entry["relative_path"] = "附件/图1.png"
    minio = FakeMinio(objects)

    await Impl._write_attachment_to_workspace(entry, "chat1", minio, used_names=set())

    assert entry["workspace_path"] == "/uploads/附件/图1.md"
    assert entry["raw_workspace_path"] == "/uploads/附件/图1.png"


# ---------------------------------------------------------------- parse failure


async def test_daily_image_parse_failure_lands_as_original():
    minio = FakeMinio()
    submit = SimpleNamespace(file_id="f3", file_name="动图.gif", relative_path=None)
    path = local_file(".gif", b"GIF89a")

    entry = await Impl._keep_original_in_workspace(
        submit, "动图.gif", "chat1", minio, path, RuntimeError("no loader"), set()
    )

    assert entry["valid"] is True
    assert entry["parsing_status"] == "completed"
    assert entry["ingest_mode"] == Impl._IMAGE_ORIGINAL_MODE
    assert entry["workspace_path"] == "/uploads/动图.gif"
    assert entry["raw_workspace_path"] == "/uploads/动图.gif"
    assert minio.puts["workspace/chat1/uploads/动图.gif"][0] == b"GIF89a"


async def test_task_mode_image_parse_failure_is_not_reported_failed(monkeypatch):
    """A ``failed`` result makes the input box delete the attachment, so the user
    could not even send the picture on."""
    minio = FakeMinio()

    async def _minio():
        return minio

    class BrokenPipeline:
        def __init__(self, **kwargs):
            self.loader = None

        async def arun(self):
            raise RuntimeError("etl not configured")

    monkeypatch.setattr(wi, "get_minio_storage", _minio)
    monkeypatch.setattr("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", BrokenPipeline)
    path = local_file(".webp", b"RIFFxxxxWEBP")

    result = await Impl._parse_file(1, "f4", path, "图.webp")

    assert result["parsing_status"] == "completed"
    assert result["ingest_mode"] == Impl._IMAGE_ORIGINAL_MODE
    assert minio.tmp_puts["f4.webp"] == b"RIFFxxxxWEBP"
    assert "original_file_path" not in result


async def test_task_mode_non_image_parse_failure_still_fails(monkeypatch):
    class BrokenPipeline:
        def __init__(self, **kwargs):
            self.loader = None

        async def arun(self):
            raise RuntimeError("etl 403")

    monkeypatch.setattr("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", BrokenPipeline)
    path = local_file(".pdf", b"%PDF broken")

    result = await Impl._parse_file(1, "f5", path, "扫描件.pdf")

    assert result["parsing_status"] == "failed"


async def test_ingest_of_an_image_original_lands_it_as_itself():
    minio = FakeMinio({"f6.gif": b"GIF89a"})
    temp_info = {
        "file_id": "f6",
        "original_filename": "动图.gif",
        "parsing_status": "completed",
        "ingest_mode": Impl._IMAGE_ORIGINAL_MODE,
        "markdown_file_path": "f6.gif",
        "line_count": 0,
    }
    submit = SimpleNamespace(file_id="f6", file_name="动图.gif", relative_path=None)

    entry = await Impl._ingest_one_file(submit, temp_info, "chat1", minio, used_names=set())

    assert entry["workspace_path"] == "/uploads/动图.gif"
    assert entry["raw_workspace_path"] == "/uploads/动图.gif"
    # the chip previews the picture itself
    assert entry["original_file_path"] == entry["markdown_file_path"]


# ---------------------------------------------------------------- pointer block


def _image_file(**extra):
    return {
        "valid": True,
        "original_filename": "截图.png",
        "workspace_path": "/uploads/截图.md",
        "raw_workspace_path": "/uploads/截图.png",
        "line_count": 3,
        "text_empty": False,
        **extra,
    }


async def test_pointer_block_words_an_image_as_a_picture():
    block = (await Impl.prepare_file_list(SimpleNamespace(files=[_image_file()]), has_code_interpreter=True))[0]

    assert "raw: uploads/截图.png" in block
    assert "图片原件" in block
    assert "不要据此认为用户上传的不是图片" in block
    # the spreadsheet/document wording does not apply to a picture
    assert "表格/文档的精确数据" not in block


@pytest.mark.parametrize(
    ("vision", "expected", "absent"),
    [(True, "read_file(raw)", "不具备视觉能力"), (False, "不具备视觉能力", "read_file(raw)")],
)
async def test_pointer_block_follows_the_vision_flag(vision, expected, absent):
    block = (await Impl.prepare_file_list(SimpleNamespace(files=[_image_file()]), supports_vision=vision))[0]

    assert expected in block
    assert absent not in block


async def test_pointer_block_says_when_ocr_found_nothing():
    block = (await Impl.prepare_file_list(SimpleNamespace(files=[_image_file(text_empty=True)])))[0]

    assert "图中没有识别出文字" in block


async def test_pointer_block_announces_an_image_without_text_view():
    files = [
        {
            "valid": True,
            "original_filename": "动图.gif",
            "workspace_path": "/uploads/动图.gif",
            "raw_workspace_path": "/uploads/动图.gif",
            "ingest_mode": Impl._IMAGE_ORIGINAL_MODE,
        }
    ]
    block = (await Impl.prepare_file_list(SimpleNamespace(files=files)))[0]

    assert "raw: uploads/动图.gif" in block
    assert "没有文本视图" in block


# ---------------------------------------------------------------- guard hints


def test_no_vision_hint_for_an_upload_routes_to_the_path():
    hint = guard._no_vision_hint("/uploads/截图.png", has_code_interpreter=True)

    assert "直接使用该路径" in hint
    assert "`/uploads/截图.md`" in hint
    assert "fitz" not in hint


def test_no_vision_hint_for_a_generated_image_keeps_the_source_route():
    hint = guard._no_vision_hint("/output/page3.png", has_code_interpreter=True)

    assert "fitz" in hint


def test_oversized_image_hint_does_not_talk_about_spreadsheets():
    hint = guard._binary_read_hint("/uploads/大图.jpg", has_code_interpreter=True)

    assert "直接使用该路径" in hint
    assert "pandas" not in hint
