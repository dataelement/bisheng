"""Scoped service-account setup/cleanup for dedicated E2E identities."""

import re

import httpx

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers


async def select_service_account_tenant(client: httpx.AsyncClient, token: str, tenant_id: int) -> dict:
    assert tenant_id > 0
    result = assert_resp_200(
        await client.put(
            f"{API_BASE}/service-accounts/management-scope",
            headers=auth_headers(token),
            json={"tenant_id": tenant_id},
        )
    )
    assert result["scope_tenant_id"] == tenant_id
    return {**auth_headers(token), "X-Service-Account-Tenant": str(tenant_id)}


async def cleanup_service_accounts(
    client: httpx.AsyncClient,
    headers: dict,
    *,
    tenant_id: int,
    owner_id: int,
    prefix: str,
) -> None:
    """Only exact tenant/owner/prefix matches; cleanup failures remain visible."""
    assert re.fullmatch(r"e2e-f113-[a-z0-9-]+-", prefix)
    matches = []
    consumed = 0
    for page in range(1, 101):
        result = assert_resp_200(
            await client.get(
                f"{API_BASE}/service-accounts",
                headers=headers,
                params={"keyword": prefix, "page": page, "page_size": 100},
            )
        )
        rows = result["data"]
        for row in rows:
            if row["name"].startswith(prefix):
                assert row["tenant_id"] == tenant_id and row["resource_owner"]["user_id"] == owner_id
                matches.append(row["id"])
        consumed += len(rows)
        if consumed >= result["total"]:
            break
        assert rows, "Incomplete service account cleanup pagination"
    else:
        raise AssertionError("Service account cleanup exceeded its bounded page count")
    for account_id in matches:
        assert_resp_200(await client.delete(f"{API_BASE}/service-accounts/{account_id}", headers=headers))
