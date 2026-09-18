"""Live F067 smoke coverage for the ten-tool S-mode path plus S/D/PAT policy.

Run only against a dedicated MySQL + Redis + OpenFGA deployment::

    F067_E2E=1 \
    F067_E2E_MCP_URLS=https://backend.example/api/v2/mcp,https://gateway.example/api/v2/mcp \
    F067_E2E_API_KEY=... \
    F067_E2E_PAT=... \
    F067_E2E_DELEGATED_USER=... \
    F067_E2E_EMBEDDING_MODEL=... \
    F067_E2E_FILE_URL=https://files.example/e2e.txt \
    F067_E2E_OVERSIZE_BODY_BYTES=2097152 \
    uv run pytest test/e2e/test_e2e_f067_open_mcp.py -m e2e

The suite prefixes every resource with ``e2e-f067-open-mcp-`` and deletes the
created knowledge resource in ``finally``. Do not enable it against production.
"""

from __future__ import annotations

import base64
import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.open_mcp import call_error, call_success, open_mcp_session

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("F067_E2E") != "1",
        reason="set F067_E2E=1 only against a dedicated F067 test deployment",
    ),
]

EXPECTED_TOOLS = {
    "bisheng_knowledge_list",
    "bisheng_knowledge_create",
    "bisheng_knowledge_update",
    "bisheng_knowledge_delete",
    "bisheng_knowledge_clear",
    "bisheng_knowledge_retrieve",
    "bisheng_knowledge_file_upload",
    "bisheng_knowledge_file_list",
    "bisheng_knowledge_file_delete",
    "bisheng_knowledge_files_delete",
}


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required when F067_E2E=1")
    return value


def _urls() -> list[str]:
    return [item.strip().rstrip("/") for item in _required("F067_E2E_MCP_URLS").split(",") if item.strip()]


@pytest.mark.asyncio
@pytest.mark.parametrize("mcp_url", _urls() if os.environ.get("F067_E2E") == "1" else ["disabled"])
async def test_s_mode_calls_all_ten_tools_over_streamable_http(mcp_url: str):
    """AC-01/04/07/21: S mode discovers and successfully calls the fixed ten tools."""
    credential = _required("F067_E2E_API_KEY")
    model = _required("F067_E2E_EMBEDDING_MODEL")
    file_url = _required("F067_E2E_FILE_URL")
    name = f"e2e-f067-open-mcp-{uuid4().hex[:12]}"
    knowledge_id: int | None = None

    async with open_mcp_session(mcp_url, credential) as session:
        listed = await session.list_tools()
        assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS
        await call_success(session, "bisheng_knowledge_list", {"type": 0, "page_size": 1})
        try:
            created = await call_success(
                session,
                "bisheng_knowledge_create",
                {"name": name, "type": 0, "model": model},
            )
            knowledge_id = int(created["id"])
            await call_success(
                session,
                "bisheng_knowledge_update",
                {"knowledge_id": knowledge_id, "description": "F067 E2E"},
            )
            await call_success(
                session,
                "bisheng_knowledge_retrieve",
                {"query": "empty", "knowledge_base_ids": [knowledge_id], "top_k": 1},
            )

            uploaded_ids = []
            for index in range(3):
                payload = base64.b64encode(f"F067 E2E {uuid4().hex} {index}".encode()).decode()
                uploaded = await call_success(
                    session,
                    "bisheng_knowledge_file_upload",
                    {
                        "knowledge_id": knowledge_id,
                        "file_name": f"{name}-{index}.txt",
                        "content_base64": payload,
                    },
                )
                uploaded_ids.append(int(uploaded["id"]))
            uploaded = await call_success(
                session,
                "bisheng_knowledge_file_upload",
                {"knowledge_id": knowledge_id, "file_url": file_url},
            )
            uploaded_ids.append(int(uploaded["id"]))

            files = await call_success(
                session,
                "bisheng_knowledge_file_list",
                {"knowledge_id": knowledge_id, "page_size": 20},
            )
            assert {item["id"] for item in files["data"]} >= set(uploaded_ids)
            await call_success(
                session,
                "bisheng_knowledge_file_delete",
                {"file_id": uploaded_ids[0]},
            )
            await call_success(
                session,
                "bisheng_knowledge_files_delete",
                {"file_ids": uploaded_ids[1:]},
            )
            await call_success(
                session,
                "bisheng_knowledge_clear",
                {"knowledge_id": knowledge_id},
            )
        finally:
            if knowledge_id is not None:
                await call_success(
                    session,
                    "bisheng_knowledge_delete",
                    {"knowledge_id": knowledge_id},
                )


@pytest.mark.asyncio
async def test_pat_discovers_only_three_read_tools_when_configured():
    """AC-12/13/18: PAT can execute reads and cannot call a hidden write tool."""
    pat = _required("F067_E2E_PAT")
    async with open_mcp_session(_urls()[0], pat) as session:
        listed = await session.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "bisheng_knowledge_list",
            "bisheng_knowledge_retrieve",
            "bisheng_knowledge_file_list",
        }
        await call_success(session, "bisheng_knowledge_list", {"type": 0, "page_size": 1})
        await call_error(
            session,
            "bisheng_knowledge_create",
            {"name": "must-not-create", "type": 0, "model": "unused"},
            expected_code="PERMISSION_DENIED",
        )


@pytest.mark.asyncio
async def test_delegated_mode_forwards_subject_and_executes_read():
    """AC-10/11/15: D mode discovers the allowlist and executes as the configured subject."""
    credential = _required("F067_E2E_API_KEY")
    delegated_user = _required("F067_E2E_DELEGATED_USER")
    async with open_mcp_session(_urls()[0], credential, on_behalf_of=delegated_user) as session:
        listed = await session.list_tools()
        assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS
        await call_success(session, "bisheng_knowledge_list", {"type": 0, "page_size": 1})


@pytest.mark.asyncio
@pytest.mark.parametrize("mcp_url", _urls() if os.environ.get("F067_E2E") == "1" else ["disabled"])
async def test_transport_rejects_oversize_body_for_direct_and_gateway_urls(mcp_url: str):
    """AC-21/22: backend and gateway both reject oversized MCP bodies with HTTP 413."""
    credential = _required("F067_E2E_API_KEY")
    body_size = int(_required("F067_E2E_OVERSIZE_BODY_BYTES"))
    assert 1024 <= body_size <= 10 * 1024 * 1024, "use a bounded body and lower the dedicated test limit"
    headers = {
        "Authorization": f"Bearer {credential}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(mcp_url, headers=headers, content=b" " * body_size)
    assert response.status_code == 413
