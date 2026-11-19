"""Tests for the PaddleOCR hosted jobs API client.

Every expectation here encodes behaviour measured against the live
``/api/v2/ocr/jobs`` service on 2026-11-12 — see the module docstring of
``paddle_ocr_client.py`` for the contract.
"""

import httpx
import pytest

from bisheng.core.config.settings import KnowledgeConf, PaddleOcrConf
from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader
from bisheng.knowledge.rag.pipeline.loader.paddle_ocr_client import (
    PaddleOcrJobsClient,
    PaddleOcrJobsError,
)
from bisheng.utils.exceptions import EtlException

JOBS_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
# The presigned result lives on a different host; the token must never follow it.
RESULT_URL = "https://paddleocr-store-5.bj.bcebos.com/v1/job/abc/json/def.json?authorization=bce-auth-v1"

INLINE_RESULT = {
    "logId": "c99a3ec0",
    "errorCode": 0,
    "errorMsg": "Success",
    "result": {
        "layoutParsingResults": [
            {
                "prunedResult": {
                    "width": 1191,
                    "height": 1684,
                    "parsing_res_list": [
                        {
                            "block_content": "Section 1: Quarterly Report",
                            "block_label": "paragraph_title",
                            "block_bbox": [72, 88, 500, 110],
                            "block_order": 1,
                        },
                        {
                            "block_content": "The revenue grew by 12 percent.",
                            "block_label": "text",
                            "block_bbox": [72, 130, 600, 152],
                            "block_order": 2,
                        },
                    ],
                },
                "markdown": {"text": "# Section 1: Quarterly Report\n\nThe revenue grew by 12 percent.", "images": {}},
            }
        ]
    },
}


def _conf(**overrides) -> PaddleOcrConf:
    base = {
        "url": JOBS_URL,
        "model": "PaddleOCR-VL-1.6",
        "api_key_env": "TEST_PADDLE_TOKEN",
        "poll_interval_seconds": 0.001,
        "job_timeout_seconds": 30,
        "retry_backoff": 0.01,
        "timeout": 5,
    }
    return PaddleOcrConf(**{**base, **overrides})


@pytest.fixture(autouse=True)
def _paddle_token_env(monkeypatch):
    """The client refuses to build without a token, so every test provides one."""
    monkeypatch.setenv("TEST_PADDLE_TOKEN", "secret-token")


def _source(tmp_path) -> str:
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    return str(path)


