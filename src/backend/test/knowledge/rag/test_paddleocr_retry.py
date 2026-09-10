from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader
from bisheng.utils.exceptions import EtlException


def _loader(**kwargs) -> PaddleOcrLoader:
    return PaddleOcrLoader(
        url="https://paddle-ocr.example/layout-parsing",
        file_path="unused.png",
        file_metadata={},
        file_extension="png",
        tmp_dir=".",
        retry_backoff=0.25,
        **kwargs,
    )


def _response(status_code: int, payload: dict, text: str = "response") -> MagicMock:
    response = MagicMock(status_code=status_code, text=text)
    response.json.return_value = payload
    return response


def test_sync_retries_queue_full_response_then_succeeds() -> None:
    queue_full = _response(
        503,
        {"errorCode": 10010, "errorMsg": "queue full"},
    )
    success = _response(200, {"errorCode": 0, "result": {"layoutParsingResults": []}})
    loader = _loader(max_retries=2)

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.paddle_ocr.requests.post", side_effect=[queue_full, success]
    ) as post:
        with patch("bisheng.knowledge.rag.pipeline.loader.paddle_ocr.time.sleep") as sleep:
            result = loader._call_api_sync("encoded")

    assert result == {"layoutParsingResults": []}
    assert post.call_count == 2
    sleep.assert_called_once_with(0.25)


def test_sync_does_not_retry_non_transient_response() -> None:
    bad_request = _response(400, {"errorCode": 40001, "errorMsg": "bad request"}, text="bad request")
    loader = _loader(max_retries=3)

    with patch("bisheng.knowledge.rag.pipeline.loader.paddle_ocr.requests.post", return_value=bad_request) as post:
        with pytest.raises(EtlException, match="status=400"):
            loader._call_api_sync("encoded")

    post.assert_called_once()


def test_sync_stops_after_configured_retries() -> None:
    queue_full = _response(503, {"errorCode": 10010, "errorMsg": "queue full"}, text="queue full")
    loader = _loader(max_retries=1)

    with patch(
        "bisheng.knowledge.rag.pipeline.loader.paddle_ocr.requests.post",
        side_effect=[queue_full, queue_full],
    ) as post:
        with patch("bisheng.knowledge.rag.pipeline.loader.paddle_ocr.time.sleep") as sleep:
            with pytest.raises(EtlException, match="status=503"):
                loader._call_api_sync("encoded")

    assert post.call_count == 2
    sleep.assert_called_once_with(0.25)


async def test_async_retries_rate_limit_business_code_then_succeeds() -> None:
    rate_limited = _response(200, {"errorCode": 12002, "errorMsg": "rate limited"})
    success = _response(200, {"errorCode": 0, "result": {"layoutParsingResults": []}})
    client = MagicMock()
    client.post = AsyncMock(side_effect=[rate_limited, success])
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=None)
    loader = _loader(max_retries=2)

    with patch("bisheng.knowledge.rag.pipeline.loader.paddle_ocr.httpx.AsyncClient", return_value=client_context):
        with patch("bisheng.knowledge.rag.pipeline.loader.paddle_ocr.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await loader._call_api_async("encoded")

    assert result == {"layoutParsingResults": []}
    assert client.post.await_count == 2
    sleep.assert_awaited_once_with(0.25)
