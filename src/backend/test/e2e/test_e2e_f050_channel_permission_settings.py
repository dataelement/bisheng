"""Live E2E coverage for F050 channel permission settings.

Set ``F050_E2E=1`` and ``F050_E2E_CHANNEL_SOURCE_ID`` only for a dedicated
deployment. Cleanup is restricted to the ``e2e-f050-channel-`` prefix.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token

PREFIX = "e2e-f050-channel-"
pytestmark = pytest.mark.skipif(
    os.environ.get("F050_E2E") != "1",
    reason="set F050_E2E=1 only against a dedicated F050 test deployment",
)


async def _cleanup(client: httpx.AsyncClient, token: str) -> None:
    response = await client.get(
        f"{API_BASE}/channel/manager/my_channels",
        params={"query_type": "created", "sort_by": "latest_update"},
        headers=auth_headers(token),
    )
    rows = assert_resp_200(response)
    for item in rows if isinstance(rows, list) else []:
        if str(item.get("name", "")).startswith(PREFIX):
            deleted = await client.delete(
                f"{API_BASE}/channel/manager/{item['id']}",
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


def _source_id() -> str:
    value = os.environ.get("F050_E2E_CHANNEL_SOURCE_ID", "").strip()
    if not value:
        pytest.fail("F050_E2E_CHANNEL_SOURCE_ID is required when F050_E2E=1")
    return value


class TestE2EF050ChannelPermissionSettings:
    """F050 channel creation, idempotency, and F048 truth."""

    async def test_ac02_ac12_creation_context_and_candidates(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-02/12: prospective context and candidates are tenant scoped."""
        headers = auth_headers(admin_token)
        context = assert_resp_200(
            await client.get(
                f"{API_BASE}/channel/manager/creation-permission-context",
                headers=headers,
            )
        )
        assert context["catalog_release_id"] > 0
        assert isinstance(context["can_configure_initial_permissions"], bool)
        groups = assert_resp_200(
            await client.get(
                f"{API_BASE}/channel/manager/creation-grant-subjects/user-groups",
                params={"page": 1, "page_size": 20},
                headers=headers,
            )
        )
        assert "data" in groups and "total" in groups

    async def test_ac15_ac18_ac20_ac30_ac32_create_and_read_owner(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-15/18/20/30/32: business fields persist with protected owner."""
        headers = auth_headers(admin_token)
        name = f"{PREFIX}{uuid4().hex[:10]}"
        payload = {
            "name": name,
            "source_list": [_source_id()],
            "visibility": "private",
            "filter_rules": [],
            "knowledge_sync": {"main": {"enabled": False, "spaces": []}, "subs": []},
        }
        created = assert_resp_200(
            await client.post(
                f"{API_BASE}/channel/manager/create",
                json=payload,
                headers=headers,
            )
        )
        channel_id = str(created["id"])
        detail = assert_resp_200(
            await client.get(
                f"{API_BASE}/channel/manager/{channel_id}",
                headers=headers,
            )
        )
        assert detail["name"] == name
        assert detail["source_list"] == payload["source_list"]

        roster = assert_resp_200(
            await client.get(
                f"{API_BASE}/permissions/resources/channel/{channel_id}/grants",
                params={"page_size": 100},
                headers=headers,
            )
        )["data"]
        assert any(item["protected"] and item["model"]["key"] == "owner" for item in roster)

    async def test_ac16_ac17_ac19_ac30_same_request_reuses_resource(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-16/17/19/30: same request resumes; changed payload is rejected."""
        headers = auth_headers(admin_token)
        request_id = f"e2e-f050-{uuid4().hex}"
        payload = {
            "name": f"{PREFIX}{uuid4().hex[:10]}",
            "source_list": [_source_id()],
            "visibility": "private",
            "filter_rules": [],
            "creation_request_id": request_id,
        }
        first = assert_resp_200(
            await client.post(
                f"{API_BASE}/channel/manager/create",
                json=payload,
                headers=headers,
            )
        )
        repeated = assert_resp_200(
            await client.post(
                f"{API_BASE}/channel/manager/create",
                json=payload,
                headers=headers,
            )
        )
        assert repeated["id"] == first["id"]
        conflict = await client.post(
            f"{API_BASE}/channel/manager/create",
            json={**payload, "description": "different"},
            headers=headers,
        )
        assert_resp_error(conflict, 19056)
