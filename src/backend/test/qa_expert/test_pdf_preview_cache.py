"""问答预览与下载复用基础 PDF 的行为回归。"""

import asyncio
import shutil
import subprocess
from importlib import import_module
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import fitz
import pytest
from minio.error import S3Error

from bisheng.knowledge.pdf.converter import ConversionResult, PdfConversionError, PdfConverterRegistry
from bisheng.qa_expert.domain import watermarked_download as downloads
from bisheng.qa_expert.domain.pdf_preview_service import QaPdfPreviewGenerationError, QaPdfPreviewService


def pdf_bytes(text="base preview"):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), text)
        return document.tobytes()


class Storage:
    bucket = "bisheng"
    tmp_bucket = "tmp-dir"

    def __init__(self):
        self.objects = {(self.bucket, "qa-expert/1/question/attachment/a/source.doc"): b"source-v1"}
        self.puts = []

    async def get_object(self, *, bucket_name, object_name):
        return self.get_object_sync(bucket_name=bucket_name, object_name=object_name)

    def get_object_sync(self, *, object_name, bucket_name=None):
        key = (bucket_name or self.bucket, object_name)
        if key not in self.objects:
            raise FileNotFoundError(object_name)
        return self.objects[key]

    def put_object_sync(self, *, object_name, file, content_type, bucket_name=None):
        assert content_type == "application/pdf"
        self.objects[(bucket_name or self.bucket, object_name)] = Path(file).read_bytes()
        self.puts.append(object_name)


class Lease:
    def __init__(self, mutex):
        self.mutex = mutex
        self.acquired = False

    def __enter__(self):
        assert self.mutex.acquire(timeout=5)
        self.acquired = True
        return self

    def __exit__(self, *_):
        self.acquired = False
        self.mutex.release()

    def owned(self):
        return self.acquired


class Redis:
    def __init__(self):
        self.locks = {}
        self.guard = Lock()

    def lock(self, key, **_kwargs):
        with self.guard:
            mutex = self.locks.setdefault(key, Lock())
        return Lease(mutex)


@pytest.fixture
def environment(monkeypatch):
    storage = Storage()
    redis = Redis()
    conversions = []
    watermarks = []

    def convert(_self, source, output_dir, _context):
        conversions.append(source.read_bytes())
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "output.pdf"
        path.write_bytes(pdf_bytes())
        return ConversionResult(path, "fake-office")

    async def watermark(data, **kwargs):
        watermarks.append((data, kwargs["user_name"]))
        return data + kwargs["user_name"].encode(), "source.pdf"

    monkeypatch.setattr(PdfConverterRegistry, "convert", convert)
    monkeypatch.setattr(downloads, "_apply_qa_pdf_watermark", watermark)
    monkeypatch.setattr(
        import_module("bisheng.core.cache.redis_manager"),
        "get_redis_client_sync",
        lambda: SimpleNamespace(connection=redis),
    )
    return SimpleNamespace(storage=storage, redis=redis, conversions=conversions, watermarks=watermarks)


async def download(environment, user="alice", tenant_id=1, source=None):
    return await downloads.build_qa_asset_download(
        source=source or "/bisheng/qa-expert/1/question/attachment/a/source.doc",
        title="source.doc",
        user_name=user,
        account=user,
        department_name="",
        tenant_id=tenant_id,
        storage=environment.storage,
    )


async def test_preview_and_download_reuse_persisted_pdf_but_keep_user_watermarks(environment):
    first = await download(environment)
    second = await download(environment, user="bob")
    assert first[0].endswith(b"alice")
    assert second[0].endswith(b"bob")
    assert len(environment.conversions) == 1
    assert len(environment.storage.puts) == 1
    assert environment.watermarks[0][0] == environment.watermarks[1][0]
    for key in environment.storage.puts:
        assert environment.storage.objects[("bisheng", key)] == environment.watermarks[0][0]


@pytest.mark.parametrize("change", ["content", "tenant", "unscoped", "path", "bucket", "format"])
async def test_source_snapshot_changes_never_reuse_old_pdf(environment, change):
    await download(environment)
    source = "qa-expert/1/question/attachment/a/source.doc"
    bucket, tenant_id, filename = "bisheng", 1, "source.doc"
    data = b"source-v1"
    if change == "content":
        data = b"source-v2"
    elif change == "tenant":
        tenant_id = 2
    elif change == "unscoped":
        tenant_id = None
    elif change == "path":
        source = "qa-expert/1/question/attachment/b/source.doc"
    elif change == "bucket":
        bucket = "tmp-dir"
    else:
        filename = "source.ppt"
    service = QaPdfPreviewService(storage=environment.storage, redis_client=environment.redis)
    service.get_or_generate(
        source_bytes=data, filename=filename, source_bucket=bucket, source_object=source, tenant_id=tenant_id
    )
    assert len(environment.conversions) == 2
    assert len(set(environment.storage.puts)) == 2


async def test_deleted_source_cannot_be_read_through_cached_pdf(environment):
    await download(environment)
    del environment.storage.objects[("bisheng", "qa-expert/1/question/attachment/a/source.doc")]
    with pytest.raises(FileNotFoundError):
        await download(environment)
    assert len(environment.conversions) == 1


async def test_corrupt_or_missing_cached_pdf_is_regenerated(environment):
    await download(environment)
    key = ("bisheng", environment.storage.puts[0])
    environment.storage.objects[key] = b"broken PDF"
    await download(environment)
    del environment.storage.objects[key]
    await download(environment)
    assert len(environment.conversions) == 3
    assert len(set(environment.storage.puts)) == 1


