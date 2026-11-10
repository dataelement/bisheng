"""Opt-in F113 smoke; only dedicated e2e-f113 owners and temporary accounts.

F113_E2E=1, E2E_API_BASE, E2E_ADMIN_TOKEN, F113_E2E_TENANT_A/B,
F113_E2E_OWNER_A/B and optional F113_E2E_RUN_ID (lowercase alphanumeric) are
required. Both owners must be dedicated e2e-f113 users in their named tenant.
The original admin scope is restored. Keys remain in process memory only.
No application, existing service account, membership or approval is modified.
Migration/reused-connection/publish-stage cases remain in the feature checklist.
"""

import os
import re
from dataclasses import dataclass, field

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers
from test.e2e.helpers.service_accounts import cleanup_service_accounts, select_service_account_tenant

pytestmark = pytest.mark.skipif(os.environ.get("F113_E2E") != "1", reason="requires deployed F113 and dedicated users")


@dataclass
class ManagementTarget:
    client: httpx.AsyncClient = field(repr=False)
    token: str = field(repr=False)
    tenant_a: int
    tenant_b: int
    owner_a: int
    owner_b: int
    prefix: str
    headers: dict = field(repr=False)


@pytest.fixture
async def management_target():
    token = os.environ["E2E_ADMIN_TOKEN"]
    tenant_a, tenant_b = (int(os.environ[f"F113_E2E_TENANT_{side}"]) for side in ("A", "B"))
    owner_a, owner_b = (int(os.environ[f"F113_E2E_OWNER_{side}"]) for side in ("A", "B"))
    run_id = os.environ.get("F113_E2E_RUN_ID", "smoke")
    assert re.fullmatch(r"[a-z0-9]{1,24}", run_id)
    assert tenant_a > 0 and tenant_b > 0 and tenant_a != tenant_b and owner_a != owner_b
    prefix = f"e2e-f113-{run_id}-"
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
        original = assert_resp_200(
            await client.get(
                f"{API_BASE}/service-accounts/management-scope",
                headers=auth_headers(token),
            )
        )
        try:
            for tenant, owner in ((tenant_a, owner_a), (tenant_b, owner_b)):
                headers = await select_service_account_tenant(client, token, tenant)
                candidates = assert_resp_200(
                    await client.get(
                        f"{API_BASE}/service-accounts/owner-candidates",
                        headers=headers,
                        params={"keyword": "e2e-f113-", "page": 1, "page_size": 100},
                    )
                )
                assert any(row["user_id"] == owner and row["tenant_id"] == tenant for row in candidates["data"])
            headers = await select_service_account_tenant(client, token, tenant_a)
            await cleanup_service_accounts(client, headers, tenant_id=tenant_a, owner_id=owner_a, prefix=prefix)
            yield ManagementTarget(client, token, tenant_a, tenant_b, owner_a, owner_b, prefix, headers)
        finally:
            try:
                headers = await select_service_account_tenant(client, token, tenant_a)
                await cleanup_service_accounts(client, headers, tenant_id=tenant_a, owner_id=owner_a, prefix=prefix)
            finally:
                assert_resp_200(
                    await client.post(
                        f"{API_BASE}/admin/tenant-scope",
                        headers=auth_headers(token),
                        json={"tenant_id": original["scope_tenant_id"]},
                    )
                )


async def test_scope_switch_rejects_every_old_confirmation_without_revoking_a_valid_key(management_target):
    """AC-01、AC-17、AC-18、AC-20、AC-21、AC-22、AC-23、AC-24、AC-26: real management and key calls."""
    target = management_target
    client, token, headers = target.client, target.token, target.headers
    tenant_a, tenant_b = target.tenant_a, target.tenant_b
    owner_a, owner_b, prefix = target.owner_a, target.owner_b, target.prefix
    root = f"{API_BASE}/service-accounts"
    created = assert_resp_200(
        await client.post(
            root,
            headers=headers,
            json={
                "name": prefix + "account",
                "resource_owner_user_id": owner_a,
            },
        )
    )
    account_id = created["id"]
    account_url = f"{root}/{account_id}"
    detail = assert_resp_200(await client.get(account_url, headers=headers))
    assert detail["tenant_id"] == tenant_a and detail["resource_owner"]["user_id"] == owner_a
    assert_resp_error(
        await client.post(
            root,
            headers=headers,
            json={
                "name": prefix + "wrong-owner",
                "resource_owner_user_id": owner_b,
            },
        ),
        26021,
    )
    issued = assert_resp_200(
        await client.post(f"{account_url}/keys", headers=headers, json={"name": prefix + "key", "scopes": []})
    )
    bearer = {"Authorization": "Bearer " + issued.pop("plaintext")}
    whoami = API_BASE.removesuffix("/api/v1") + "/api/v2/auth/whoami"
    identity = assert_resp_200(await client.get(whoami, headers=bearer))
    assert identity["tenant_id"] == tenant_a
    await select_service_account_tenant(client, token, tenant_b)
    # All confirmations retain A; none are transparently replayed in B.
    for method, url, body in (
        ("POST", root, {"name": prefix + "stale", "resource_owner_user_id": owner_a}),
        ("PATCH", account_url, {"name": prefix + "must-not-save"}),
        ("POST", account_url + "/enable", None),
        ("POST", account_url + "/disable", None),
        ("DELETE", account_url, None),
        ("POST", account_url + "/keys", {"name": prefix + "stale-key", "scopes": []}),
        ("PATCH", account_url + f"/keys/{issued['id']}", {"name": "must-not-save"}),
        ("POST", account_url + f"/keys/{issued['id']}/revoke", None),
        ("POST", account_url + "/keys/revoke-all", None),
        (
            "POST",
            account_url + "/resource-grants:mutate?resource_type=app&resource_id=e2e-f113-never",
            {
                "idempotency_key": prefix + "refused-grant",
                "expected_resource_version": 0,
                "expected_catalog_release_id": 1,
                "changes": [
                    {"op": "ADD", "model_key": "use", "subject": {"type": "service_account", "id": str(account_id)}}
                ],
            },
        ),
    ):
        assert_resp_error(await client.request(method, url, headers=headers, json=body), 26073)
    headers = await select_service_account_tenant(client, token, tenant_a)
    unchanged = assert_resp_200(await client.get(account_url, headers=headers))
    assert unchanged["name"] == detail["name"] and unchanged["status"] == detail["status"]
    assert unchanged["active_key_count"] == 1
    assert_resp_200(await client.get(whoami, headers=bearer))
