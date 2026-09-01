"""Live E2E coverage for F050 knowledge-space permission settings.

Set ``F050_E2E=1`` only for a dedicated test deployment. The suite creates and
deletes resources whose names start with ``e2e-f050-knowledge-``.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token

PREFIX = "e2e-f050-knowledge-"
pytestmark = pytest.mark.skipif(
    os.environ.get("F050_E2E") != "1",
    reason="set F050_E2E=1 only against a dedicated F050 test deployment",
)


async def _cleanup(client: httpx.AsyncClient, token: str) -> None:
    response = await client.get(
        f"{API_BASE}/knowledge/space/list",
        params={"page": 1, "page_size": 200},
        headers=auth_headers(token),
    )
    payload = assert_resp_200(response)
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    for item in rows if isinstance(rows, list) else []:
        if str(item.get("name", "")).startswith(PREFIX):
            deleted = await client.delete(
                f"{API_BASE}/knowledge/space/{item['id']}",
                headers=auth_headers(token),
            )
            assert_resp_200(deleted)


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=30.0) as value:
        yield value


@pytest.fixture(scope="module")
async def admin_token(client: httpx.AsyncClient) -> str:
    return await get_admin_token(client)


@pytest.fixture(scope="module", autouse=True)
async def prefix_cleanup(client: httpx.AsyncClient, admin_token: str):
    await _cleanup(client, admin_token)
    yield
    await _cleanup(client, admin_token)


class TestE2EF050KnowledgePermissionSettings:
    """F050 knowledge-space creation, idempotency, and F048 truth."""

    async def test_ac01_ac12_creation_context_and_candidates(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-01/12: prospective context and candidates are tenant scoped."""
        headers = auth_headers(admin_token)
        context = assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge/space/creation-permission-context",
                headers=headers,
            )
        )
        assert context["catalog_release_id"] > 0
        assert isinstance(context["can_configure_initial_permissions"], bool)
        assert all(model["active"] for model in context["grantable_models"])

        users = assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge/space/creation-grant-subjects/users",
                params={"page": 1, "page_size": 20},
                headers=headers,
            )
        )
        assert "data" in users and "total" in users

    async def test_ac15_ac18_ac20_ac30_create_and_read_f048_owner(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-15/18/20/30: legacy create persists and exposes protected owner."""
        headers = auth_headers(admin_token)
        name = f"{PREFIX}{uuid4().hex[:10]}"
        created = assert_resp_200(
            await client.post(
                f"{API_BASE}/knowledge/space",
                json={"name": name, "auth_type": "private", "auto_tag_enabled": False},
                headers=headers,
            )
        )
        space_id = str(created["id"])
        info = assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}",
                headers=headers,
            )
        )
        assert info["name"] == name

        context = assert_resp_200(
            await client.get(
                f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/context",
                headers=headers,
            )
        )
        roster = assert_resp_200(
            await client.get(
                f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/grants",
                params={"page_size": 100},
                headers=headers,
            )
        )["data"]
        assert context["mode"] == "CUSTOM"
        assert any(item["protected"] and item["model"]["key"] == "owner" for item in roster)

    async def test_ac16_ac17_ac19_ac30_same_request_reuses_resource(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-16/17/19/30: same request resumes; changed payload is rejected."""
        headers = auth_headers(admin_token)
        request_id = f"e2e-f050-{uuid4().hex}"
        name = f"{PREFIX}{uuid4().hex[:10]}"
        payload = {
            "name": name,
            "auth_type": "private",
            "creation_request_id": request_id,
        }
        first = assert_resp_200(
            await client.post(
                f"{API_BASE}/knowledge/space",
                json=payload,
                headers=headers,
            )
        )
        repeated = assert_resp_200(
            await client.post(
                f"{API_BASE}/knowledge/space",
                json=payload,
                headers=headers,
            )
        )
        assert repeated["id"] == first["id"]

        conflict = await client.post(
            f"{API_BASE}/knowledge/space",
            json={**payload, "description": "different"},
            headers=headers,
        )
        assert_resp_error(conflict, 18072)
