"""Only temporary tool tests and schema downloads use the safe transport."""

import pytest

from bisheng.tool.domain.services.test_openapi import TestOpenApiTools


async def test_temporary_tool_ignores_injected_unsafe_client():
    class UnsafeClient:
        async def aget(self, *_args, **_kwargs):
            pytest.fail("Test endpoint used unsafe transport")

    tool = TestOpenApiTools(
        url="http://127.0.0.1",
        params={"path": "/", "method": "get", "parameters": []},
        async_client=UnsafeClient(),
    )
    with pytest.raises(ValueError):
        await tool.arun()


async def test_malformed_parameters_do_not_escape_with_secrets(monkeypatch):
    from types import SimpleNamespace

    from bisheng_langchain.utils import safe_http

    monkeypatch.setattr(
        safe_http,
        "resolve_destination",
        lambda url: SimpleNamespace(hostname="fixture.example", port=80, ips=("127.0.0.1",), url=url),
    )
    with pytest.raises(safe_http.RequestFailed) as caught:
        await safe_http.arequest(
            "GET", "http://fixture.example/", params={"credential": {"api_key": "SECRET_SENTINEL"}}
        )
    assert "SECRET_SENTINEL" not in str(caught.value)


async def test_schema_download_blocks_loopback():
    from bisheng.api.utils import get_url_content

    with pytest.raises(ValueError):
        await get_url_content("http://127.0.0.1:1/")
