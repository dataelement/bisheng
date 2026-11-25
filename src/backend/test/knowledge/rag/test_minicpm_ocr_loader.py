import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import requests

from bisheng.knowledge.rag.pipeline.loader.minicpm_ocr import MinicpmOcrLoader
from bisheng.utils.exceptions import EtlException

ENDPOINT = "http://minicpm.example/v1/chat/completions"


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "response"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def _completion(text: str, finish_reason: str = "stop") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}]}


def _respond_by_page(url, json=None, headers=None) -> _Response:
    """Answer each page with its own text, independent of request ordering."""
    image_url = json["messages"][0]["content"][0]["image_url"]["url"]
    label = "one" if image_url.endswith(base64.b64encode(b"one").decode("ascii")) else "two"
    return _Response(200, _completion(f"page {label}"))


def _loader(**kwargs) -> MinicpmOcrLoader:
    return MinicpmOcrLoader(
        base_url="http://minicpm.example/v1",
        file_path="unused.pdf",
        file_metadata={},
        file_extension="pdf",
        tmp_dir=".",
        retry_backoff=0.25,
        **kwargs,
    )


def test_endpoint_normalizes_trailing_slash() -> None:
    loader = MinicpmOcrLoader(
        base_url="http://minicpm.example/v1/",
        file_path="unused.pdf",
        file_metadata={},
        file_extension="pdf",
        tmp_dir=".",
    )
    assert loader._endpoint == ENDPOINT


def test_missing_base_url_is_rejected() -> None:
    with pytest.raises(EtlException, match="base_url"):
        MinicpmOcrLoader(
            base_url="",
            file_path="unused.pdf",
            file_metadata={},
            file_extension="pdf",
            tmp_dir=".",
        )


def test_payload_sends_image_before_prompt() -> None:
    payload = _loader()._build_payload(b"image-bytes", "image/png")

    content = payload["messages"][0]["content"]
    assert [part["type"] for part in content] == ["image_url", "text"]
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1] == {"type": "text", "text": "Text Recognition:"}
    assert payload["model"] == "minicpm-ocr"
    assert payload["max_tokens"] == 4096
    assert payload["temperature"] == 0.0
    # vLLM only accepts request-level processor kwargs with --trust-request-mm-kwargs.
    assert "mm_processor_kwargs" not in payload


def test_mm_processor_kwargs_sent_only_when_configured() -> None:
    assert "mm_processor_kwargs" not in _loader(mm_processor_kwargs={})._build_payload(b"img", "image/png")

    payload = _loader(mm_processor_kwargs={"downsample_mode": "4x"})._build_payload(b"img", "image/png")
    assert payload["mm_processor_kwargs"] == {"downsample_mode": "4x"}


def test_request_kwargs_are_merged_but_cannot_override_managed_fields() -> None:
    payload = _loader(
        request_kwargs={"top_k": 1, "model": "other", "messages": [], "max_tokens": 1}
    )._build_payload(b"img", "image/png")

    assert payload["top_k"] == 1
    assert payload["model"] == "minicpm-ocr"
    assert payload["max_tokens"] == 4096
    assert [part["type"] for part in payload["messages"][0]["content"]] == ["image_url", "text"]


def test_api_key_and_custom_headers() -> None:
    loader = _loader(api_key="secret", headers={"X-Tenant": "kb"})
    assert loader.headers == {"X-Tenant": "kb", "Authorization": "Bearer secret"}


def test_sync_retries_transient_status_then_succeeds() -> None:
    responses = [_Response(429, text="rate limited"), _Response(200, _completion("hello"))]
    loader = _loader(max_retries=2)

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.requests.post", side_effect=responses
    ) as post, patch("bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.time.sleep") as sleep:
        assert loader._recognize_sync(1, {}) == "hello"

    assert post.call_count == 2
    sleep.assert_called_once_with(0.25)


def test_sync_gives_up_after_configured_retries() -> None:
    response = _Response(503, text="unavailable")
    loader = _loader(max_retries=1)

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.requests.post", return_value=response
    ) as post, patch("bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.time.sleep"):
        with pytest.raises(EtlException, match="status=503"):
            loader._recognize_sync(3, {})

    assert post.call_count == 2


def test_sync_does_not_retry_client_error() -> None:
    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.requests.post",
        return_value=_Response(400, text="bad request"),
    ) as post:
        with pytest.raises(EtlException, match="status=400"):
            _loader(max_retries=3)._recognize_sync(1, {})

    post.assert_called_once()


def test_sync_retries_connect_timeout_and_read_timeout_is_fatal() -> None:
    loader = _loader(max_retries=1)

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.requests.post",
        side_effect=[requests.ConnectTimeout("connect timed out"), _Response(200, _completion("ok"))],
    ) as post, patch("bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.time.sleep") as sleep:
        assert loader._recognize_sync(1, {}) == "ok"

    assert post.call_count == 2
    sleep.assert_called_once_with(0.25)

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.requests.post",
        side_effect=requests.ReadTimeout("read timed out"),
    ) as post:
        with pytest.raises(EtlException, match="timeout"):
            loader._recognize_sync(1, {})

    post.assert_called_once()


def test_sync_wraps_unexpected_request_errors() -> None:
    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.requests.post",
        side_effect=requests.TooManyRedirects("too many redirects"),
    ):
        with pytest.raises(EtlException, match="request failed"):
            _loader()._recognize_sync(1, {})


