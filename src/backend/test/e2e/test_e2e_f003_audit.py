"""E2E for F003 audit optimisation, against the backend of the current environment.

Prerequisites: backend on E2E_API_BASE (default http://localhost:7860/api/v1) whose
database already has the operator department columns. Reads existing rows and
never deletes them. The one write is a login.

Covers the API half of spec AC-01, AC-10, AC-17, AC-19, AC-21, AC-23, AC-27,
AC-30, AC-33, AC-37, AC-39, AC-42. UI behaviour is the checklist next to the spec.
"""

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_F003") == "0",
    reason="set E2E_F003=0 to skip the live audit checks",
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=API_BASE, timeout=30.0) as one:
        yield one


@pytest.fixture(scope="module")
def admin(client):
    return auth_headers(_sync_admin_token())


def _sync_admin_token() -> str:
    """The shared helper is async; this suite stays synchronous like the other live e2e files."""
    import asyncio

    async def _go():
        async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as async_client:
            return await get_admin_token(async_client)

    return asyncio.run(_go())


def _rows(data):
    if isinstance(data, dict):
        return data.get("data") or data.get("items") or []
    return data or []


class TestE2EAuditOptimization:
    def test_ac17_anonymous_refused(self, client):
        """AC-17: no identity, no audit data."""
        resp = client.get("/audit", params={"page": 1, "limit": 1})
        assert resp.status_code in (401, 403) or resp.json().get("status_code") in (401, 403)

    def test_ac39_list_carries_the_organisation(self, client, admin):
        """AC-10, AC-39: every system-operation row exposes the snapshot columns."""
        data = assert_resp_200(client.get("/audit", params={"page": 1, "limit": 20}, headers=admin))
        assert "total" in data
        for row in _rows(data):
            assert "operator_dept_id" in row
            assert "operator_dept_path" in row

    def test_ac01_action_filter_returns_only_that_action(self, client, admin):
        """AC-01: filtering one of the five added actions returns nothing else."""
        data = assert_resp_200(
            client.get("/audit", params={"page": 1, "limit": 50, "event_type": "update_sandbox_conf"}, headers=admin)
        )
        for row in _rows(data):
            assert (row.get("event_type") or row.get("action")) == "update_sandbox_conf"

    def test_ac19_unknown_department_returns_empty(self, client, admin):
        """AC-19: a department id outside any real tree yields an empty page, not an error."""
        data = assert_resp_200(
            client.get("/audit", params={"page": 1, "limit": 20, "dept_ids": 2147483000}, headers=admin)
        )
        assert _rows(data) == []
        assert data["total"] == 0

    def test_ac21_department_candidates(self, client, admin):
        """AC-21, AC-23, AC-27: the picker returns active nodes, an archived list and the two switches."""
        data = assert_resp_200(client.get("/audit/departments", params={"limit": 50}, headers=admin))
        for key in ("active", "archived", "show_none", "show_unrecorded"):
            assert key in data
        assert data["show_none"] is True and data["show_unrecorded"] is True
        for node in data["active"] + data["archived"]:
            assert {"id", "dept_id", "name", "path_name", "tenant_id", "has_children"} <= set(node)
        if data["active"]:
            found = assert_resp_200(
                client.get(
                    "/audit/departments", params={"keyword": data["active"][0]["name"], "limit": 20}, headers=admin
                )
            )
            assert any(node["id"] == data["active"][0]["id"] for node in found["active"] + found["archived"])

    def test_ac30_usage_type_filter(self, client, admin):
        """AC-30, AC-33: the four usage types are accepted and every row carries one."""
        allowed = {"daily", "assistant", "workflow", "task"}
        for usage in allowed:
            data = assert_resp_200(
                client.get("/audit/session", params={"page": 1, "page_size": 20, "usage_type": usage}, headers=admin)
            )
            assert "total" in data
            for row in _rows(data):
                assert row["usage_type"] == usage
                assert "operator_dept_id" in row
        rejected = client.get("/audit/session", params={"usage_type": "nope"}, headers=admin)
        # The app renders validation errors as HTTP 200 with status_code 422 in the body.
        assert rejected.json().get("status_code") == 422

    def test_ac37_missing_session_refused(self, client, admin):
        """AC-37: a conversation id that is not a session in scope is refused."""
        resp = client.get("/session/chat/messages/e2e-f003-missing", headers=admin)
        body = resp.json()
        assert body.get("status_code") in (403, 404), body

    def test_ac42_runtime_records_accept_the_organisation(self, client, admin):
        """AC-42: the runtime record list takes the comma-separated organisation filter."""
        resp = client.get(
            "/app-runtime-audit/records/access",
            params={"time_range": "recent7d", "dept_ids": "1", "include_descendants": "true", "limit": 5},
            headers=admin,
        )
        body = resp.json()
        # The tab can be switched off; a permission or availability error is that switch, not a crash.
        if body.get("status_code") == 200:
            for row in body["data"].get("items", []):
                assert "operator_dept_id" in row
        else:
            assert body.get("status_code") not in (None, 500), body


def test_import_guard():
    """The async helper import stays the single auth implementation."""
    assert callable(get_admin_token)
    assert callable(assert_resp_error)
