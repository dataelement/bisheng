"""Tests for F024 410 Gone responses on deprecated tenant member endpoints.

``POST /api/v1/tenants/{id}/users`` and ``DELETE /api/v1/tenants/{id}/users/{user_id}``
return 410 Gone in v2.5.1 — tenant membership is derived from the user's
primary department (F012), so manual UserTenant writes from the public
API are removed. The ``GET`` endpoint is retained.

We invoke the endpoint handlers directly (no full FastAPI app spin-up,
which is heavy and pulls in the global startup chain). The 410 handlers
intentionally take no auth dependency so SDK retries do not land on
401/403, mirroring F011's ``switch-tenant`` 410 pattern.
"""

from __future__ import annotations

import asyncio

import pytest


def _decode(response):
    """Extract status_code + parsed JSON body from a starlette ``JSONResponse``."""
    import json
    return response.status_code, json.loads(response.body)


@pytest.mark.parametrize(
    'tenant_id', [1, 2, 9999],
    ids=['root', 'small', 'large'],
)
def test_add_users_endpoint_returns_410_gone(tenant_id):
    """AC-08: POST /tenants/{id}/users always returns 410 Gone."""
    from bisheng.tenant.api.endpoints.tenant_users import add_users_deprecated

    response = asyncio.run(add_users_deprecated(tenant_id))
    status, body = _decode(response)

    assert status == 410
    assert body['error'] == '410 Gone'
    assert 'primary department' in body['detail']
    assert 'apply-edit' in body['migration']
    assert body['deprecated_since'] == 'v2.5.1'


@pytest.mark.parametrize(
    'tenant_id,user_id',
    [(1, 1), (5, 100), (9999, 88888)],
)
def test_remove_user_endpoint_returns_410_gone(tenant_id, user_id):
    """AC-09: DELETE /tenants/{id}/users/{user_id} always returns 410 Gone."""
    from bisheng.tenant.api.endpoints.tenant_users import remove_user_deprecated

    response = asyncio.run(remove_user_deprecated(tenant_id, user_id))
    status, body = _decode(response)

    assert status == 410
    assert body['error'] == '410 Gone'
    assert 'primary department' in body['detail']
    assert 'apply-edit' in body['migration']


def test_deprecated_endpoints_have_no_auth_dependency():
    """AC-08/09 detail: 410 handlers take no UserPayload dependency so they
    can't degrade to 401/403 even when SDK clients retry without auth.

    Verified by inspecting the FastAPI route's dependency tree.
    """
    from bisheng.tenant.api.endpoints import tenant_users as m

    add_route = next(
        r for r in m.router.routes
        if r.path == '/{tenant_id}/users' and 'POST' in r.methods
    )
    delete_route = next(
        r for r in m.router.routes
        if r.path == '/{tenant_id}/users/{user_id}' and 'DELETE' in r.methods
    )

    # FastAPI route's dependant.dependencies should NOT contain UserPayload.
    def _has_user_payload(deps) -> bool:
        for dep in deps:
            # FastAPI Dependant.name is set to the parameter name in the
            # outer signature — `login_user` in our handlers.
            if getattr(dep, 'name', None) == 'login_user':
                return True
            if _has_user_payload(getattr(dep, 'dependencies', [])):
                return True
        return False

    assert not _has_user_payload(add_route.dependant.dependencies)
    assert not _has_user_payload(delete_route.dependant.dependencies)


def test_get_endpoint_still_takes_auth_dependency():
    """AC-10: GET /tenants/{id}/users is preserved (auth + service call)."""
    from bisheng.tenant.api.endpoints import tenant_users as m

    get_route = next(
        r for r in m.router.routes
        if r.path == '/{tenant_id}/users' and 'GET' in r.methods
    )

    # GET should still require admin auth — verify dependant has at least
    # one dependency referencing UserPayload.
    def _has_user_payload(deps) -> bool:
        for dep in deps:
            # FastAPI Dependant.name is set to the parameter name in the
            # outer signature — `login_user` in our handlers.
            if getattr(dep, 'name', None) == 'login_user':
                return True
            if _has_user_payload(getattr(dep, 'dependencies', [])):
                return True
        return False

    assert _has_user_payload(get_route.dependant.dependencies)
