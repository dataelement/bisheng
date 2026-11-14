"""Tests for the hosted (mineru.net) MinerU V4 transport.

Contract measured against the live service on 2026-11-13: submit takes a public
file URL and returns ``data.task_id``; status returns ``data.state`` and, once
done, ``data.full_zip_url``; the zip carries ``full.md`` + ``*_content_list.json``
(not the self-hosted ``middle_json.json``).
"""

import io
import json
import zipfile

import httpx
import pytest

from bisheng.core.config.settings import MineruV4Conf
from bisheng.knowledge.rag.pipeline.loader.mineru_v4 import MineruV4Loader
from bisheng.knowledge.rag.pipeline.loader.mineru_v4_client import MineruV4Error
from bisheng.knowledge.rag.pipeline.loader.mineru_v4_cloud_client import (
    MineruV4CloudClient,
    MineruV4CloudError,
)

TASK_URL = "https://mineru.net/api/v4/extract/task"
ZIP_URL = "https://cdn-mineru.openxlab.org.cn/pdf/2026/result.zip"
PUBLIC_PDF = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return output.getvalue()


def _result_zip(text: str = "Dummy PDF file", bbox=(90, 80, 305, 104)) -> bytes:
    content_list = [{"type": "text", "text": text, "bbox": list(bbox), "page_idx": 0}]
    return _zip_bytes(
        {
            "full.md": text.encode(),
            "abc_content_list.json": json.dumps(content_list).encode(),
            "layout.json": b"{}",
        }
    )


def _conf(**overrides) -> MineruV4Conf:
    base = {
        "api_url": TASK_URL,
        "api_key_enc": "",
        "api_key_env": "TEST_MV4_KEY",
        "request_timeout_seconds": 5,
        "job_timeout_seconds": 30,
        "poll_interval_seconds": 0.001,
        "cloud_model_version": "pipeline",
    }
    return MineruV4Conf(**{**base, **overrides})


class Recorder:
    def __init__(self, states=("pending", "done"), zip_bytes=None, submit=None, status=None):
        self.states = list(states)
        self.zip_bytes = zip_bytes if zip_bytes is not None else _result_zip()
        self.submit = submit or {"code": 0, "msg": "ok", "data": {"task_id": "task-1"}}
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/extract/task"):
            return httpx.Response(200, json=self.submit)
        if "/extract/task/" in request.url.path and "cdn" not in request.url.host:
            if self.status is not None:
                return httpx.Response(200, json=self.status)
            state = self.states.pop(0) if self.states else "done"
            body: dict = {"code": 0, "data": {"task_id": "task-1", "state": state}}
            if state == "done":
                body["data"]["full_zip_url"] = ZIP_URL
            return httpx.Response(200, json=body)
        if "cdn" in request.url.host:
            return httpx.Response(200, content=self.zip_bytes)
        raise AssertionError(f"unexpected request {request.method} {request.url}")


def test_parse_submits_polls_and_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MV4_KEY", "secret")
    rec = Recorder(states=["pending", "done"])
    client = MineruV4CloudClient(_conf(), transport=httpx.MockTransport(rec.handler))

    path = client.parse(PUBLIC_PDF, str(tmp_path))

    submit = next(r for r in rec.requests if r.method == "POST")
    assert json.loads(submit.content)["url"] == PUBLIC_PDF
    assert json.loads(submit.content)["model_version"] == "pipeline"
    assert zipfile.is_zipfile(path)
    assert sum(1 for r in rec.requests if "/extract/task/" in r.url.path) == 2


