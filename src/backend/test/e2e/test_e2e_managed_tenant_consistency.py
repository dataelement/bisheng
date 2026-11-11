"""F009 dedicated-environment contract checks; existing fixtures are never modified.

Set E2E_F009_FIXTURES to JSON with fixture_prefix=e2e-f009-, home_tenant_id,
management_tenant_id, foreign_department_key, user_id. Supply ephemeral
E2E_ADMIN_TOKEN and E2E_F009_USER_TOKEN for dedicated e2e-f009-* identities.
Only the dedicated administrator's management scope changes and is restored.
"""

import json
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token

pytestmark = pytest.mark.e2e


@pytest.fixture
async def dedicated():
    raw = os.environ.get("E2E_F009_FIXTURES")
    if not raw or not os.environ.get("E2E_ADMIN_TOKEN") or not os.environ.get("E2E_F009_USER_TOKEN"):
        pytest.skip("Dedicated F009 environment, prefixed fixtures and ephemeral tokens are required")
    facts = json.loads(raw)
    assert facts["fixture_prefix"] == "e2e-f009-"
    assert facts["foreign_department_key"].startswith("e2e-f009-")
    assert facts["home_tenant_id"] != facts["management_tenant_id"]
    async with httpx.AsyncClient(timeout=30) as client:
        admin = auth_headers(await get_admin_token(client))
        user = auth_headers(os.environ["E2E_F009_USER_TOKEN"])
        for headers in (admin, user):
            identity = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
            assert identity["user_name"].startswith("e2e-f009-")
        before = assert_resp_200(await client.get(f"{API_BASE}/admin/tenant-scope", headers=admin))
        try:
            assert_resp_200(
                await client.post(
                    f"{API_BASE}/admin/tenant-scope", headers=admin, json={"tenant_id": facts["home_tenant_id"]}
                )
            )
            yield client, admin, user, facts
        finally:
            assert_resp_200(
                await client.post(
                    f"{API_BASE}/admin/tenant-scope", headers=admin, json={"tenant_id": before["scope_tenant_id"]}
                )
            )


async def test_management_scope_does_not_change_own_policy(dedicated):
    """AC-15/16/20/38: M changes administration, while home menu and budget remain H."""
    client, admin, _user, facts = dedicated
    own_before = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=admin))
    quota_before = assert_resp_200(await client.get(f"{API_BASE}/quota/effective", headers=admin))
    assert_resp_200(
        await client.post(
            f"{API_BASE}/admin/tenant-scope", headers=admin, json={"tenant_id": facts["management_tenant_id"]}
        )
    )
    own_after = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=admin))
    quota_after = assert_resp_200(await client.get(f"{API_BASE}/quota/effective", headers=admin))
    assert own_before["leaf_tenant_id"] == own_after["leaf_tenant_id"]
    assert set(own_before["web_menu"]) == set(own_after["web_menu"])
    assert own_before["role"] == own_after["role"]
    assert quota_before == quota_after


async def test_foreign_affiliation_form_has_no_policy_binding(dedicated):
    """AC-04/05/07: foreign membership shows organization facts and no local policy grant."""
    client, admin, _user, facts = dedicated
    key = facts["foreign_department_key"]
    form = assert_resp_200(
        await client.get(f"{API_BASE}/departments/{key}/members/{facts['user_id']}/edit-form", headers=admin)
    )
    assert form["policy_editable"] is False
    assert form["role_apply_status"] == "NOT_APPLICABLE_CROSS_TENANT"
    assert form["context_role_ids"] == []
    assert form["assignable_roles_catalog"][key] == []


async def test_management_identity_is_not_granted_to_an_ordinary_user(dedicated):
    """AC-37/38: ordinary-user identity cannot read the administration scope API."""
    client, _admin, user, _facts = dedicated
    response = await client.get(f"{API_BASE}/admin/tenant-scope", headers=user)
    body = response.json()
    assert {"status_code", "status_message", "data"}.issubset(body)
    assert response.status_code == 403
    assert body["status_code"] == 19701
