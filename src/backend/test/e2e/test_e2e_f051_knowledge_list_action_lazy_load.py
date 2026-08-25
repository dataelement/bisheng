"""Live E2E coverage for F051 knowledge-list action lazy loading.

Set ``F051_E2E=1`` only against a dedicated deployment containing the F051
backend and frontend build. This suite is read-only and creates no resources.
"""

from __future__ import annotations

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token

pytestmark = pytest.mark.skipif(
    os.environ.get("F051_E2E") != "1",
    reason="set F051_E2E=1 only against a dedicated F051 test deployment",
)


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=30.0) as value:
        yield value


@pytest.fixture(scope="module")
async def admin_token(client: httpx.AsyncClient) -> str:
    return await get_admin_token(client)


def _rows(payload: dict) -> list[dict]:
    rows = payload.get("data", [])
    assert isinstance(rows, list)
    return rows


class TestE2EF051KnowledgeListActionLazyLoad:
    """F051 list response minimization and single-resource action endpoint."""

    @pytest.mark.parametrize("knowledge_type", [0, 1])
    async def test_ac01_ac02_ac04_list_rows_only_include_visible(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        knowledge_type: int,
    ) -> None:
        """AC-01/02/04: document and QA list rows use the same minimal actions."""
        payload = assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge",
                params={"type": knowledge_type, "action": "visible", "page_size": 20},
                headers=auth_headers(admin_token),
            )
        )
        assert {"data", "page_size", "has_more", "next_cursor"} <= payload.keys()
        assert all(row.get("actions") == ["visible"] for row in _rows(payload))

    async def test_ac03_ac14_use_selector_keeps_minimal_response_shape(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-03/14: action=use still selects resources without action decoration."""
        payload = assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge",
                params={"type": 0, "action": "use", "page_size": 20},
                headers=auth_headers(admin_token),
            )
        )
        assert all(row.get("actions") == ["visible"] for row in _rows(payload))

    async def test_ac05_ac07_single_resource_endpoint_returns_current_actions(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-05/07: one visible row can load current actions independently."""
        headers = auth_headers(admin_token)
        payload = assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge",
                params={"type": 0, "action": "visible", "page_size": 1},
                headers=headers,
            )
        )
        rows = _rows(payload)
        if not rows:
            pytest.skip("dedicated deployment has no visible document knowledge base")

        actions = assert_resp_200(
            await client.get(
                f"{API_BASE}/permissions/resources/knowledge_library/{rows[0]['id']}/my-permissions",
                headers=headers,
            )
        )
        assert isinstance(actions.get("actions"), list)
        assert "visible" in actions["actions"]
        assert rows[0]["actions"] == ["visible"]