def test_truncated_output_raises() -> None:
    with pytest.raises(EtlException, match="truncated"):
        _loader()._extract_text(_completion("partial", finish_reason="length"), 2)


def test_unexpected_response_shape_raises() -> None:
    with pytest.raises(EtlException, match="unexpected response"):
        _loader()._extract_text({"choices": []}, 1)


def test_thinking_output_in_reasoning_content_raises() -> None:
    response = {
        "choices": [
            {
                "message": {"content": "", "reasoning_content": "recognized text"},
                "finish_reason": "stop",
            }
        ]
    }

    with pytest.raises(EtlException, match="reasoning_content"):
        _loader()._extract_text(response, 3)


def test_blank_page_without_reasoning_is_skipped() -> None:
    response = {"choices": [{"message": {"content": "  "}, "finish_reason": "stop"}]}

    assert _loader()._extract_text(response, 1) == ""


def test_document_indexes_match_merged_content() -> None:
    loader = _loader()
    loader.file_metadata = {"document_id": 42}
    document = loader._build_document(["AAA", "", "BB"])

    assert document.page_content == "AAA\n\nBB"
    assert document.metadata["pages"] == [0, 2]
    assert document.metadata["indexes"] == [[0, 3], [5, 7]]
    assert document.metadata["bboxes"] == [[], []]
    assert document.metadata["types"] == ["text", "text"]
    assert document.metadata["document_id"] == 42


def test_html_tables_are_converted_to_markdown() -> None:
    document = _loader()._build_document(["<table><tr><td>a</td></tr></table>"])

    assert "<table" not in document.page_content
    assert "| a |" in document.page_content
    assert document.metadata["indexes"][0][1] == len(document.page_content)


def test_document_without_content_raises() -> None:
    with pytest.raises(EtlException, match="no readable content"):
        _loader()._build_document(["", "   "])


def test_load_sends_one_request_per_page(monkeypatch) -> None:
    loader = _loader(concurrency=2)
    monkeypatch.setattr(loader, "_page_images", lambda: [(b"page-1", "image/png"), (b"page-2", "image/png")])
    calls = []

    def fake_recognize(page_number: int, payload: dict) -> str:
        calls.append((page_number, payload))
        return f"T{page_number}"

    monkeypatch.setattr(loader, "_recognize_sync", fake_recognize)

    documents = loader.load()

    assert sorted(number for number, _ in calls) == [1, 2]
    assert documents[0].page_content == "T1\n\nT2"
    assert documents[0].metadata["pages"] == [0, 1]


def test_image_input_is_sent_without_rasterizing(tmp_path) -> None:
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"png-bytes")
    loader = MinicpmOcrLoader(
        base_url="http://minicpm.example/v1",
        file_path=str(image_path),
        file_metadata={},
        file_extension="png",
        tmp_dir=str(tmp_path),
    )

    assert loader._page_images() == [(b"png-bytes", "image/png")]


def test_missing_image_reports_read_error(tmp_path) -> None:
    loader = MinicpmOcrLoader(
        base_url="http://minicpm.example/v1",
        file_path=str(tmp_path / "missing.jpg"),
        file_metadata={},
        file_extension="jpg",
        tmp_dir=str(tmp_path),
    )

    with pytest.raises(EtlException, match="Cannot read file"):
        loader._page_images()


async def test_async_posts_every_page_in_order(monkeypatch) -> None:
    client = MagicMock()
    client.post = AsyncMock(side_effect=_respond_by_page)
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=None)
    loader = _loader(concurrency=2)
    monkeypatch.setattr(loader, "_page_images", lambda: [(b"one", "image/png"), (b"two", "image/png")])

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.httpx.AsyncClient", return_value=client_context
    ):
        documents = await loader.aload()

    assert client.post.await_count == 2
    assert documents[0].page_content == "page one\n\npage two"


async def test_async_retries_transient_status(monkeypatch) -> None:
    client = MagicMock()
    client.post = AsyncMock(side_effect=[_Response(503, text="busy"), _Response(200, _completion("ok"))])
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=None)
    loader = _loader(max_retries=1)
    monkeypatch.setattr(loader, "_page_images", lambda: [(b"one", "image/png")])

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.httpx.AsyncClient", return_value=client_context
    ), patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        documents = await loader.aload()

    assert client.post.await_count == 2
    sleep.assert_awaited_once_with(0.25)
    assert documents[0].page_content == "ok"


async def test_async_retries_connect_timeout(monkeypatch) -> None:
    client = MagicMock()
    client.post = AsyncMock(
        side_effect=[httpx.ConnectTimeout("connect timed out"), _Response(200, _completion("ok"))]
    )
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=None)
    loader = _loader(max_retries=1)
    monkeypatch.setattr(loader, "_page_images", lambda: [(b"one", "image/png")])

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.httpx.AsyncClient", return_value=client_context
    ), patch(
        "bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        documents = await loader.aload()

    assert client.post.await_count == 2
    sleep.assert_awaited_once_with(0.25)
    assert documents[0].page_content == "ok"


async def test_async_propagates_page_failure(monkeypatch) -> None:
    client = MagicMock()
    client.post = AsyncMock(return_value=_Response(400, text="bad request"))
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=None)
    loader = _loader()
    monkeypatch.setattr(loader, "_page_images", lambda: [(b"one", "image/png")])

    with patch("bisheng.knowledge.rag.pipeline.loader.minicpm_ocr.httpx.AsyncClient", return_value=client_context):
        with pytest.raises(EtlException, match="status=400"):
            await loader.aload()
