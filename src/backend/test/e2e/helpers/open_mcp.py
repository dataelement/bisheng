"""Live Streamable HTTP helpers for F067 MCP E2E tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@asynccontextmanager
async def open_mcp_session(
    url: str,
    credential: str,
    *,
    on_behalf_of: str | None = None,
    end_user: str | None = None,
) -> AsyncIterator[ClientSession]:
    headers = {"Authorization": f"Bearer {credential}"}
    if on_behalf_of:
        headers["X-On-Behalf-Of"] = on_behalf_of
    if end_user:
        headers["X-End-User"] = end_user
    async with streamablehttp_client(url, headers=headers, timeout=60.0) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session


async def call_success(session: ClientSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    assert not result.isError, f"{name} failed: {result.content}"
    assert result.structuredContent is not None, f"{name} omitted structuredContent"
    return result.structuredContent


async def call_error(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
    *,
    expected_code: int | str,
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    assert result.isError, f"{name} unexpectedly succeeded"
    assert result.structuredContent is None, f"{name} returned structuredContent for an error"
    text_blocks = [item.text for item in result.content if getattr(item, "type", None) == "text"]
    assert len(text_blocks) == 1, f"{name} returned an invalid tool-error body"
    payload = json.loads(text_blocks[0])
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["message"]
    return payload


__all__ = ["call_error", "call_success", "open_mcp_session"]
