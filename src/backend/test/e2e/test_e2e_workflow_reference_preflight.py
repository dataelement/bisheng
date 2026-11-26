"""Read-only live preflight checks against an explicitly selected workflow.

Set E2E_WORKFLOW_ID, E2E_API_BASE, E2E_ADMIN_PASSWORD and E2E_MANAGEMENT_TENANT.
No resource is saved, created or deleted; only transient request graphs change.
"""

import copy
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token


@pytest.fixture
async def preflight_client():
    workflow_id = os.environ.get("E2E_WORKFLOW_ID")
    if not workflow_id:
        pytest.skip("set E2E_WORKFLOW_ID for the opt-in live read-only check")
    async with httpx.AsyncClient(timeout=30) as client:
        token = await get_admin_token(client)
        headers = {**auth_headers(token), "X-Management-Tenant": os.environ.get("E2E_MANAGEMENT_TENANT", "1")}
        saved = assert_resp_200(await client.get(f"{API_BASE}/flows/{workflow_id}", headers=headers))
        yield client, workflow_id, headers, saved
        after = assert_resp_200(await client.get(f"{API_BASE}/flows/{workflow_id}", headers=headers))
        assert after["data"] == saved["data"]
        assert after["update_time"] == saved["update_time"]


async def test_ac15_preflight_reports_every_repeated_invalid_selection_without_saving(preflight_client):
    """AC-15/16: every affected node is located, including unsaved repeated references."""
    client, workflow_id, headers, saved = preflight_client
    graph = copy.deepcopy(saved["data"])
    graph["nodes"] = [
        {
            "id": f"e2e-preflight-{i}",
            "data": {
                "id": f"e2e-preflight-{i}",
                "name": f"e2e-preflight-{i}",
                "type": "rag",
                "group_params": [
                    {
                        "params": [
                            {
                                "key": "knowledge",
                                "value": {
                                    "type": "space",
                                    "value": [{"key": 2147483647, "label": "e2e-preflight-missing"}],
                                },
                            }
                        ]
                    }
                ],
            },
        }
        for i in range(8)
    ]
    graph["edges"] = []
    result = assert_resp_200(
        await client.post(
            f"{API_BASE}/workflow/references/validate",
            headers=headers,
            json={"workflow_id": workflow_id, "data": graph},
        )
    )
    assert result["valid"] is False and len(result["errors"]) == 8
    assert {row["node_id"] for row in result["errors"]} == {f"e2e-preflight-{i}" for i in range(8)}
    assert all(
        row["target_id"] == "2147483647" and row["parameter_key"] == "knowledge" and row["state"] == "unavailable"
        for row in result["errors"]
    )


async def test_ac15_empty_unsaved_graph_passes_without_changing_saved_graph(preflight_client):
    """AC-15: preflight validates the submitted graph rather than the saved invalid graph."""
    client, workflow_id, headers, _ = preflight_client
    result = assert_resp_200(
        await client.post(
            f"{API_BASE}/workflow/references/validate",
            headers=headers,
            json={"workflow_id": workflow_id, "data": {"nodes": [], "edges": []}},
        )
    )
    assert result == {"valid": True, "errors": []}


async def test_ac17_preflight_requires_authentication(preflight_client):
    """AC-17: anonymous calls cannot inspect workflow references."""
    _, workflow_id, _, _ = preflight_client
    async with httpx.AsyncClient(timeout=15) as anonymous:
        response = await anonymous.post(
            f"{API_BASE}/workflow/references/validate",
            json={"workflow_id": workflow_id, "data": {"nodes": [], "edges": []}},
        )
    assert response.status_code == 401
    body = response.json()
    # Authentication dependency rejects with FastAPI's HTTP envelope before
    # the endpoint's business-response formatter is reached.
    assert body == {"detail": ""}