class Recorder:
    """Handler that serves the three API steps and records every request."""

    def __init__(self, *, states=("pending", "done"), result_url=RESULT_URL, submit_body=None, submit_status=200):
        self.states = list(states)
        self.result_url = result_url
        self.submit_body = submit_body or {"code": 0, "msg": "Success", "data": {"jobId": "job-1"}}
        self.submit_status = submit_status
        self.requests: list[httpx.Request] = []
        self.submits = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/jobs") and request.method == "POST":
            self.submits += 1
            return httpx.Response(self.submit_status, json=self.submit_body)
        if path.endswith("/job-1"):
            state = self.states.pop(0) if self.states else "done"
            body: dict = {"code": 0, "msg": "Success", "data": {"jobId": "job-1", "state": state}}
            if state == "done":
                body["data"]["resultUrl"] = {"jsonUrl": self.result_url}
            return httpx.Response(200, json=body)
        if "bcebos.com" in request.url.host:
            return httpx.Response(200, json=INLINE_RESULT)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def test_submits_multipart_with_file_and_model(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_PADDLE_TOKEN", "secret-token")
    source = _source(tmp_path)
    rec = Recorder()
    client = PaddleOcrJobsClient(_conf(), transport=rec.transport())

    result = client.parse(source)

    submit = rec.requests[0]
    assert "multipart/form-data" in submit.headers["content-type"], "the API rejects a JSON body with HTTP 500"
    assert submit.headers["Authorization"] == "token secret-token"
    assert result == INLINE_RESULT["result"]


def test_send_model_as_form_field_not_json_body(tmp_path):
    source = _source(tmp_path)
    rec = Recorder()
    client = PaddleOcrJobsClient(_conf(), transport=rec.transport())
    client.parse(source)

    body = rec.requests[0].content.decode("latin-1")
    assert 'name="model"' in body and "PaddleOCR-VL-1.6" in body
    assert 'name="file"' in body
    # A JSON body is what the old sync loader sent and what the service refuses.
    assert not body.lstrip().startswith("{")


def test_polls_until_done_then_fetches_presigned_result(tmp_path):
    source = _source(tmp_path)
    rec = Recorder(states=["pending", "pending", "done"])
    client = PaddleOcrJobsClient(_conf(), transport=rec.transport())

    result = client.parse(source)

    status_calls = [r for r in rec.requests if r.url.path.endswith("/job-1")]
    assert len(status_calls) == 3, "one poll per intermediate state plus the final one"
    assert any("bcebos.com" in r.url.host for r in rec.requests), "result must come from the presigned jsonUrl"
    assert result["layoutParsingResults"][0]["prunedResult"]["width"] == 1191


def test_token_is_never_sent_to_the_object_store(tmp_path, monkeypatch):
    """The presigned URL authenticates by query string; leaking the token there is a real risk."""
    monkeypatch.setenv("TEST_PADDLE_TOKEN", "secret-token")
    source = _source(tmp_path)
    rec = Recorder()
    client = PaddleOcrJobsClient(_conf(api_key_env="TEST_PADDLE_TOKEN"), transport=rec.transport())

    client.parse(source)

    jobs_calls = [r for r in rec.requests if "aistudio-app.com" in r.url.host]
    store_calls = [r for r in rec.requests if "bcebos.com" in r.url.host]
    assert jobs_calls and all(r.headers.get("Authorization") == "token secret-token" for r in jobs_calls)
    assert store_calls and all("Authorization" not in r.headers for r in store_calls)


def test_missing_token_env_var_fails_loudly_at_construction(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_PADDLE_TOKEN_MISSING", raising=False)
    with pytest.raises(PaddleOcrJobsError, match="token is missing"):
        PaddleOcrJobsClient(_conf(api_key_env="TEST_PADDLE_TOKEN_MISSING"))


def test_missing_model_fails_loudly_at_construction(monkeypatch):
    monkeypatch.setenv("TEST_PADDLE_TOKEN", "x")
    with pytest.raises(PaddleOcrJobsError, match=r"requires knowledge\.paddle_ocr\.model"):
        PaddleOcrJobsClient(_conf(model=""))


def test_wrong_model_business_code_is_not_retried(tmp_path):
    """Live service: code 10007 模型传参错误. Not retryable, so it must fail immediately."""
    source = _source(tmp_path)
    rec = Recorder(submit_body={"code": 10007, "msg": "模型传参错误", "data": {}})
    client = PaddleOcrJobsClient(_conf(max_retries=3), transport=rec.transport())

    with pytest.raises(PaddleOcrJobsError, match="code=10007"):
        client.parse(source)
    assert rec.submits == 1


def test_queue_full_business_code_is_retried_then_succeeds(tmp_path):
    source = _source(tmp_path)
    queue_full = {"code": 10010, "msg": "queue full", "data": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs") and request.method == "POST":
            handler.calls += 1
            if handler.calls == 1:
                return httpx.Response(200, json=queue_full)
            return httpx.Response(200, json={"code": 0, "msg": "Success", "data": {"jobId": "job-1"}})
        if request.url.path.endswith("/job-1"):
            return httpx.Response(
                200, json={"code": 0, "data": {"jobId": "job-1", "state": "done", "resultUrl": {"jsonUrl": RESULT_URL}}}
            )
        return httpx.Response(200, json=INLINE_RESULT)

    handler.calls = 0
    client = PaddleOcrJobsClient(_conf(max_retries=2), transport=httpx.MockTransport(handler))
    assert client.parse(source) == INLINE_RESULT["result"]
    assert handler.calls == 2


def test_failed_job_state_surfaces_the_provider_reason(tmp_path):
    source = _source(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"code": 0, "data": {"jobId": "job-1"}})
        return httpx.Response(
            200,
            # Verbatim from the live service, fullwidth comma included — the point
            # of the test is that provider text passes through untouched.
            json={"code": 0, "data": {"jobId": "job-1", "state": "failed", "errorMsg": "OCR服务请求失败，状态码 500"}},  # noqa: RUF001
        )

    client = PaddleOcrJobsClient(_conf(), transport=httpx.MockTransport(handler))
    with pytest.raises(PaddleOcrJobsError, match="OCR服务请求失败"):
        client.parse(source)


def test_job_timeout_is_reported_as_a_failure(tmp_path):
    source = _source(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"code": 0, "data": {"jobId": "job-1"}})
        return httpx.Response(200, json={"code": 0, "data": {"jobId": "job-1", "state": "pending"}})

    client = PaddleOcrJobsClient(
        _conf(job_timeout_seconds=0.01, poll_interval_seconds=0.001), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(PaddleOcrJobsError, match="timed out"):
        client.parse(source)


def test_result_error_code_is_raised(tmp_path):
    source = _source(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"code": 0, "data": {"jobId": "job-1"}})
        if request.url.path.endswith("/job-1"):
            return httpx.Response(
                200, json={"code": 0, "data": {"jobId": "job-1", "state": "done", "resultUrl": {"jsonUrl": RESULT_URL}}}
            )
        return httpx.Response(200, json={"errorCode": 1056, "errorMsg": "文档无法解析", "result": {}})

    client = PaddleOcrJobsClient(_conf(), transport=httpx.MockTransport(handler))
    with pytest.raises(PaddleOcrJobsError, match="文档无法解析"):
        client.parse(source)


def test_jobs_error_is_an_etl_exception_so_the_file_is_marked_failed():
    """knowledge_imp.py only writes a parse_failed remark for EtlException."""
    assert issubclass(PaddleOcrJobsError, EtlException)


async def test_async_path_matches_the_sync_contract(tmp_path):
    source = _source(tmp_path)
    rec = Recorder(states=["pending", "done"])
    client = PaddleOcrJobsClient(_conf(), transport=rec.transport())

    result = await client.parse_async(source)

    assert result == INLINE_RESULT["result"]
    assert "multipart/form-data" in rec.requests[0].headers["content-type"]
    assert [r for r in rec.requests if r.url.path.endswith("/job-1")]


# ----------------------------------------------------------------------------------
# Loader-level dispatch: which transport each deployment form selects.
# ----------------------------------------------------------------------------------


def _loader(tmp_path, **paddle_kwargs) -> PaddleOcrLoader:
    conf = KnowledgeConf(loader_provider="paddle_ocr", paddle_ocr=paddle_kwargs)
    path = tmp_path / "report.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n test")
    return PaddleOcrLoader(
        file_path=str(path),
        file_metadata={},
        file_extension="png",
        tmp_dir=str(tmp_path / "out"),
        filter_page_header_footer=False,
        **conf.paddle_ocr.model_dump(),
    )


