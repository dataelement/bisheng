"""F019-admin-tenant-scope HTTP integration tests.

Covers AC-01/02/03/04/05/14/15/16 at the HTTP surface. Strategy mirrors
``test_resource_owner_transfer_api.py``:

- Minimal FastAPI app with only the F019 admin router attached.
- ``_check_is_global_super`` patched so tests can control the super-admin
  decision without an FGA dependency.
- ``TenantScopeService`` patched with ``AsyncMock`` so routing, auth gate,
  request validation and error→HTTP mapping are verified in isolation.

Service-layer correctness (Redis effects, audit payload shape) is covered
in ``test_admin_tenant_scope_service.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.admin_scope import AdminScopeTenantNotFoundError


ENDPOINT_MOD = 'bisheng.admin.api.endpoints.tenant_scope'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mk_user(user_id: int, tenant_id: int = 1):
    u = MagicMock(spec=UserPayload)
    u.user_id = user_id
    u.user_name = f'user_{user_id}'
    u.tenant_id = tenant_id
    return u


@pytest.fixture()
def super_admin():
    return _mk_user(user_id=1, tenant_id=1)


@pytest.fixture()
def child_admin():
    return _mk_user(user_id=10, tenant_id=5)


@pytest.fixture()
def normal_user():
    return _mk_user(user_id=999, tenant_id=5)


def _build_app(login_user):
    """Mount only the F019 admin router — smallest possible surface."""
    from bisheng.admin.api.router import router as admin_router

    app = FastAPI()
    app.include_router(admin_router, prefix='/api/v1')
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    return app


# Helper: patch the super check + service methods in one place.
def _patched_super(is_super: bool):
    return patch(
        f'{ENDPOINT_MOD}._check_is_global_super',
        new_callable=AsyncMock,
        return_value=is_super,
    )


# =========================================================================
# POST /admin/tenant-scope
# =========================================================================

class TestSetTenantScope:

    def test_super_admin_success(self, super_admin):
        """AC-01: super admin POST {tenant_id: 5} → 200 + scope data."""
        app = _build_app(super_admin)
        client = TestClient(app)
        with _patched_super(True), patch(
            f'{ENDPOINT_MOD}.TenantScopeService.set_scope',
            new_callable=AsyncMock,
            return_value={
                'scope_tenant_id': 5,
                'expires_at': '2026-04-21T08:00:00+00:00',
            },
        ) as svc:
            resp = client.post('/api/v1/admin/tenant-scope', json={'tenant_id': 5})

        assert resp.status_code == 200
        body = resp.json()
        assert body['data']['scope_tenant_id'] == 5
        assert body['data']['expires_at'] == '2026-04-21T08:00:00+00:00'
        # set_scope received the correct user_id + tenant_id + ctx shape.
        kwargs = svc.await_args.kwargs
        assert kwargs['user_id'] == 1
        assert kwargs['tenant_id'] == 5
        assert 'ip' in kwargs['request_context']
        assert 'ua' in kwargs['request_context']

    def test_clear_scope_via_null(self, super_admin):
        """AC-03: body tenant_id=null → 200, service invoked with None."""
        app = _build_app(super_admin)
        client = TestClient(app)
        with _patched_super(True), patch(
            f'{ENDPOINT_MOD}.TenantScopeService.set_scope',
            new_callable=AsyncMock,
            return_value={'scope_tenant_id': None, 'expires_at': None},
        ) as svc:
            resp = client.post('/api/v1/admin/tenant-scope', json={'tenant_id': None})

        assert resp.status_code == 200
        assert resp.json()['data'] == {
            'scope_tenant_id': None, 'expires_at': None,
        }
        assert svc.await_args.kwargs['tenant_id'] is None

    def test_child_admin_forbidden_19701(self, child_admin):
        """AC-04: Child Admin → HTTP 403 + body.status_code=19701."""
        app = _build_app(child_admin)
        client = TestClient(app)
        with _patched_super(False), patch(
            f'{ENDPOINT_MOD}.TenantScopeService.set_scope',
            new_callable=AsyncMock,
        ) as svc:
            resp = client.post('/api/v1/admin/tenant-scope', json={'tenant_id': 5})

        assert resp.status_code == 403
        assert resp.json()['status_code'] == 19701
        # Service must NOT be called on an auth failure (no Redis side effects).
        svc.assert_not_awaited()

    def test_normal_user_forbidden_19701(self, normal_user):
        """AC-05: ordinary user → HTTP 403 + 19701."""
        app = _build_app(normal_user)
        client = TestClient(app)
        with _patched_super(False):
            resp = client.post('/api/v1/admin/tenant-scope', json={'tenant_id': 5})
        assert resp.status_code == 403
        assert resp.json()['status_code'] == 19701

    def test_invalid_tenant_id_returns_19702(self, super_admin):
        """AC-15: service raises 19702 → HTTP 400 + body.status_code=19702."""
        app = _build_app(super_admin)
        client = TestClient(app)
        with _patched_super(True), patch(
            f'{ENDPOINT_MOD}.TenantScopeService.set_scope',
            new_callable=AsyncMock,
            side_effect=AdminScopeTenantNotFoundError(),
        ):
            resp = client.post('/api/v1/admin/tenant-scope', json={'tenant_id': 999})

        assert resp.status_code == 400
        assert resp.json()['status_code'] == 19702

    def test_root_as_scope_accepted(self, super_admin):
        """AC-16: tenant_id=1 (Root) is a valid scope (lock-to-Root view)."""
        app = _build_app(super_admin)
        client = TestClient(app)
        with _patched_super(True), patch(
            f'{ENDPOINT_MOD}.TenantScopeService.set_scope',
            new_callable=AsyncMock,
            return_value={
                'scope_tenant_id': 1,
                'expires_at': '2026-04-21T08:00:00+00:00',
            },
        ) as svc:
            resp = client.post('/api/v1/admin/tenant-scope', json={'tenant_id': 1})

        assert resp.status_code == 200
        assert resp.json()['data']['scope_tenant_id'] == 1
        assert svc.await_args.kwargs['tenant_id'] == 1


# =========================================================================
# GET /admin/tenant-scope
# =========================================================================

class TestGetTenantScope:

    def test_super_admin_returns_current(self, super_admin):
        """AC-02: super admin GET returns {scope_tenant_id, expires_at}."""
        app = _build_app(super_admin)
        client = TestClient(app)
        with _patched_super(True), patch(
            f'{ENDPOINT_MOD}.TenantScopeService.get_scope',
            new_callable=AsyncMock,
            return_value={
                'scope_tenant_id': 5,
                'expires_at': '2026-04-21T08:00:00+00:00',
            },
        ):
            resp = client.get('/api/v1/admin/tenant-scope')

        assert resp.status_code == 200
        assert resp.json()['data']['scope_tenant_id'] == 5

    def test_super_admin_empty_scope_returns_nulls(self, super_admin):
        """AC-02 edge: no active scope → both fields null, HTTP 200."""
        app = _build_app(super_admin)
        client = TestClient(app)
        with _patched_super(True), patch(
            f'{ENDPOINT_MOD}.TenantScopeService.get_scope',
            new_callable=AsyncMock,
            return_value={'scope_tenant_id': None, 'expires_at': None},
        ):
            resp = client.get('/api/v1/admin/tenant-scope')

        assert resp.status_code == 200
        assert resp.json()['data'] == {
            'scope_tenant_id': None, 'expires_at': None,
        }

    def test_child_admin_get_forbidden_19701(self, child_admin):
        """Symmetry with POST: non-super GET also 403 + 19701."""
        app = _build_app(child_admin)
        client = TestClient(app)
        with _patched_super(False), patch(
            f'{ENDPOINT_MOD}.TenantScopeService.get_scope',
            new_callable=AsyncMock,
        ) as svc:
            resp = client.get('/api/v1/admin/tenant-scope')

        assert resp.status_code == 403
        assert resp.json()['status_code'] == 19701
        svc.assert_not_awaited()
