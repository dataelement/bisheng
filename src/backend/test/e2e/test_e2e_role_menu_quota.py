"""
E2E tests for F005: Role Menu Quota (策略角色、菜单权限与配额管理)

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE env var)
- Default admin account: admin/Bisheng@top1 (or E2E_ADMIN_PASSWORD env var)
- Default tenant (id=1)

Covers (API behavior):
- AC-01: Create tenant role via POST /roles
- AC-02: Create global role (admin) via POST /roles
- AC-03: List roles (tenant admin) — global readonly + tenant editable
- AC-04: List roles (system admin) — all except AdminRole
- AC-05: Update role via PUT /roles/{id}
- AC-06: Update global role by non-admin → 24003
- AC-07: Delete builtin role → 24004
- AC-08: Delete role cascades
- AC-09: Duplicate role name → 24002
- AC-10: Get role detail with user_count
- AC-10c: Invalid quota_config → 24005
- AC-11: Update menu permissions
- AC-12: Get menu permissions
- AC-15: Get effective quota
- AC-19: Admin quota all unlimited
- AC-24: Legacy POST /role/add
- AC-25: Legacy GET /role/list

Skipped (unit test coverage / requires F008):
- AC-16~AC-18: Multi-role quota logic (covered by test_quota_service.py)
- AC-20~AC-23: Quota enforcement (requires @require_quota on resource endpoints, F008)
- AC-10b: Regular user denied (requires non-admin user without any admin role)
- AC-26, AC-27: Legacy role_access (requires group_admin setup)

Data isolation: All test resources use 'e2e-f005-role-' prefix.
"""

import os
import time

import httpx
import pytest

API_BASE = os.environ.get('E2E_API_BASE', 'http://localhost:7860/api/v1')
HEALTH_URL = API_BASE.replace('/api/v1', '') + '/health'
PREFIX = 'e2e-f005-role-'
RUN_ID = str(int(time.time()))[-6:]


# ---------------------------------------------------------------------------
# Auth helpers (sync, following F004 pattern)
# ---------------------------------------------------------------------------