async def test_cached_pdf_survives_service_recreation_and_redis_unavailability(environment, monkeypatch):
    await download(environment)

    def unavailable():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(import_module("bisheng.core.cache.redis_manager"), "get_redis_client_sync", unavailable)
    # 下载每次都新建服务实例; 只依赖持久存储即可命中。
    await download(environment, user="bob")
    assert len(environment.conversions) == 1


async def test_generation_failure_is_not_cached_and_next_request_retries(environment, monkeypatch):
    original = PdfConverterRegistry.convert

    def failed(*_args):
        raise PdfConversionError("office failed")

    monkeypatch.setattr(PdfConverterRegistry, "convert", failed)
    with pytest.raises(PdfConversionError):
        await download(environment)
    assert environment.storage.puts == []
    monkeypatch.setattr(PdfConverterRegistry, "convert", original)
    await download(environment)
    assert len(environment.conversions) == 1


async def test_invalid_converted_pdf_and_expired_lease_are_not_published(environment, monkeypatch):
    original = PdfConverterRegistry.convert

    def invalid(_self, _source, output_dir, _context):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "invalid.pdf"
        path.write_bytes(b"not pdf")
        return ConversionResult(path, "fake")

    monkeypatch.setattr(PdfConverterRegistry, "convert", invalid)
    from bisheng.knowledge.pdf.validator import PdfValidationError

    with pytest.raises(PdfValidationError):
        await download(environment)
    monkeypatch.setattr(PdfConverterRegistry, "convert", original)
    monkeypatch.setattr(Lease, "owned", lambda _self: False)
    with pytest.raises(QaPdfPreviewGenerationError):
        await download(environment)
    assert environment.storage.puts == []


async def test_concurrent_preview_requests_share_one_generation_even_if_first_is_cancelled(environment, monkeypatch):
    original = PdfConverterRegistry.convert
    started, release = Event(), Event()

    def slow(*args):
        started.set()
        assert release.wait(timeout=5)
        return original(*args)

    monkeypatch.setattr(PdfConverterRegistry, "convert", slow)
    first = asyncio.create_task(download(environment))
    assert await asyncio.to_thread(started.wait, 5)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    others = [asyncio.create_task(download(environment, user="bob")) for _ in range(3)]
    release.set()
    await asyncio.gather(*others)
    assert len(environment.conversions) == 1
    assert len(environment.storage.puts) == 1


async def test_preview_pdf_entry_and_download_entry_share_cache(environment):
    await download(environment)
    await downloads.build_watermarked_qa_pdf(
        source="/bisheng/qa-expert/1/question/attachment/a/source.doc",
        title="source.doc",
        user_name="preview",
        account="preview",
        department_name="",
        tenant_id=1,
        storage=environment.storage,
    )
    assert len(environment.conversions) == 1
    assert environment.watermarks[-1][1] == "preview"


async def test_s3_missing_object_is_a_cache_miss_but_storage_failure_is_not(environment, monkeypatch):
    original = environment.storage.get_object_sync

    def missing(**kwargs):
        try:
            return original(**kwargs)
        except FileNotFoundError:
            raise S3Error(None, "NoSuchKey", "missing", "resource", "request", "host") from None

    monkeypatch.setattr(environment.storage, "get_object_sync", missing)
    await download(environment)
    assert len(environment.conversions) == 1

    def denied(**kwargs):
        if kwargs["object_name"].startswith("knowledge/"):
            raise S3Error(None, "AccessDenied", "denied", "resource", "request", "host")
        return original(**kwargs)

    monkeypatch.setattr(environment.storage, "get_object_sync", denied)
    with pytest.raises(S3Error, match="AccessDenied"):
        await download(environment)
    assert len(environment.conversions) == 1


async def test_cold_cache_does_not_convert_without_coordination(environment, monkeypatch):
    def unavailable():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(import_module("bisheng.core.cache.redis_manager"), "get_redis_client_sync", unavailable)
    with pytest.raises(ConnectionError):
        await download(environment)
    assert environment.conversions == []
    assert environment.storage.puts == []


async def test_original_pdf_with_doc_name_keeps_existing_passthrough(environment):
    original = pdf_bytes()
    environment.storage.objects[("bisheng", "qa-expert/1/question/attachment/a/source.doc")] = original
    result = await download(environment)
    assert result[0] == original + b"alice"
    assert environment.conversions == []
    assert environment.storage.puts == []


@pytest.mark.skipif(shutil.which("soffice") is None, reason="本机未安装 LibreOffice")
def test_real_doc_conversion_and_reuse(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("QA cached DOC preview")
    source = tmp_path / "source.docx"
    document.save(source)
    subprocess.run(
        [
            shutil.which("soffice"),
            "--headless",
            f"-env:UserInstallation={(tmp_path / 'profile').as_uri()}",
            "--convert-to",
            "doc:MS Word 97",
            "--outdir",
            str(tmp_path),
            str(source),
        ],
        capture_output=True,
        check=True,
        timeout=90,
    )
    source_bytes = (tmp_path / "source.doc").read_bytes()
    assert source_bytes[:8] == bytes.fromhex("d0cf11e0a1b11ae1")
    storage, redis = Storage(), Redis()
    parameters = {
        "source_bytes": source_bytes,
        "filename": "source.doc",
        "source_bucket": "bisheng",
        "source_object": "qa-expert/1/question/attachment/real/source.doc",
        "tenant_id": 1,
    }
    first = QaPdfPreviewService(storage=storage, redis_client=redis).get_or_generate(**parameters)

    class NoConversion:
        def convert(self, *_args):
            pytest.fail("已有持久产物不应再次调用 LibreOffice")

    second = QaPdfPreviewService(storage=storage, converter_registry=NoConversion()).get_or_generate(**parameters)
    assert first == second
    with fitz.open(stream=first, filetype="pdf") as rendered:
        assert "QA cached DOC preview" in rendered[0].get_text()
    assert len(storage.puts) == 1
