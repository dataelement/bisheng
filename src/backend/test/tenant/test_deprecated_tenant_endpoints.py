"""Tests for F011 deprecated tenant CRUD returning HTTP 410 Gone.

AC-15: ``POST /api/v1/tenants`` is retired (Root auto-created by migration,
Child created via ``POST /api/v1/departments/{id}/mount-tenant``).
``POST /api/v1/user/switch-tenant`` is retired (no more switch — user leaf
is derived from primary department in v2.5.1).

Test-First: written before the endpoint implementation is flipped to 410.
Expected to fail first (either 200/403 or missing route), then pass once
the handlers return the 410 payload.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


@pytest.fixture()
def tenant_app():
    """Minimal FastAPI app that mounts the tenant_crud router only.

    We don't use the full production app (lifespan + DB + Redis) because
    the 410 contract does not need any of those — the handlers must fire
    before any business logic.
    """
    from bisheng.tenant.api.endpoints import tenant_crud

    app = FastAPI()
    app.include_router(tenant_crud.router, prefix='/api/v1/tenants')
    return app


@pytest.fixture()
def user_tenant_app():
    from bisheng.tenant.api.endpoints import user_tenant

    app = FastAPI()
    app.include_router(user_tenant.router, prefix='/api/v1/user')
    return app


class TestDeprecatedPostTenants:

    def test_returns_410_gone(self, tenant_app):
        client = TestClient(tenant_app)
        resp = client.post('/api/v1/tenants/', json={
            'tenant_code': 'acme',
            'tenant_name': 'Acme Inc',
        })
        assert resp.status_code == 410

    def test_body_mentions_migration_and_mount_routes(self, tenant_app):
        client = TestClient(tenant_app)
        resp = client.post('/api/v1/tenants/', json={
            'tenant_code': 'acme',
            'tenant_name': 'Acme Inc',
        })
        body = resp.json()
        # Body surfaces how to create new tenants under v2.5.1.
        text = str(body).lower()
        assert '410' in text or 'gone' in text
        assert 'mount-tenant' in text or 'migration' in text.lower() or 'mount' in text


class TestDeprecatedSwitchTenant:

    def test_returns_410_gone(self, user_tenant_app):
        client = TestClient(user_tenant_app)
        resp = client.post('/api/v1/user/switch-tenant', json={
            'tenant_id': 2,
        })
        assert resp.status_code == 410

    def test_body_explains_removal(self, user_tenant_app):
        client = TestClient(user_tenant_app)
        resp = client.post('/api/v1/user/switch-tenant', json={
            'tenant_id': 2,
        })
        body = resp.json()
        assert 'switch' in str(body).lower() or 'primary department' in str(body).lower() \
            or 'derived' in str(body).lower() or 'removed' in str(body).lower()
