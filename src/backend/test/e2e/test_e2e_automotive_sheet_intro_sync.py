"""
E2E tests for F049: Automotive Sheet Intro Sync

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE env var)
- Admin account with tenant-admin scope for automotive sync API

Covers (API layer):
- AC-01: Config GET defaults + PUT/GET round-trip (disabled)
- AC-02: POST /test rejected when enabled=false (19907)
- AC-07: GET /runs pagination shape
"""

from __future__ import annotations

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token

BASE_PATH = "/admin/developer-tokens/automotive-sheet-intro-sync"


def _disabled_config() -> dict:
    return {
        "enabled": False,
        "api_url": None,
        "api_method": "GET",
        "api_timeout_seconds": 120,
        "developer_token_id": None,
        "file_name": "汽车板介绍.pdf",
        "external_file_id": "automotive_sheet_intro",
    }


@pytest.mark.skipif(
    os.environ.get("E2E_SKIP", "0") == "1",
    reason="E2E tests skipped (E2E_SKIP=1)",
)
class TestE2EAutomotiveSheetIntroSync:
    """E2E: F049 automotive sheet intro sync admin API."""

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
            yield client

    @pytest.fixture
    async def admin_headers(self, client):
        token = await get_admin_token(client)
        return auth_headers(token)

    async def test_ac01_config_get_defaults(self, client, admin_headers):
        """AC-01: GET returns default config when unset."""
        resp = await client.get(BASE_PATH, headers=admin_headers)
        data = assert_resp_200(resp)
        assert data["enabled"] is False
        assert data["file_name"] == "汽车板介绍.pdf"
        assert data["external_file_id"] == "automotive_sheet_intro"
        assert data["api_method"] == "GET"

    async def test_ac01_config_put_disabled_round_trip(self, client, admin_headers):
        """AC-01: PUT disabled config then GET returns same fields."""
        payload = _disabled_config()
        payload["api_url"] = "https://example.com/placeholder.pdf"

        put_resp = await client.put(BASE_PATH, json=payload, headers=admin_headers)
        saved = assert_resp_200(put_resp)
        assert saved["enabled"] is False
        assert saved["api_url"] == "https://example.com/placeholder.pdf"

        get_resp = await client.get(BASE_PATH, headers=admin_headers)
        loaded = assert_resp_200(get_resp)
        assert loaded["enabled"] is saved["enabled"]
        assert loaded["api_url"] == saved["api_url"]
        assert loaded["file_name"] == saved["file_name"]

    async def test_ac02_test_sync_rejected_when_disabled(self, client, admin_headers):
        """AC-02: POST /test when enabled=false → business error 19907."""
        await client.put(BASE_PATH, json=_disabled_config(), headers=admin_headers)
        resp = await client.post(f"{BASE_PATH}/test", headers=admin_headers)
        assert resp.status_code == 403
        body = resp.json()
        assert body["status_code"] == 403
        assert body.get("data", {}).get("error_code") == 19907

    async def test_ac07_list_runs_pagination(self, client, admin_headers):
        """AC-07: GET /runs returns PageData shape."""
        resp = await client.get(
            f"{BASE_PATH}/runs",
            params={"page": 1, "limit": 10},
            headers=admin_headers,
        )
        data = assert_resp_200(resp)
        assert "data" in data
        assert "total" in data
        assert isinstance(data["data"], list)