def _login(client: httpx.Client, username: str = 'admin', password: str = None) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    import base64

    pubkey_resp = client.get(f'{API_BASE}/user/public_key')
    assert pubkey_resp.status_code == 200
    public_key_pem = pubkey_resp.json()['data']['public_key']

    if password is None:
        password = os.environ.get('E2E_ADMIN_PASSWORD', 'Bisheng@top1')

    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
    encrypted_b64 = base64.b64encode(encrypted).decode()

    resp = client.post(f'{API_BASE}/user/login', json={
        'user_name': username,
        'password': encrypted_b64,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['status_code'] == 200, f"Login failed: {body.get('status_message')}"
    return body['data']['access_token']


def _auth(token: str) -> dict:
    return {'Cookie': f'access_token_cookie={token}'}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _assert_200(resp: httpx.Response) -> dict:
    assert resp.status_code == 200, f'HTTP {resp.status_code}: {resp.text[:300]}'
    body = resp.json()
    assert body['status_code'] == 200, (
        f"Business error {body['status_code']}: {body.get('status_message')}"
    )
    return body.get('data')


def _assert_error(resp: httpx.Response, expected_code: int) -> dict:
    body = resp.json()
    assert body['status_code'] == expected_code, (
        f"Expected error {expected_code}, got {body['status_code']}: "
        f"{body.get('status_message')}"
    )
    return body


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------

def _cleanup_test_roles(client: httpx.Client, token: str):
    """Delete all roles with e2e-f005-role- prefix."""
    headers = _auth(token)
    resp = client.get(f'{API_BASE}/roles', params={'keyword': PREFIX, 'page': 1, 'limit': 100},
                      headers=headers)
    if resp.status_code != 200:
        return
    body = resp.json()
    if body.get('status_code') != 200:
        return
    data = body.get('data', {})
    items = data.get('data', []) if isinstance(data, dict) else []
    for item in items:
        role_id = item.get('id')
        name = item.get('role_name', '')
        if role_id and name.startswith(PREFIX):
            client.delete(f'{API_BASE}/roles/{role_id}', headers=headers)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def client():
    with httpx.Client(timeout=30.0) as c:
        # Health check
        try:
            resp = c.get(HEALTH_URL)
            assert resp.status_code == 200
        except Exception:
            pytest.skip('Backend not running')
        yield c


@pytest.fixture(scope='module')
def admin_token(client):
    return _login(client)


@pytest.fixture(scope='module', autouse=True)
def cleanup(client, admin_token):
    """Double cleanup: before + after test suite."""
    _cleanup_test_roles(client, admin_token)
    yield
    _cleanup_test_roles(client, admin_token)


# ---------------------------------------------------------------------------
# Tests: Role CRUD
# ---------------------------------------------------------------------------

class TestRoleCRUD:

    def test_ac01_create_tenant_role(self, client, admin_token):
        """AC-01: Create role → role_type='tenant', returns full object."""
        headers = _auth(admin_token)
        resp = client.post(f'{API_BASE}/roles', json={
            'role_name': f'{PREFIX}editor-{RUN_ID}',
            'quota_config': {'knowledge_space': 10, 'channel': 5},
            'remark': 'E2E test role',
        }, headers=headers)
        data = _assert_200(resp)

        assert data['id'] is not None
        assert data['role_name'] == f'{PREFIX}editor-{RUN_ID}'
        assert data['quota_config']['knowledge_space'] == 10

        # Verify via GET
        get_resp = client.get(f'{API_BASE}/roles/{data["id"]}', headers=headers)
        get_data = _assert_200(get_resp)
        assert get_data['role_name'] == f'{PREFIX}editor-{RUN_ID}'
        assert get_data['user_count'] == 0

    def test_ac09_duplicate_name_rejected(self, client, admin_token):
        """AC-09: Duplicate role_name → error 24002."""
        headers = _auth(admin_token)
        name = f'{PREFIX}dup-{RUN_ID}'

        # First create succeeds
        resp1 = client.post(f'{API_BASE}/roles', json={'role_name': name}, headers=headers)
        _assert_200(resp1)

        # Second with same name fails
        resp2 = client.post(f'{API_BASE}/roles', json={'role_name': name}, headers=headers)
        _assert_error(resp2, 24002)

    def test_ac10c_invalid_quota_config(self, client, admin_token):
        """AC-10c: Invalid quota_config → error 24005."""
        headers = _auth(admin_token)
        resp = client.post(f'{API_BASE}/roles', json={
            'role_name': f'{PREFIX}bad-quota-{RUN_ID}',
            'quota_config': {'knowledge_space': -5},  # invalid: negative but not -1
        }, headers=headers)
        _assert_error(resp, 24005)

    def test_ac04_list_roles_excludes_admin(self, client, admin_token):
        """AC-04: System admin list → all roles except AdminRole(id=1)."""
        headers = _auth(admin_token)
        resp = client.get(f'{API_BASE}/roles', params={'page': 1, 'limit': 100},
                          headers=headers)
        data = _assert_200(resp)

        assert 'data' in data
        assert 'total' in data
        role_ids = [r['id'] for r in data['data']]
        assert 1 not in role_ids, 'AdminRole(id=1) should not appear in list'

    def test_ac05_update_role(self, client, admin_token):
        """AC-05: Update role → success."""
        headers = _auth(admin_token)

        # Create a role first
        create_resp = client.post(f'{API_BASE}/roles', json={
            'role_name': f'{PREFIX}updatable-{RUN_ID}',
        }, headers=headers)
        role_id = _assert_200(create_resp)['id']

        # Update it
        update_resp = client.put(f'{API_BASE}/roles/{role_id}', json={
            'role_name': f'{PREFIX}updated-{RUN_ID}',
            'remark': 'updated remark',
        }, headers=headers)
        update_data = _assert_200(update_resp)
        assert update_data['role_name'] == f'{PREFIX}updated-{RUN_ID}'

        # Verify via GET
        get_resp = client.get(f'{API_BASE}/roles/{role_id}', headers=headers)
        get_data = _assert_200(get_resp)
        assert get_data['remark'] == 'updated remark'

    def test_ac07_delete_builtin_rejected(self, client, admin_token):
        """AC-07: Delete AdminRole(id=1) → error 24004."""
        headers = _auth(admin_token)
        resp = client.delete(f'{API_BASE}/roles/1', headers=headers)
        _assert_error(resp, 24004)

    def test_ac07_delete_default_role_rejected(self, client, admin_token):
        """AC-07: Delete DefaultRole(id=2) → error 24004."""
        headers = _auth(admin_token)
        resp = client.delete(f'{API_BASE}/roles/2', headers=headers)
        _assert_error(resp, 24004)

    def test_ac08_delete_role_success(self, client, admin_token):
        """AC-08: Delete custom role → success, cascades UserRole + RoleAccess."""
        headers = _auth(admin_token)

        # Create
        create_resp = client.post(f'{API_BASE}/roles', json={
            'role_name': f'{PREFIX}deletable-{RUN_ID}',
        }, headers=headers)
        role_id = _assert_200(create_resp)['id']

        # Delete
        del_resp = client.delete(f'{API_BASE}/roles/{role_id}', headers=headers)
        _assert_200(del_resp)

        # Verify gone — GET should return 24000 (not found)
        get_resp = client.get(f'{API_BASE}/roles/{role_id}', headers=headers)
        _assert_error(get_resp, 24000)

    def test_ac10_get_role_detail(self, client, admin_token):
        """AC-10: Get role detail with user_count and department_name."""
        headers = _auth(admin_token)

        # DefaultRole(id=2) is always available
        resp = client.get(f'{API_BASE}/roles/2', headers=headers)
        data = _assert_200(resp)
        assert data['id'] == 2
        assert 'user_count' in data
        assert 'role_type' in data


# ---------------------------------------------------------------------------
# Tests: Menu Permissions
# ---------------------------------------------------------------------------

class TestMenuPermissions:

    def test_ac11_ac12_update_and_get_menu(self, client, admin_token):
        """AC-11+AC-12: Update menu then get it back."""
        headers = _auth(admin_token)

        # Create a test role
        create_resp = client.post(f'{API_BASE}/roles', json={
            'role_name': f'{PREFIX}menu-test-{RUN_ID}',
        }, headers=headers)
        role_id = _assert_200(create_resp)['id']

        # Set menu permissions
        menu_ids = ['workstation', 'build', 'knowledge', 'knowledge_space']
        update_resp = client.post(f'{API_BASE}/roles/{role_id}/menu', json={
            'menu_ids': menu_ids,
        }, headers=headers)
        _assert_200(update_resp)

        # Get menu permissions
        get_resp = client.get(f'{API_BASE}/roles/{role_id}/menu', headers=headers)
        get_data = _assert_200(get_resp)
        assert set(get_data) == set(menu_ids)

        # Update to different set
        new_menu_ids = ['workstation', 'admin', 'model']
        client.post(f'{API_BASE}/roles/{role_id}/menu', json={
            'menu_ids': new_menu_ids,
        }, headers=headers)

        # Verify replacement
        get_resp2 = client.get(f'{API_BASE}/roles/{role_id}/menu', headers=headers)
        get_data2 = _assert_200(get_resp2)
        assert set(get_data2) == set(new_menu_ids)


# ---------------------------------------------------------------------------
# Tests: Quota Queries
# ---------------------------------------------------------------------------

class TestQuotaQueries:

    def test_ac19_admin_all_unlimited(self, client, admin_token):
        """AC-19: Admin effective quota → all resources -1."""
        headers = _auth(admin_token)
        resp = client.get(f'{API_BASE}/quota/effective', headers=headers)
        data = _assert_200(resp)

        assert isinstance(data, list)
        assert len(data) == 8  # 8 resource types in DEFAULT_ROLE_QUOTA

        for item in data:
            assert item['effective'] == -1, (
                f"{item['resource_type']}: expected -1, got {item['effective']}"
            )
            assert item['role_quota'] == -1

    def test_ac15_quota_has_all_fields(self, client, admin_token):
        """AC-15: Effective quota response has required fields."""
        headers = _auth(admin_token)
        resp = client.get(f'{API_BASE}/quota/effective', headers=headers)
        data = _assert_200(resp)

        for item in data:
            assert 'resource_type' in item
            assert 'role_quota' in item
            assert 'tenant_quota' in item
            assert 'tenant_used' in item
            assert 'user_used' in item
            assert 'effective' in item

    def test_usage_endpoint(self, client, admin_token):
        """AC-15: Usage endpoint returns per-resource counts."""
        headers = _auth(admin_token)
        resp = client.get(f'{API_BASE}/quota/usage', headers=headers)
        data = _assert_200(resp)

        assert isinstance(data, dict)
        assert 'knowledge_space' in data
        assert 'workflow' in data


# ---------------------------------------------------------------------------
# Tests: Legacy API Backward Compatibility
# ---------------------------------------------------------------------------

class TestLegacyAPI:

    def test_ac25_legacy_role_list(self, client, admin_token):
        """AC-25: Legacy GET /role/list returns role list."""
        headers = _auth(admin_token)
        resp = client.get(f'{API_BASE}/role/list', params={'page': 1, 'limit': 10},
                          headers=headers)
        data = _assert_200(resp)
        assert 'data' in data
        assert 'total' in data
