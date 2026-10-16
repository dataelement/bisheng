"""API execution: upstream failures, bounded streams and credential-safe logging."""

import httpx
import pytest

from bisheng.common.errcode.dsh import DshToolOutputTooLargeError, DshToolUpstreamFailedError
from bisheng.tool.domain.services.bounded_openapi import BoundedOpenApiTools


def implementation():
    return BoundedOpenApiTools(
        url="https://fixture.example",
        params={
            "path": "/search",
            "method": "post",
            "parameters": [{"name": "query", "in": "body", "schema": {"type": "string"}}],
        },
        max_output_bytes=100,
    )


async def test_bounded_success_and_saved_argument_mapping(monkeypatch):
    """AC-16: use actual OpenAPI parameter placement with the opt-in transport."""
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(200, text='{"results":[],"truncated":false}')

    impl = implementation()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "bisheng.tool.domain.services.bounded_openapi.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    assert await impl.arun(query="hello") == '{"results":[],"truncated":false}'
    assert requests[0].content == b'{"query":"hello"}'
    assert requests[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "status,headers,text,error",
    [
        (500, {}, "private upstream message", DshToolUpstreamFailedError),
        (302, {"Location": "https://fixture.example/api/v1/dsh/tools/x/invoke"}, "", DshToolUpstreamFailedError),
        (200, {"Content-Encoding": "br"}, "private", DshToolUpstreamFailedError),
        (200, {}, "x" * 101, DshToolOutputTooLargeError),
    ],
)
async def test_transport_failures_do_not_return_sensitive_text(monkeypatch, status, headers, text, error):
    """AC-19, AC-21, AC-28, AC-31: fail before converting errors into results."""
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "bisheng.tool.domain.services.bounded_openapi.httpx.AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, headers=headers, text=text)), **kwargs
        ),
    )
    with pytest.raises(error) as caught:
        await implementation().arun(query="hello")
    assert "private" not in str(caught.value)


async def test_http_library_logging_does_not_reveal_query_credentials(monkeypatch, caplog):
    """AC-21: httpx INFO logging must not expose saved query authentication."""
    import logging

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "bisheng.tool.domain.services.bounded_openapi.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="ok")), **kwargs),
    )
    impl = implementation()
    impl.api_key = "fixture-private-credential"
    impl.api_location = "query"
    impl.parameter_name = "credential"
    with caplog.at_level(logging.INFO, logger="httpx"):
        assert await impl.arun(query="private-query") == "ok"
        # The context filter must leave ordinary request logging enabled.
        logging.getLogger("httpx").info("unrelated request")
    assert "fixture-private-credential" not in caplog.text
    assert "private-query" not in caplog.text
    assert "fixture.example" not in caplog.text
    assert "unrelated request" in caplog.text


async def test_stream_cap_stops_consumption_and_closes(monkeypatch):
    """AC-28, AC-29: cap chunked responses before full buffering and close on exit."""

    class Stream(httpx.AsyncByteStream):
        reads = 0
        closed = False

        async def __aiter__(self):
            for _ in range(10):
                self.reads += 1
                yield b"x" * 60

        async def aclose(self):
            self.closed = True

    stream = Stream()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "bisheng.tool.domain.services.bounded_openapi.httpx.AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)), **kwargs
        ),
    )
    with pytest.raises(DshToolOutputTooLargeError):
        await implementation().arun(query="hello")
    assert stream.reads == 2 and stream.closed


async def test_number_arguments_keep_integer_precision(monkeypatch):
    """The legacy mapper coerced number fields to float; the bounded path sends them as-is."""
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(200, text="ok")

    impl = BoundedOpenApiTools(
        url="https://fixture.example",
        params={
            "path": "/search",
            "method": "get",
            "parameters": [{"name": "id", "in": "query", "schema": {"type": "number"}}],
        },
        max_output_bytes=100,
    )
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "bisheng.tool.domain.services.bounded_openapi.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    assert await impl.arun(id=9007199254740993) == "ok"
    assert requests[0].url.params["id"] == "9007199254740993"