def test_jobs_url_selects_the_jobs_transport(tmp_path):
    loader = _loader(tmp_path, url=JOBS_URL, model="PaddleOCR-VL-1.6", api_key_env="TEST_PADDLE_TOKEN")
    assert loader.service_mode == "jobs"


def test_layout_parsing_url_stays_on_the_existing_sync_path(tmp_path):
    """A self-hosted PP-StructureV3 deployment must be untouched by this change."""
    loader = _loader(tmp_path, url="https://paddle.example/layout-parsing", auth_token="t")
    assert loader.service_mode == "sync"
    assert loader.headers["Authorization"] == "token t"


def test_explicit_service_mode_overrides_detection(tmp_path):
    loader = _loader(tmp_path, url=JOBS_URL, service_mode="sync", auth_token="t")
    assert loader.service_mode == "sync"


def test_service_mode_never_raises_from_config_load(tmp_path):
    """get_knowledge() rebuilds this class on every read; a bad OCR line must not 500 the platform."""
    conf = KnowledgeConf(loader_provider="paddle_ocr", paddle_ocr={"url": JOBS_URL})  # no model, no api_key_env
    assert KnowledgeConf(**conf.model_dump()).paddle_ocr.resolved_service_mode == "jobs"


def test_loader_parses_a_jobs_result_into_documents(tmp_path):
    """End to end through the real parsing half of the loader."""
    import os

    os.environ["TEST_PADDLE_TOKEN"] = "secret-token"
    rec = Recorder()
    loader = _loader(
        tmp_path,
        url=JOBS_URL,
        model="PaddleOCR-VL-1.6",
        api_key_env="TEST_PADDLE_TOKEN",
    )
    try:
        loader._jobs_client = PaddleOcrJobsClient(loader.config, transport=rec.transport())
        documents = loader.load()
    finally:
        os.environ.pop("TEST_PADDLE_TOKEN", None)

    assert len(documents) == 1
    content = documents[0].page_content
    assert "Section 1: Quarterly Report" in content
    assert "revenue grew by 12 percent" in content
    assert len(loader.bbox_list) == 2, "bboxes must survive so citation highlighting still works"
    assert documents[0].metadata["types"] == ["Title", "text"]
