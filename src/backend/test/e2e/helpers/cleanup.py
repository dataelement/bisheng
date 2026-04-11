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
):
    """Ensure a test tenant exists. Creates one if not found.

    Note: F001 does not expose tenant CRUD API — this is a stub that will
    be implemented when F010 (tenant-management-ui) is available.
    For now, tests use the default tenant (id=1).
    """
    # F010 will provide tenant CRUD API. Until then, use default tenant.
    pass
