"""E2E data cleanup helpers for BiSheng.

Provides safe cleanup with prefix filtering to prevent accidental deletion
of production data.
"""

import httpx

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers


async def cleanup_by_prefix(
    client: httpx.AsyncClient,
    path: str,
    prefix: str,
    token: str,
):
    """Safely delete resources matching a specific name prefix.

    Args:
        path: API list endpoint (e.g. "/flow/list")
        prefix: Name prefix to match (must be >= 5 chars for safety)
        token: JWT token for authentication

    Raises:
        ValueError: If prefix is too short (prevents accidental mass deletion)
    """
    if len(prefix) < 5:
        raise ValueError(
            f'Cleanup prefix too short ({len(prefix)} chars): "{prefix}". '
            f'Must be >= 5 chars to prevent accidental deletion.'
        )

    headers = auth_headers(token)
    try:
        resp = await client.get(
            f'{API_BASE}{path}',
            params={'page': 1, 'limit': 100},
            headers=headers,
        )
        if resp.status_code != 200:
            return

        body = resp.json()
        if body.get('status_code') != 200:
            return

        data = body.get('data', {})
        items = data.get('data', []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return

        for item in items:
            name = item.get('name', '')
            if name.startswith(prefix):
                item_id = item.get('id')
                if item_id:
                    await client.delete(
                        f'{API_BASE}{path}/{item_id}',
                        headers=headers,
                    )
    except Exception:
        pass  # Cleanup failure is non-fatal


async def ensure_test_tenant(
    client: httpx.AsyncClient,
    admin_token: str,
    tenant_code: str,
    admin_user_ids: list = None,
) -> dict:
    """Ensure a test tenant exists. Creates one if not found.

    Returns tenant dict with at least {id, tenant_code}.
    Uses F010 tenant CRUD API.
    """
    headers = auth_headers(admin_token)

    # Check if tenant already exists via list API
    resp = await client.get(
        f'{API_BASE}/tenants/',
        params={'keyword': tenant_code, 'page': 1, 'page_size': 10},
        headers=headers,
    )
    if resp.status_code == 200:
        body = resp.json()
        if body.get('status_code') == 200:
            data = body.get('data', {})
            items = data.get('data', []) if isinstance(data, dict) else []
            for item in items:
                if item.get('tenant_code') == tenant_code:
                    return item

    # Not found — create it
    resp = await client.post(
        f'{API_BASE}/tenants/',
        json={
            'tenant_name': f'Test Tenant ({tenant_code})',
            'tenant_code': tenant_code,
            'admin_user_ids': admin_user_ids or [1],
        },
        headers=headers,
    )
    if resp.status_code == 200:
        body = resp.json()
        if body.get('status_code') == 200:
            return body.get('data', {})

    return {'id': None, 'tenant_code': tenant_code}


async def cleanup_test_tenants(
    client: httpx.AsyncClient,
    prefix: str,
    token: str,
):
    """Delete test tenants by code prefix. Removes users first, then deletes."""
    if len(prefix) < 5:
        raise ValueError(f'Cleanup prefix too short: "{prefix}"')

    headers = auth_headers(token)
    try:
        resp = await client.get(
            f'{API_BASE}/tenants/',
            params={'page': 1, 'page_size': 100},
            headers=headers,
        )
        if resp.status_code != 200:
            return

        body = resp.json()
        if body.get('status_code') != 200:
            return

        data = body.get('data', {})
        items = data.get('data', []) if isinstance(data, dict) else []
        for item in items:
            code = item.get('tenant_code', '')
            if code.startswith(prefix):
                tid = item.get('id')
                if not tid:
                    continue
                # Remove all users first (so delete succeeds)
                users_resp = await client.get(
                    f'{API_BASE}/tenants/{tid}/users',
                    params={'page': 1, 'page_size': 100},
                    headers=headers,
                )
                if users_resp.status_code == 200:
                    users_body = users_resp.json()
                    if users_body.get('status_code') == 200:
                        users_data = users_body.get('data', {})
                        user_list = users_data.get('data', []) if isinstance(users_data, dict) else []
                        for u in user_list:
                            uid = u.get('user_id')
                            if uid:
                                await client.delete(
                                    f'{API_BASE}/tenants/{tid}/users/{uid}',
                                    headers=headers,
                                )
                # Disable then delete
                await client.put(
                    f'{API_BASE}/tenants/{tid}/status',
                    json={'status': 'disabled'},
                    headers=headers,
                )
                await client.delete(
                    f'{API_BASE}/tenants/{tid}',
                    headers=headers,
                )
    except Exception:
        pass  # Cleanup failure is non-fatal