def test_api_key_is_never_sent_to_the_result_cdn(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MV4_KEY", "secret")
    rec = Recorder()
    client = MineruV4CloudClient(_conf(), transport=httpx.MockTransport(rec.handler))

    client.parse(PUBLIC_PDF, str(tmp_path))

    api_calls = [r for r in rec.requests if "mineru.net" in r.url.host]
    cdn_calls = [r for r in rec.requests if "cdn" in r.url.host]
    assert api_calls and all(r.headers.get("Authorization") == "Bearer secret" for r in api_calls)
    assert cdn_calls and all("Authorization" not in r.headers for r in cdn_calls)


def test_submit_error_code_carries_a_hint(tmp_path):
    rec = Recorder(submit={"code": -10002, "msg": 'field "url" is not a valid URL'})
    client = MineruV4CloudClient(_conf(), transport=httpx.MockTransport(rec.handler))

    with pytest.raises(MineruV4CloudError, match="not a valid URL"):
        client.parse(PUBLIC_PDF, str(tmp_path))


def test_failed_state_surfaces_the_service_reason(tmp_path):
    rec = Recorder(status={"code": 0, "data": {"state": "failed", "err_msg": "boom"}})
    client = MineruV4CloudClient(_conf(), transport=httpx.MockTransport(rec.handler))

    with pytest.raises(MineruV4CloudError, match="boom"):
        client.parse(PUBLIC_PDF, str(tmp_path))


def test_job_timeout_is_reported(tmp_path):
    rec = Recorder(status={"code": 0, "data": {"state": "running"}})
    client = MineruV4CloudClient(_conf(job_timeout_seconds=0.01), transport=httpx.MockTransport(rec.handler))

    with pytest.raises(MineruV4CloudError, match="timed out"):
        client.parse(PUBLIC_PDF, str(tmp_path))


def test_non_cloud_url_is_rejected_by_the_cloud_client():
    with pytest.raises(MineruV4CloudError, match="extract/task"):
        MineruV4CloudClient(_conf(api_url="https://self.hosted/root"))


# ---------------------------------------------------------------------------
# Loader side: the hosted zip has a different shape from the self-hosted one.
# ---------------------------------------------------------------------------


def _loader(tmp_path, **conf_kwargs) -> MineruV4Loader:
    conf = _conf(**conf_kwargs)
    return MineruV4Loader(
        file_path=str(tmp_path / "doc.pdf"),
        file_metadata={"file_name": "doc.pdf"},
        file_extension="pdf",
        tmp_dir=str(tmp_path),
        filter_page_header_footer=False,
        force_ocr=False,
        retain_images=False,
        **conf.model_dump(),
    )


def test_cloud_url_selects_the_cloud_transport(tmp_path):
    assert _loader(tmp_path).is_cloud
    assert not _loader(tmp_path, api_url="https://self.hosted/root").is_cloud


def test_cloud_zip_parses_into_content_and_bboxes(tmp_path):
    loader = _loader(tmp_path)
    archive = tmp_path / "result.zip"
    archive.write_bytes(_result_zip("Dummy PDF file", (90, 80, 305, 104)))

    documents = loader._build_cloud_documents(*loader._read_cloud_zip(str(archive)))

    assert documents[0].page_content == "Dummy PDF file"
    assert documents[0].metadata["types"] == ["text"]
    assert len(loader.bbox_list) == 1
    assert loader.bbox_list[0].bbox == [90.0, 80.0, 305.0, 104.0]
    assert loader.bbox_list[0].page == 0


def test_cloud_zip_without_full_md_is_rejected(tmp_path):
    loader = _loader(tmp_path)
    archive = tmp_path / "bad.zip"
    archive.write_bytes(_zip_bytes({"abc_content_list.json": b"[]"}))

    with pytest.raises(MineruV4Error, match=r"full\.md"):
        loader._read_cloud_zip(str(archive))


def test_unreachable_share_host_is_explained_before_any_remote_call(tmp_path, monkeypatch):
    """A loopback sharepoint can never be fetched by the hosted service."""
    loader = _loader(tmp_path)
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4")

    class Store:
        tmp_bucket = "tmp-dir"
        uploaded: list[str] = []

        def put_object_tmp_sync(self, object_name, *_args, **_kwargs):
            Store.uploaded.append(object_name)

        def get_share_link_sync(self, *_args, **_kwargs):
            return "http://localhost:9001/api/v1/download-shared-object/abc"

    store = Store()
    with pytest.raises(MineruV4Error, match="not reachable from the internet"):
        loader._cloud_public_url(store)
    assert Store.uploaded == [], "nothing may be staged for a host the API cannot reach"


# ---------------------------------------------------------------------------
# Upload mode: POST register → PUT bytes (no Content-Type) → poll → markdown.
# Measured 2026-11-14 against the live service.
# ---------------------------------------------------------------------------

UPLOAD_URL = "https://mineru.net/api/v1/agent/parse/file"
PRESIGNED = "https://mineru.oss-cn-shanghai.aliyuncs.com/api-upload/extract/x.pdf?Signature=abc"
MARKDOWN_URL = "https://cdn-mineru.openxlab.org.cn/pdf/x/full.md"


def _upload_conf(**overrides) -> MineruV4Conf:
    return _conf(api_url=UPLOAD_URL, **overrides)


def test_upload_mode_registers_puts_and_reads_markdown(tmp_path, monkeypatch):
    from bisheng.knowledge.rag.pipeline.loader.mineru_v4_cloud_client import MineruV4UploadClient

    monkeypatch.setenv("TEST_MV4_KEY", "secret")
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.4 test")
    states = iter(["waiting-file", "running", "done"])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST" and request.url.path.endswith("/agent/parse/file"):
            assert json.loads(request.content) == {"file_name": "doc.pdf"}
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "t1", "file_url": PRESIGNED}})
        if request.method == "PUT" and "aliyuncs" in request.url.host:
            assert "content-type" not in {k.lower() for k in request.headers.keys()}, (
                "a Content-Type breaks the OSS signature"
            )
            return httpx.Response(200)
        if "/api/v1/agent/parse/" in request.url.path:
            state = next(states)
            body: dict = {"code": 0, "data": {"task_id": "t1", "state": state}}
            if state == "done":
                body["data"]["markdown_url"] = MARKDOWN_URL
            return httpx.Response(200, json=body)
        if "cdn" in request.url.host:
            return httpx.Response(200, text="# Title\n\nbody text")
        raise AssertionError(f"unexpected {request.method} {request.url}")

    client = MineruV4UploadClient(_upload_conf(), transport=httpx.MockTransport(handler))
    markdown = client.parse_uploaded(str(source), "doc.pdf")

    assert markdown == "# Title\n\nbody text"
    assert sum(1 for r in calls if "/api/v1/agent/parse/t1" in r.url.path) == 3


