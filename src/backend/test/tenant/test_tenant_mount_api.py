"""Integration tests for F011 mount/unmount/migrate + Root protection API.

Covers spec AC-02, AC-03, AC-04a/b/d, AC-11, AC-15 at the HTTP surface.

Strategy:
  - Spin up a minimal FastAPI app with just the F011 routers mounted
    (tenant_crud + tenant_mount). No lifespan, no DB, no Redis — the
    business calls are mocked at the Service layer.
  - Override the ``get_login_user`` dep so we can control operator identity
    without issuing a real JWT.

Test-First: written BEFORE ``tenant_mount.py`` exists and BEFORE
``tenant_crud.py`` gets the Root-id HTTP-403 guard. First run = red.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload


@pytest.fixture()
def super_admin_payload():
    p = MagicMock(spec=UserPayload)
    p.user_id = 1
    p.user_name = 'root'
    p.tenant_id = 1
    p.is_global_super = True
    p.is_admin = MagicMock(return_value=True)
    return p


@pytest.fixture()
def child_admin_payload():
    p = MagicMock(spec=UserPayload)
    p.user_id = 55
    p.user_name = 'child_admin'
    p.tenant_id = 5
    p.is_global_super = False
    p.is_admin = MagicMock(return_value=True)
    return p


def _build_app(login_user):
    """Build the smallest app that contains the two F011 routers."""
    from bisheng.tenant.api.endpoints import tenant_crud, tenant_mount

    app = FastAPI()
    app.include_router(tenant_crud.router, prefix='/api/v1/tenants')
    app.include_router(tenant_mount.router, prefix='/api/v1')

    # Override login user dep for both endpoints.
    app.dependency_overrides[UserPayload.get_admin_user] = lambda: login_user
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    return app


# =========================================================================
# /departments/{id}/mount-tenant
# =========================================================================

class TestMountTenantEndpoint:

    def test_post_mount_tenant_happy_path(self, super_admin_payload):
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        fake_tenant = MagicMock()
        fake_tenant.id = 2
        fake_tenant.tenant_code = 'acme'
        fake_tenant.tenant_name = 'Acme'
        fake_tenant.parent_tenant_id = 1
        fake_tenant.status = 'active'
        fake_tenant.model_dump = lambda include=None: {
            'id': 2, 'tenant_code': 'acme', 'tenant_name': 'Acme',
            'parent_tenant_id': 1, 'status': 'active',
        }

        with patch(
            'bisheng.tenant.api.endpoints.tenant_mount.TenantMountService.mount_child',
            new_callable=AsyncMock, return_value=fake_tenant,
        ):
            resp = client.post(
                '/api/v1/departments/7/mount-tenant',
                json={'tenant_code': 'acme', 'tenant_name': 'Acme'},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get('data', {}).get('id') == 2

    def test_post_mount_tenant_nested_returns_400_22001(
        self, super_admin_payload,
    ):
        from bisheng.common.errcode.tenant_tree import (
            TenantTreeNestingForbiddenError,
        )
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        with patch(
            'bisheng.tenant.api.endpoints.tenant_mount.TenantMountService.mount_child',
            new_callable=AsyncMock,
            side_effect=TenantTreeNestingForbiddenError(),
        ):
            resp = client.post(
                '/api/v1/departments/20/mount-tenant',
                json={'tenant_code': 'nested', 'tenant_name': 'Nested'},
            )
        assert resp.status_code == 400
        assert resp.json()['status_code'] == 22001

    def test_delete_mount_no_body(self, super_admin_payload):
        """v2.5.1 唯一路径：DELETE 不需要 body，行为固定为迁回 Root + 归档。"""
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        with patch(
            'bisheng.tenant.api.endpoints.tenant_mount.TenantMountService.unmount_child',
            new_callable=AsyncMock,
            return_value={'tenant_id': 2, 'migrated_counts': {'flow': 3}},
        ):
            resp = client.request(
                'DELETE', '/api/v1/departments/7/mount-tenant',
            )
        assert resp.status_code == 200
        assert resp.json()['data']['tenant_id'] == 2
        assert resp.json()['data']['migrated_counts'] == {'flow': 3}

    def test_delete_mount_legacy_body_ignored(self, super_admin_payload):
        """旧客户端发 {policy: 'archive'} body 也应通过（兼容），实际走 migrate。"""
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        with patch(
            'bisheng.tenant.api.endpoints.tenant_mount.TenantMountService.unmount_child',
            new_callable=AsyncMock,
            return_value={'tenant_id': 2, 'migrated_counts': {}},
        ):
            resp = client.request(
                'DELETE', '/api/v1/departments/7/mount-tenant',
                json={'policy': 'archive'},
            )
        assert resp.status_code == 200
        assert resp.json()['data']['tenant_id'] == 2


# =========================================================================
# /tenants/{id}/status + DELETE /tenants/{id} Root protection
# =========================================================================

class TestRootProtectionHttp:

    def test_put_root_status_returns_403_22008(self, super_admin_payload):
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        resp = client.put(
            '/api/v1/tenants/1/status', json={'status': 'disabled'},
        )
        assert resp.status_code == 403
        body = resp.json()
        # Body should surface 22008 for the frontend.
        flat = str(body).lower()
        assert '22008' in flat

    def test_delete_root_returns_403_22008(self, super_admin_payload):
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        resp = client.delete('/api/v1/tenants/1')
        assert resp.status_code == 403
        assert '22008' in str(resp.json()).lower()

    def test_put_child_status_path_reaches_service(self, super_admin_payload):
        """Non-root id must fall through to TenantService (Service does the real work)."""
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        with patch(
            'bisheng.tenant.api.endpoints.tenant_crud.TenantService.aupdate_tenant_status',
            new_callable=AsyncMock,
            return_value={'id': 5, 'status': 'disabled'},
        ) as svc:
            resp = client.put(
                '/api/v1/tenants/5/status', json={'status': 'disabled'},
            )
        assert resp.status_code == 200
        svc.assert_awaited_once()


# =========================================================================
# POST /tenants/{child_id}/resources/migrate-from-root
# =========================================================================

class TestMigrateFromRootEndpoint:

    def test_post_migrate_from_root_super_happy(self, super_admin_payload):
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        with patch(
            'bisheng.tenant.api.endpoints.tenant_mount.TenantMountService.migrate_resources_from_root',
            new_callable=AsyncMock,
            return_value={'migrated': 2, 'failed': []},
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/migrate-from-root',
                json={
                    'resource_type': 'knowledge',
                    'resource_ids': [100, 102],
                },
            )
        assert resp.status_code == 200
        assert resp.json()['data']['migrated'] == 2

    def test_post_migrate_child_admin_returns_403_22010(
        self, child_admin_payload,
    ):
        from bisheng.common.errcode.tenant_tree import (
            TenantTreeMigratePermissionError,
        )
        app = _build_app(child_admin_payload)
        client = TestClient(app)
        with patch(
            'bisheng.tenant.api.endpoints.tenant_mount.TenantMountService.migrate_resources_from_root',
            new_callable=AsyncMock,
            side_effect=TenantTreeMigratePermissionError(),
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/migrate-from-root',
                json={
                    'resource_type': 'knowledge',
                    'resource_ids': [100],
                },
            )
        assert resp.status_code == 403
        assert '22010' in str(resp.json())

    def test_post_migrate_reports_failed_rows_inline(self, super_admin_payload):
        app = _build_app(super_admin_payload)
        client = TestClient(app)
        failed = [{'resource_id': 101, 'reason': '22011: wrong source tenant_id'}]
        with patch(
            'bisheng.tenant.api.endpoints.tenant_mount.TenantMountService.migrate_resources_from_root',
            new_callable=AsyncMock,
            return_value={'migrated': 2, 'failed': failed},
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/migrate-from-root',
                json={
                    'resource_type': 'knowledge',
                    'resource_ids': [100, 101, 102],
                },
            )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['migrated'] == 2
        assert data['failed'] == failed
