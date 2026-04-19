"""API endpoint tests for /tenants/{id}/admins (F013 code-review fix).

Verifies AC-13 HTTP layer: POST /tenants/1/admins returns 403 + errcode 19204.
Also covers the happy path for GET / POST / DELETE on a Child tenant id.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.tenant.api.endpoints.tenant_admin import router as admin_router


@pytest.fixture
def client():
    """Isolated FastAPI app with only the admin router mounted."""
    app = FastAPI()
    app.include_router(admin_router, prefix='/tenants')

    async def _fake_admin_user():
        with patch('bisheng.user.domain.services.auth.UserRoleDao') as urd:
            urd.get_user_roles.return_value = []
            return UserPayload(user_id=1, user_name='admin', user_role=[], tenant_id=1)

    app.dependency_overrides[UserPayload.get_admin_user] = _fake_admin_user
    return TestClient(app)


# ── AC-13: Root admin grant rejected with HTTP 403 + 19204 ──────


def test_ac_13_grant_on_root_tenant_returns_403(client):
    response = client.post('/tenants/1/admins', json={'user_id': 10})
    assert response.status_code == 403
    payload = response.json()
    assert payload['status_code'] == 19204


def test_ac_13_revoke_on_root_tenant_returns_403(client):
    response = client.delete('/tenants/1/admins/10')
    assert response.status_code == 403
    payload = response.json()
    assert payload['status_code'] == 19204


# ── Child tenant happy paths ────────────────────────────────────


def test_grant_on_child_tenant_returns_200(client):
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    fake_fga = MagicMock()
    fake_fga.write_tuples = AsyncMock()
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao, \
         patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        response = client.post('/tenants/5/admins', json={'user_id': 10})

    assert response.status_code == 200
    fake_fga.write_tuples.assert_awaited_once()


def test_revoke_on_child_tenant_returns_200(client):
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    fake_fga = MagicMock()
    fake_fga.write_tuples = AsyncMock()
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao, \
         patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        response = client.delete('/tenants/5/admins/10')

    assert response.status_code == 200


def test_list_admins_returns_user_ids(client):
    fake_fga = MagicMock()
    fake_fga.read_tuples = AsyncMock(return_value=[
        {'user': 'user:7', 'relation': 'admin', 'object': 'tenant:5'},
        {'user': 'user:9', 'relation': 'admin', 'object': 'tenant:5'},
    ])
    with patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        response = client.get('/tenants/5/admins')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status_code'] == 200
    assert sorted(payload['data']['user_ids']) == [7, 9]


def test_list_admins_root_returns_empty(client):
    """Root tenant list returns 200 + empty user_ids by design (no tuples)."""
    response = client.get('/tenants/1/admins')
    assert response.status_code == 200
    assert response.json()['data']['user_ids'] == []


# ── Tenant not found (verifies the split from the code-review MEDIUM fix) ──


def test_grant_on_missing_tenant_returns_tenant_not_found(client):
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao:
        dao.aget_by_id = AsyncMock(return_value=None)
        response = client.post('/tenants/99/admins', json={'user_id': 10})

    # TenantNotFoundError flows through the generic BaseErrorCode handler (200 + errcode 20000)
    assert response.status_code == 200
    assert response.json()['status_code'] == 20000
