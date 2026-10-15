"""Read-only API acceptance against an explicitly prepared, isolated test tenant.

E2E_SUBJECT_ID_FIXTURE supplies IDs from the dedicated e2e-subject-id- dataset.
This suite does not create, edit or delete resources; no cleanup is necessary.
"""

import json
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token

_FIXTURE = os.environ.get("E2E_SUBJECT_ID_FIXTURE", "")
pytestmark = [pytest.mark.e2e, pytest.mark.skipif(not _FIXTURE, reason="Dedicated F076 API fixture not configured")]


@pytest.fixture()
def identities():
    data = json.loads(_FIXTURE)
    assert data["user_external_id"].startswith("e2e-subject-id-")
    assert data["department_external_id"].startswith("e2e-subject-id-")
    assert data["resource_name"].startswith("e2e-subject-id-")
    return data


@pytest.fixture()
async def api():
    async with httpx.AsyncClient(timeout=30) as client:
        token = await get_admin_token(client)
        yield client, auth_headers(token)


async def test_user_identity_exact_and_prefix(api, identities):
    """AC-01, AC-02, AC-03, AC-05: identity prefix and exact priority use stable IDs."""
    client, headers = api
    for query in (identities["user_external_id"], identities["user_external_id"][:-1]):
        response = await client.get(f"{API_BASE}/user/list", params={"name": query, "simple": True}, headers=headers)
        page = assert_resp_200(response)
        assert page["total"] >= 1
        assert any(row["user_id"] == identities["user_id"] for row in page["data"])
        if query == identities["user_external_id"]:
            assert page["data"][0]["external_id"] == query


async def test_resource_users_use_resource_scope(api, identities):
    """AC-16, AC-18, AC-21: current resource candidate API keeps stable identity."""
    client, headers = api
    path = f"{API_BASE}/permissions/resources/{identities['resource_type']}/{identities['resource_id']}/grant-subjects/users"
    page = assert_resp_200(await client.get(path, params={"keyword": identities["user_external_id"]}, headers=headers))
    assert any(row["user_id"] == identities["user_id"] for row in page["data"])
    assert "search_contract" not in page


async def test_resource_candidates_require_authentication(identities):
    """AC-16, AC-17: the same resource lookup refuses an unauthenticated caller."""
    path = f"{API_BASE}/permissions/resources/{identities['resource_type']}/{identities['resource_id']}/grant-subjects/users"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(path, params={"keyword": identities["user_external_id"]})
    body = response.json()
    assert body["status_code"] in (401, 403)
    assert "status_message" in body
    assert not body.get("data")


async def test_department_external_identity_in_tree(api, identities):
    """AC-04, AC-06, AC-07: department identity remains external_id in a tree."""
    client, headers = api
    path = f"{API_BASE}/permissions/resources/{identities['resource_type']}/{identities['resource_id']}/grant-subjects/departments/search"
    result = assert_resp_200(
        await client.get(path, params={"keyword": identities["department_external_id"]}, headers=headers)
    )
    pending = list(result["roots"])
    found = []
    while pending:
        node = pending.pop()
        if node["id"] == identities["department_id"]:
            found.append(node)
        pending.extend(node.get("children") or [])
    assert len(found) == 1
    assert found[0]["external_id"] == identities["department_external_id"]