def test_upload_mode_rejects_a_non_upload_url():
    from bisheng.knowledge.rag.pipeline.loader.mineru_v4_cloud_client import MineruV4UploadClient

    with pytest.raises(MineruV4CloudError, match="agent/parse/file"):
        MineruV4UploadClient(_conf())


def test_upload_mode_surfaces_register_errors(tmp_path, monkeypatch):
    from bisheng.knowledge.rag.pipeline.loader.mineru_v4_cloud_client import MineruV4UploadClient

    monkeypatch.setenv("TEST_MV4_KEY", "k")
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    client = MineruV4UploadClient(
        _upload_conf(),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": -10002, "msg": "bad"})),
    )
    with pytest.raises(MineruV4CloudError, match="-10002"):
        client.parse_uploaded(str(source), "doc.pdf")


def test_upload_url_selects_the_upload_transport(tmp_path):
    loader = _loader(tmp_path, api_url=UPLOAD_URL)
    assert loader.is_upload and not loader.is_cloud


def test_upload_result_has_no_bbox_metadata(tmp_path, monkeypatch):
    """The upload endpoint returns markdown only; bbox metadata stays empty."""
    monkeypatch.setattr(
        "bisheng.knowledge.rag.pipeline.loader.mineru_v4_cloud_client.MineruV4UploadClient.parse_uploaded",
        lambda self, path, name: "# Doc\n\ntext",
    )
    loader = _loader(tmp_path, api_url=UPLOAD_URL)
    documents = loader._load_upload()
    assert documents[0].page_content == "# Doc\n\ntext"
    assert documents[0].metadata["bboxes"] == [] and loader.bbox_list == []
