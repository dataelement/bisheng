"""Live read-only HTTP checks; real parsing/browser checks are in the proposal checklist."""

import httpx
import pytest

from test.e2e.helpers.api import API_BASE
from test.e2e.helpers.auth import auth_headers, get_admin_token

PREFIX = "e2e-workflow-images-"


@pytest.fixture
async def live_client():
    async with httpx.AsyncClient(base_url=API_BASE, timeout=10, follow_redirects=False) as client:
        try:
            await client.get("/env")
        except httpx.RequestError:
            pytest.skip("live backend is unavailable; local HTTP integration is tested separately")
        yield client


async def test_anonymous_image_content_does_not_issue_a_signed_url(live_client):
    """AC-07: a raw Markdown img request still requires login."""
    response = await live_client.get(f"/chat/{PREFIX}missing/files/missing/content")
    assert "location" not in response.headers
    if response.status_code == 200:
        assert response.json()["status_code"] in (401, 403)
    else:
        assert response.status_code in (401, 403)


async def test_unknown_conversation_does_not_issue_a_signed_url(live_client):
    """AC-07: even an administrator cannot resolve an unknown conversation's image."""
    token = await get_admin_token(live_client)
    response = await live_client.get(
        f"/chat/{PREFIX}missing/files/missing/content",
        headers=auth_headers(token),
    )
    assert "location" not in response.headers
    if response.status_code == 200:
        assert response.json()["status_code"] == 404
    else:
        assert response.status_code == 404
