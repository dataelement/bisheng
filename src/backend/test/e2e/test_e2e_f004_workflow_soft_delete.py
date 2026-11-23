"""Opt-in deployed API checks for v3.1.0-beta1 F004.

Set F004_E2E=1, E2E_API_BASE, F004_USER_TOKEN (non-admin creator),
F004_OTHER_TOKEN (same tenant, no grant), F004_FOREIGN_TOKEN (other tenant).
Only uniquely prefixed workflows created by this test are deleted. SQL retention
and version atomicity are covered by test/workflow/test_flow_soft_delete.py.
"""

import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = pytest.mark.skipif(
    os.environ.get("F004_E2E") != "1",
    reason="requires deployed F004 and dedicated non-admin tenant accounts",
)


async def test_deleted_workflow_cannot_be_reopened_and_name_is_reusable():
    """AC-02/AC-03/AC-06/AC-08/AC-11: normal user, foreign user, delete and recreate."""
    headers = auth_headers(os.environ["F004_USER_TOKEN"])
    others = [auth_headers(os.environ[key]) for key in ("F004_OTHER_TOKEN", "F004_FOREIGN_TOKEN")]
    prefix = f"e2e-f004-{uuid4().hex[:12]}"
    payload = {"name": prefix, "description": "F004 isolated test", "data": {"nodes": [], "edges": []}}
    created = []
    deleted = set()
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            first_response = await client.post(f"{API_BASE}/workflow/create", headers=headers, json=payload)
            assert first_response.status_code == 201
            assert first_response.json()["status_code"] == 200
            first = first_response.json()["data"]
            created.append(first["id"])
            assert_resp_200(await client.get(f"{API_BASE}/flows/{first['id']}", headers=headers))
            for denied in others:
                # No existing grant: cross-tenant target is hidden, same-tenant action is denied.
                response = await client.delete(f"{API_BASE}/flows/{first['id']}", headers=denied)
                expected = 404 if denied is others[1] else 19000
                assert_resp_error(response, expected)
            assert_resp_200(await client.delete(f"{API_BASE}/flows/{first['id']}", headers=headers))
            deleted.add(first["id"])
            assert_resp_error(await client.get(f"{API_BASE}/flows/{first['id']}", headers=headers), 404)
            assert_resp_error(await client.delete(f"{API_BASE}/flows/{first['id']}", headers=headers), 404)
            listed = assert_resp_200(
                await client.get(
                    f"{API_BASE}/workflow/list",
                    headers=headers,
                    params={"name": prefix, "flow_type": 10, "managed": True},
                )
            )
            assert first["id"] not in {row["id"] for row in listed["data"]}
            second_response = await client.post(f"{API_BASE}/workflow/create", headers=headers, json=payload)
            assert second_response.status_code == 201
            assert second_response.json()["status_code"] == 200
            second = second_response.json()["data"]
            created.append(second["id"])
            assert second["id"] != first["id"]
            assert_resp_200(await client.get(f"{API_BASE}/flows/{second['id']}", headers=headers))
        finally:
            for workflow_id in created:
                if workflow_id not in deleted:
                    assert_resp_200(await client.delete(f"{API_BASE}/flows/{workflow_id}", headers=headers))
