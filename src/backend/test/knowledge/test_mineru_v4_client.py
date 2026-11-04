import io
import zipfile

import httpx
import pytest

from bisheng.core.config.settings import MineruV4Conf
from bisheng.knowledge.rag.pipeline.loader.mineru_v4_client import MineruV4Client, MineruV4Error


def _zip_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("middle_json.json", "{}")
    return output.getvalue()


def test_parse_job_upload_poll_and_download(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MINERU_V4_KEY", "private-token")
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    calls = []
    statuses = iter(["queued", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/uploads":
            return httpx.Response(
                200,
                json={
                    "id": "upload-1",
                    "status": "pending",
                    "upload_url": "/v1/uploads/upload-1/content",
                    "upload_method": "PUT",
                    "upload_headers": {"Content-Type": "application/pdf"},
                },
            )
        if request.url.path == "/v1/uploads/upload-1/content":
            assert request.headers["Authorization"] == "Bearer private-token"
            return httpx.Response(200)
        if request.url.path == "/v1/uploads/upload-1/complete":
            return httpx.Response(200, json={"status": "completed", "file": {"id": "file-1"}})
        if request.url.path == "/v1/parse/jobs" and request.method == "POST":
            body = __import__("json").loads(request.content)
            assert body == {
                "files": [{"source": {"type": "file_id", "file_id": "file-1"}}],
                "tier": "standard",
                "ocr_mode": "ocr",
                "output_formats": ["zip"],
                "callback": {"url": "https://callback.example"},
            }
            return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})
        if request.url.path == "/v1/parse/jobs/job-1":
            status = next(statuses)
            return httpx.Response(
                200,
                json={
                    "status": status,
                    "files": [{"status": status, "output_files": {"zip": {"file_id": "zip-1"}}}],
                },
            )
        if request.url.path == "/v1/files/zip-1/content":
            return httpx.Response(200, content=_zip_bytes())
        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    config = MineruV4Conf(
        api_url="https://mineru.example",
        api_key_env="TEST_MINERU_V4_KEY",
        poll_interval_seconds=0.001,
        request_kwargs={"callback": {"url": "https://callback.example"}},
    )
    client = MineruV4Client(config, transport=httpx.MockTransport(handler))
    archive_path = client.parse(str(source), "sample.pdf", "ocr", str(tmp_path))
    assert zipfile.is_zipfile(archive_path)
    assert len([call for call in calls if call.url.path == "/v1/parse/jobs/job-1"]) == 2


def test_cross_origin_upload_and_download_never_receive_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MINERU_V4_KEY", "private-token")
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    external_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "storage.example":
            external_headers.append(request.headers)
            if request.method == "PUT":
                return httpx.Response(200)
            return httpx.Response(200, content=_zip_bytes())
        if request.url.path == "/v1/uploads":
            return httpx.Response(
                200,
                json={
                    "id": "upload-1",
                    "status": "pending",
                    "upload_url": "https://storage.example/upload",
                    "upload_method": "PUT",
                    "upload_headers": {"x-upload-token": "upload-only"},
                },
            )
        if request.url.path == "/v1/uploads/upload-1/complete":
            return httpx.Response(200, json={"status": "completed", "file": {"id": "file-1"}})
        if request.url.path == "/v1/parse/jobs" and request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1"})
        if request.url.path == "/v1/parse/jobs/job-1":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "files": [{"status": "completed", "output_files": {"zip": {"file_id": "zip-1"}}}],
                },
            )
        if request.url.path == "/v1/files/zip-1/content":
            return httpx.Response(302, headers={"Location": "https://storage.example/download"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = MineruV4Conf(api_url="https://mineru.example", api_key_env="TEST_MINERU_V4_KEY")
    archive_path = MineruV4Client(config, transport=httpx.MockTransport(handler)).parse(
        str(source), "sample.pdf", "auto", str(tmp_path)
    )
    assert zipfile.is_zipfile(archive_path)
    assert len(external_headers) == 2
    assert all("authorization" not in headers for headers in external_headers)
    assert external_headers[0]["x-upload-token"] == "upload-only"


def test_completed_without_zip_fails(tmp_path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/uploads":
            return httpx.Response(200, json={"status": "completed", "file": {"id": "file-1"}})
        if request.url.path == "/v1/parse/jobs" and request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1"})
        if request.url.path == "/v1/parse/jobs/job-1":
            return httpx.Response(200, json={"status": "completed", "files": [{"status": "completed"}]})
        raise AssertionError(request.url)

    with pytest.raises(MineruV4Error, match="zip"):
        MineruV4Client(MineruV4Conf(api_url="https://mineru.example"), transport=httpx.MockTransport(handler)).parse(
            str(source), "sample.pdf", "auto", str(tmp_path)
        )


def test_request_kwargs_rejects_managed_fields():
    with pytest.raises(ValueError, match="managed fields"):
        MineruV4Conf(request_kwargs={"files": []})


@pytest.mark.parametrize("status", ["partial", "failed", "canceled"])
def test_terminal_failure_never_downloads_partial_result(tmp_path, status):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/uploads":
            return httpx.Response(200, json={"status": "completed", "file": {"id": "file-1"}})
        if request.url.path == "/v1/parse/jobs" and request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1"})
        if request.url.path == "/v1/parse/jobs/job-1":
            return httpx.Response(200, json={"status": status, "files": []})
        raise AssertionError("A failed job must not download a result")

    client = MineruV4Client(MineruV4Conf(api_url="https://mineru.example"), transport=httpx.MockTransport(handler))
    with pytest.raises(MineruV4Error, match=status):
        client.parse(str(source), source.name, "auto", str(tmp_path))


def test_total_timeout_applies_before_upload(tmp_path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    config = MineruV4Conf(api_url="https://mineru.example", job_timeout_seconds=1e-9)
    client = MineruV4Client(config, transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected HTTP request")))
    with pytest.raises(MineruV4Error, match=r"^MinerU V4 parse job timed out$"):
        client.parse(str(source), source.name, "auto", str(tmp_path))


def test_request_kwargs_rejects_non_mapping_and_non_json_value():
    with pytest.raises(ValueError):
        MineruV4Conf(request_kwargs=["invalid"])
    with pytest.raises(ValueError, match="JSON serializable"):
        MineruV4Conf(request_kwargs={"callback": {1, 2}})
    with pytest.raises(ValueError, match="keys must be strings"):
        MineruV4Conf(request_kwargs={1: "value"})
    with pytest.raises(ValueError, match="JSON serializable"):
        MineruV4Conf(request_kwargs={"score": float("nan")})
