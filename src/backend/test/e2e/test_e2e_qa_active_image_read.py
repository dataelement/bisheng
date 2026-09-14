"""E2E tests for F061: QA active image read.

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE)
- Default admin account; password via E2E_ADMIN_PASSWORD or helper default

This feature adds no HTTP API, table, or error-code module. Pixel fetch is
an in-process tool on existing chat SSE paths. Live vision + MinIO + browser
SSE is the manual checklist (e2e-checklist.md). These tests only lock the
HTTP contract that *can* be asserted without a visual model.

Covers (API behavior):
- AC-05 / AC-14: no public view_image / arbitrary-URL fetch route
- AC-14: the three existing chat entries still require login
- AC-14: authenticated channel chat with a missing article still uses the
  existing ArticleNotFoundError (19040), not a new fetch API

Skipped here (unit tests under test/common, test/knowledge, test/channel,
test/workstation):
- AC-01..AC-09, AC-13, AC-15, AC-16, AC-19, AC-20 (annotate / tool / loop)

Skipped here (UI + real vision model, see e2e-checklist.md):
- AC-10, AC-11, AC-12, AC-17, AC-18
"""

from __future__ import annotations

import httpx
import pytest

from test.e2e.helpers.api import API_BASE
from test.e2e.helpers.auth import auth_headers, get_admin_token

PREFIX = "e2e-f061-"
GHOST_ARTICLE_ID = f"{PREFIX}ghost-article-doc"
GHOST_SPACE_ID = 99999991
GHOST_FILE_ID = 99999992

_CHAT_BODIES = (
    (
        "POST",
        "/workstation/chat/completions",
        {
            "clientTimestamp": "0",
            "model": "unused",
            "text": f"{PREFIX}no-image-question",
        },
    ),
    (
        "POST",
        f"/knowledge/space/{GHOST_SPACE_ID}/chat/file/{GHOST_FILE_ID}",
        {"query": f"{PREFIX}no-image-question", "modelId": 1},
    ),
    (
        "POST",
        f"/knowledge/space/{GHOST_SPACE_ID}/chat/folder",
        {
            "query": f"{PREFIX}no-image-question",
            "modelId": 1,
            "folder_id": 0,
            "chat_id": f"{PREFIX}ghost-chat",
        },
    ),
    (
        "POST",
        "/channel/chat/completions",
        {
            "article_doc_id": GHOST_ARTICLE_ID,
            "text": f"{PREFIX}no-image-question",
            "modelId": 1,
        },
    ),
)


def _assert_auth_rejected(resp: httpx.Response) -> None:
    if resp.status_code != 200:
        assert resp.status_code in (401, 403), resp.text[:200]
        return
    body = resp.json()
    assert body.get("status_code") in (401, 403), body


class TestE2EQaActiveImageRead:
    """E2E: F061 QA active image read — HTTP contract only."""

    @pytest.fixture
    async def client(self):
        try:
            async with httpx.AsyncClient(base_url=API_BASE, timeout=15.0) as client:
                probe = await client.get("/user/public_key")
                if probe.status_code >= 500:
                    pytest.skip("backend not healthy")
                yield client
        except httpx.ConnectError:
            pytest.skip("backend not running on E2E_API_BASE")

    @pytest.fixture
    async def admin_token(self, client):
        try:
            return await get_admin_token(client)
        except AssertionError as exc:
            pytest.skip(f"admin login unavailable (captcha / password): {exc}")

    @pytest.mark.parametrize("method,path,payload", _CHAT_BODIES)
    async def test_ac14_unauthenticated_chat_blocked(self, client, method, path, payload):
        """AC-14: no token on existing chat entries → rejected (no anonymous fetch)."""
        resp = await client.request(method, path, json=payload)
        _assert_auth_rejected(resp)

    async def test_ac14_unauthenticated_space_history_blocked(self, client):
        """AC-14: knowledge-space chat history stays behind login."""
        resp = await client.get(
            f"/knowledge/space/{GHOST_SPACE_ID}/chat/file/{GHOST_FILE_ID}/history",
        )
        _assert_auth_rejected(resp)

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/view_image"),
            ("POST", "/view_image"),
            ("GET", "/image_view"),
            ("POST", "/image_view"),
            ("GET", "/common/image_view"),
            ("POST", "/common/image_view"),
        ],
    )
    async def test_ac05_ac14_no_public_image_fetch_route(self, client, method, path):
        """AC-05 / AC-14: no dedicated HTTP API that accepts a URL and returns pixels."""
        resp = await client.request(method, path, json={"url": "https://example.invalid/x.png"})
        assert resp.status_code == 404, resp.text[:200]

    async def test_ac14_channel_missing_article_uses_existing_error(self, client, admin_token):
        """AC-14: logged-in channel chat with unknown article → 19040, not a new fetch API."""
        resp = await client.post(
            "/channel/chat/completions",
            json={
                "article_doc_id": GHOST_ARTICLE_ID,
                "text": f"{PREFIX}what-is-the-trend",
                "modelId": 1,
            },
            headers=auth_headers(admin_token),
        )
        body_text = resp.text
        assert "19040" in body_text or (
            resp.headers.get("content-type", "").startswith("application/json")
            and resp.json().get("status_code") == 19040
        ), body_text[:400]
