"""E2E API helpers for BiSheng.

Provides base URL, response assertion, and generic CRUD helpers.
"""

import httpx

# Backend API base URL — override with E2E_API_BASE env var if needed
import os

API_BASE = os.environ.get('E2E_API_BASE', 'http://localhost:7860/api/v1')


def assert_resp_200(resp: httpx.Response) -> dict:
    """Assert UnifiedResponseModel success and return data."""
    assert resp.status_code == 200, f'HTTP {resp.status_code}: {resp.text[:200]}'
    body = resp.json()
    assert body['status_code'] == 200, (
        f"Business error {body['status_code']}: {body.get('status_message')}"
    )
    return body.get('data')


def assert_resp_error(resp: httpx.Response, expected_code: int):
    """Assert UnifiedResponseModel returns a specific MMMEE error code."""
    body = resp.json()
    assert body['status_code'] == expected_code, (
        f"Expected error {expected_code}, got {body['status_code']}: "
        f"{body.get('status_message')}"
    )
    return body


async def create_resource(
    client: httpx.AsyncClient, path: str, data: dict, token: str,
) -> dict:
    """Generic POST to create a resource."""
    from test.e2e.helpers.auth import auth_headers
    resp = await client.post(
        f'{API_BASE}{path}',
        json=data,
        headers=auth_headers(token),
    )
    return assert_resp_200(resp)


async def list_resources(
    client: httpx.AsyncClient, path: str, token: str, params: dict = None,
) -> dict:
    """Generic GET to list resources."""
    from test.e2e.helpers.auth import auth_headers
    resp = await client.get(
        f'{API_BASE}{path}',
        params=params or {},
        headers=auth_headers(token),
    )
    return assert_resp_200(resp)


async def delete_resource(
    client: httpx.AsyncClient, path: str, resource_id: str, token: str,
):
    """Generic DELETE a resource."""
    from test.e2e.helpers.auth import auth_headers
    resp = await client.delete(
        f'{API_BASE}{path}/{resource_id}',
        headers=auth_headers(token),
    )
    return resp
