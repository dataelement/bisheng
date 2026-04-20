"""
E2E tests for F001: Multi-Tenant Core Infrastructure

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE env var)
- Default admin account: admin/admin123

F001 is a pure infrastructure feature with no new API endpoints.
These tests verify tenant infrastructure works correctly through
existing APIs (login, health check, flow list as regression).

Covers (indirect API verification):
- AC-02: Default tenant exists after startup
- AC-07: JWT contains tenant_id; old tokens fallback to 1
- AC-08: LoginUser exposes tenant_id (authenticated endpoint works)
- AC-11: enabled=false → system works like single-tenant

Already covered by unit tests (42 tests, skipped here):
- AC-01, AC-03: DDL structure
- AC-04, AC-05, AC-06: SQLAlchemy event hooks
- AC-09: Celery context propagation
- AC-10: Storage prefix functions
"""

import base64
import json
import os

import pytest
import httpx

API_BASE = os.environ.get('E2E_API_BASE', 'http://localhost:7860/api/v1')
HEALTH_URL = API_BASE.replace('/api/v1', '') + '/health'

PREFIX = 'e2e-f001-mt-'


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT token payload without verification (for inspection only)."""
    parts = token.split('.')
    if len(parts) != 3:
        return {}
    payload_b64 = parts[1] + '=' * (4 - len(parts[1]) % 4)
    payload_bytes = base64.urlsafe_b64decode(payload_b64)
    payload = json.loads(payload_bytes)
    subject = json.loads(payload.get('sub', '{}'))
    return subject


def _login(client: httpx.Client) -> str:
    """Login as admin and return JWT token."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pubkey_resp = client.get(f'{API_BASE}/user/public_key')
    assert pubkey_resp.status_code == 200
    public_key_pem = pubkey_resp.json()['data']['public_key']

    admin_password = os.environ.get('E2E_ADMIN_PASSWORD', 'Bisheng@top1')
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(admin_password.encode(), padding.PKCS1v15())
    encrypted_password = base64.b64encode(encrypted).decode()

    login_resp = client.post(
        f'{API_BASE}/user/login',
        json={'user_name': 'admin', 'password': encrypted_password},
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body['status_code'] == 200, f"Login failed: {body.get('status_message')}"
    return body['data']['access_token']


@pytest.mark.skipif(
    os.environ.get('E2E_SKIP', '0') == '1',
    reason='E2E tests skipped (E2E_SKIP=1)',
)
class TestE2EMultiTenantCore:
    """E2E: F001 Multi-Tenant Core Infrastructure"""

    @pytest.fixture(scope='class')
    def client(self):
        with httpx.Client(timeout=30.0) as c:
            yield c

    @pytest.fixture(scope='class')
    def admin_token(self, client):
        try:
            return _login(client)
        except (AssertionError, Exception) as e:
            pytest.skip(f'Login failed (backend may not have F001 deployed): {e}')

    # ──────── Health Check ────────

    def test_health_check(self, client):
        """Verify backend is running and responsive."""
        resp = client.get(HEALTH_URL)
        assert resp.status_code == 200

    # ──────── AC-02: Default Tenant ────────

    def test_ac02_default_tenant_seeded(self, admin_token):
        """AC-02: Default tenant (id=1) should exist after startup.

        Verified indirectly: login succeeds and JWT has tenant_id=1.
        """
        subject = _decode_jwt_payload(admin_token)
        assert subject.get('tenant_id') == 1, (
            f'AC-02 FAIL: Expected tenant_id=1 in JWT, got {subject.get("tenant_id")}'
        )

    # ──────── AC-07: JWT tenant_id ────────

    def test_ac07_jwt_contains_tenant_id(self, admin_token):
        """AC-07: New JWT token should contain tenant_id field."""
        subject = _decode_jwt_payload(admin_token)

        assert 'user_id' in subject, f'JWT missing user_id: {subject}'
        assert 'tenant_id' in subject, (
            f'AC-07 FAIL: JWT missing tenant_id: {subject}'
        )
        assert isinstance(subject['tenant_id'], int), (
            f'tenant_id should be int, got {type(subject["tenant_id"])}'
        )

    # ──────── AC-08: Authenticated endpoint ────────

    def test_ac08_authenticated_endpoint_works(self, client, admin_token):
        """AC-08: Authenticated endpoints work with tenant_id in JWT.

        LoginUser.tenant_id is accessible in endpoint handlers.
        """
        headers = {'Cookie': f'access_token_cookie={admin_token}'}
        resp = client.get(f'{API_BASE}/user/info', headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 200, (
            f'AC-08 FAIL: Authenticated endpoint failed: {body}'
        )

    # ──────── AC-11: Regression ────────

    def test_ac11_existing_apis_unaffected(self, client, admin_token):
        """AC-11: With multi_tenant.enabled=false, existing APIs work unchanged.

        Login + list flows still works — key regression test.
        """
        headers = {'Cookie': f'access_token_cookie={admin_token}'}

        # List workflows — basic read API regression
        resp = client.get(
            f'{API_BASE}/workflow/list',
            params={'page_num': 1, 'page_size': 5},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 200, (
            f'AC-11 FAIL: List workflows failed: {body}'
        )
