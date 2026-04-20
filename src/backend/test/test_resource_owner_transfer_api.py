"""F018 T04: resource-owner-transfer HTTP integration tests.

Covers spec AC-01/02/03/04/05/07/08b/08c/08d/10 at the HTTP surface.

Strategy mirrors ``test_tenant_mount_api.py``:
  - Minimal FastAPI app with just the F018 router attached.
  - Service layer mocked — the tests exercise routing, auth injection,
    DTO validation, and error → HTTP status mapping.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.resource_owner_transfer import (
    ResourceTransferBatchLimitError,
    ResourceTransferPermissionError,
    ResourceTransferReceiverOutOfTenantError,
    ResourceTransferSelfError,
    ResourceTransferTxFailedError,
    ResourceTransferUnsupportedTypeError,
)

ENDPOINT_MOD = 'bisheng.tenant.api.endpoints.resource_owner_transfer'


# ---------------------------------------------------------------------------
# Operator fixtures
# ---------------------------------------------------------------------------

def _mk_payload(user_id: int, *, is_super: bool = False,
                is_admin: bool = False, tenant_id: int = 2):
    p = MagicMock(spec=UserPayload)
    p.user_id = user_id
    p.user_name = f'user_{user_id}'
    p.tenant_id = tenant_id
    p.is_global_super = MagicMock(return_value=is_super)
    p.is_admin = MagicMock(return_value=is_admin)
    p.admin_scope_tenant_id = None
    return p


@pytest.fixture()
def resource_owner():
    return _mk_payload(user_id=100, tenant_id=2)


@pytest.fixture()
def tenant_admin():
    return _mk_payload(user_id=10, is_admin=True, tenant_id=2)


@pytest.fixture()
def random_user():
    """Non-owner, non-admin — should hit 19601 on transfer attempts."""
    return _mk_payload(user_id=999, tenant_id=2)


@pytest.fixture()
def global_super():
    return _mk_payload(user_id=1, is_super=True, is_admin=True, tenant_id=1)


def _build_app(login_user):
    """Mount only the F018 router — smallest possible surface."""
    from bisheng.tenant.api.endpoints import resource_owner_transfer

    app = FastAPI()
    app.include_router(resource_owner_transfer.router, prefix='/api/v1')
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    return app


# =========================================================================
# POST /tenants/{id}/resources/transfer-owner
# =========================================================================

class TestTransferOwnerEndpoint:

    def test_happy_path_returns_200_with_count(self, resource_owner):
        """AC-01: owner themselves transfers — 200 + transferred_count."""
        app = _build_app(resource_owner)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            return_value={'transferred_count': 5,
                          'transfer_log_id': 'txn_20260421_abc'},
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow', 'assistant'],
                    'reason': '交给李四',
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body['data']['transferred_count'] == 5
        assert body['data']['transfer_log_id'] == 'txn_20260421_abc'

    def test_child_admin_ok(self, tenant_admin):
        """AC-02: tenant admin代发 transfer — also 200."""
        app = _build_app(tenant_admin)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            return_value={'transferred_count': 1, 'transfer_log_id': 'txn_x'},
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow'],
                },
            )
        assert resp.status_code == 200

    def test_non_owner_non_admin_returns_403_19601(self, random_user):
        """AC-03: permission check fails → 19601 → HTTP 403."""
        app = _build_app(random_user)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            side_effect=ResourceTransferPermissionError(),
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow'],
                },
            )
        assert resp.status_code == 403
        assert resp.json()['status_code'] == 19601

    def test_resource_ids_null_accepted(self, resource_owner):
        """AC-04: resource_ids absent → service gets None, returns full count."""
        app = _build_app(resource_owner)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            return_value={'transferred_count': 18, 'transfer_log_id': 'txn_'},
        ) as svc:
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow', 'knowledge_space'],
                },
            )
        assert resp.status_code == 200
        assert svc.call_args.kwargs['resource_ids'] is None

    def test_resource_ids_list_passed_through(self, resource_owner):
        """AC-05: specific id list flows to the service unchanged."""
        app = _build_app(resource_owner)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            return_value={'transferred_count': 2, 'transfer_log_id': 'txn_'},
        ) as svc:
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow'],
                    'resource_ids': ['wf-a', 'wf-c'],
                },
            )
        assert resp.status_code == 200
        assert svc.call_args.kwargs['resource_ids'] == ['wf-a', 'wf-c']

    def test_batch_over_500_returns_400_19602(self, resource_owner):
        """AC-07: 501-row batch → 19602 → HTTP 400."""
        app = _build_app(resource_owner)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            side_effect=ResourceTransferBatchLimitError(),
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow'],
                },
            )
        assert resp.status_code == 400
        assert resp.json()['status_code'] == 19602

    def test_receiver_cross_child_returns_400_19603(self, resource_owner):
        """AC-08c: to_user leaf in Child B when tenant_id = Child A → 19603."""
        app = _build_app(resource_owner)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            side_effect=ResourceTransferReceiverOutOfTenantError(),
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow'],
                },
            )
        assert resp.status_code == 400
        assert resp.json()['status_code'] == 19603

    def test_root_to_child_returns_400_19603(self, global_super):
        """AC-08d: Root → Child blocked; caller is expected to use F011
        migrate-from-root instead."""
        app = _build_app(global_super)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            side_effect=ResourceTransferReceiverOutOfTenantError(),
        ):
            resp = client.post(
                '/api/v1/tenants/1/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow'],
                },
            )
        assert resp.status_code == 400
        assert resp.json()['status_code'] == 19603

    def test_unsupported_type_rejected_at_dto_level(self, resource_owner):
        """Literal schema rejects 'dashboard' → HTTP 422 from FastAPI validation."""
        app = _build_app(resource_owner)
        client = TestClient(app)
        resp = client.post(
            '/api/v1/tenants/2/resources/transfer-owner',
            json={
                'from_user_id': 100, 'to_user_id': 200,
                'resource_types': ['dashboard'],
            },
        )
        # FastAPI's own validator short-circuits before the handler runs.
        assert resp.status_code == 422

    def test_self_transfer_returns_400_19606(self, resource_owner):
        """AC 19606: from_user_id == to_user_id."""
        app = _build_app(resource_owner)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            side_effect=ResourceTransferSelfError(),
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 100,
                    'resource_types': ['workflow'],
                },
            )
        assert resp.status_code == 400
        assert resp.json()['status_code'] == 19606

    def test_tx_failure_returns_500_19605(self, resource_owner):
        """AC-06: FGA failure → 19605 wrapped → HTTP 500 with structured body."""
        app = _build_app(resource_owner)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.transfer_owner',
            new_callable=AsyncMock,
            side_effect=ResourceTransferTxFailedError(),
        ):
            resp = client.post(
                '/api/v1/tenants/2/resources/transfer-owner',
                json={
                    'from_user_id': 100, 'to_user_id': 200,
                    'resource_types': ['workflow'],
                },
            )
        assert resp.status_code == 500
        assert resp.json()['status_code'] == 19605


# =========================================================================
# GET /tenants/{id}/resources/pending-transfer
# =========================================================================

class TestPendingTransferEndpoint:

    def test_super_admin_gets_list(self, global_super):
        """AC-10: super admin sees users whose leaf moved off the tenant."""
        app = _build_app(global_super)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.list_pending_transfer',
            new_callable=AsyncMock,
            return_value=[
                {'user_id': 100, 'resource_count': 3,
                 'current_leaf_tenant_id': 5},
            ],
        ):
            resp = client.get('/api/v1/tenants/2/resources/pending-transfer')
        assert resp.status_code == 200
        data = resp.json()['data']
        assert len(data) == 1
        assert data[0]['user_id'] == 100
        assert data[0]['resource_count'] == 3
        assert data[0]['current_leaf_tenant_id'] == 5

    def test_tenant_admin_allowed(self, tenant_admin):
        app = _build_app(tenant_admin)
        client = TestClient(app)
        with patch(
            f'{ENDPOINT_MOD}.ResourceOwnershipService.list_pending_transfer',
            new_callable=AsyncMock, return_value=[],
        ):
            resp = client.get('/api/v1/tenants/2/resources/pending-transfer')
        assert resp.status_code == 200
        assert resp.json()['data'] == []

    def test_regular_user_forbidden_19601(self, random_user):
        """AC-10 extension: non-admin users cannot enumerate pending transfers."""
        app = _build_app(random_user)
        client = TestClient(app)
        resp = client.get('/api/v1/tenants/2/resources/pending-transfer')
        assert resp.status_code == 403
        assert resp.json()['status_code'] == 19601
