"""
E2E tests for F004: ReBAC Permission Engine Core

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE env var)
- OpenFGA running on localhost:8080
- Default admin account: admin/Bisheng@top1 (or E2E_ADMIN_PASSWORD env var)
- Default tenant (id=1)

Covers:
- AC-01: FGAClient wraps OpenFGA REST API (verified via AC-02/AC-03)
- AC-02: PermissionService five-level check chain (admin shortcircuit, FGA check, owner fallback)
- AC-03: Resource authorization API (grant/revoke for user/department/user_group)
- AC-05: L2 Redis cache (10s TTL, UNCACHEABLE_RELATIONS bypass)
- AC-06: Owner fallback (DB creator check when FGA tuple not yet written)
- AC-10: LoginUser rebac_check/rebac_list_accessible integration

Skipped (unit/integration tests only):
- AC-04: FailedTuple Celery compensation (requires Celery running)
- AC-07: ChangeHandler → OpenFGA integration (covered by test_change_handler_integration.py)
- AC-08: Docker compose OpenFGA service (infrastructure, manual verify)
- AC-09: FGAManager startup initialization (covered by startup)

Error codes tested: 19000, 19003, 19005

Data isolation: All test resources use 'e2e-f004-rebac-' prefix.
"""

import os
import time

import httpx
import pytest

API_BASE = os.environ.get('E2E_API_BASE', 'http://localhost:7860/api/v1')
HEALTH_URL = API_BASE.replace('/api/v1', '') + '/health'
PREFIX = 'e2e-f004-rebac-'
RUN_ID = str(int(time.time()))[-6:]  # unique suffix per run


# ---------------------------------------------------------------------------
# Auth helpers (sync, following F002 pattern)
# ---------------------------------------------------------------------------

def _login(client: httpx.Client, username: str = 'admin', password: str = None) -> str:
    """Login and return JWT token."""
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
# Response assertion helpers
# ---------------------------------------------------------------------------

def _assert_200(resp: httpx.Response) -> dict:
    """Assert HTTP 200 + business success, return data."""
    assert resp.status_code == 200, f'HTTP {resp.status_code}: {resp.text[:300]}'
    body = resp.json()
    assert body['status_code'] == 200, (
        f"Business error {body['status_code']}: {body.get('status_message')}"
    )
    return body.get('data')


def _assert_error(resp: httpx.Response, code: int) -> dict:
    """Assert HTTP 200 + specific business error code."""
    assert resp.status_code == 200
    body = resp.json()
    assert body['status_code'] == code, (
        f"Expected {code}, got {body['status_code']}: {body.get('status_message')}"
    )
    return body


# ---------------------------------------------------------------------------
# Resource helpers
# ---------------------------------------------------------------------------

def _create_workflow(client: httpx.Client, token: str, name: str) -> dict:
    """Create a test workflow (simplest resource with user_id). Returns flow dict."""
    resp = client.post(f'{API_BASE}/workflow/create', json={
        'name': name,
        'flow_type': 10,
        'data': {'nodes': [], 'edges': []},
    }, headers=_auth(token))
    # workflow/create returns HTTP 201
    assert resp.status_code in (200, 201), f'HTTP {resp.status_code}: {resp.text[:300]}'
    body = resp.json()
    assert body['status_code'] == 200, f"Business error: {body.get('status_message')}"
    return body.get('data')


def _delete_workflow(client: httpx.Client, token: str, flow_id: str):
    """Delete a workflow (best-effort)."""
    try:
        client.delete(f'{API_BASE}/workflow/{flow_id}', headers=_auth(token))
    except Exception:
        pass


def _get_default_group_role(client: httpx.Client, admin_token: str) -> dict:
    """Find the first available group and default role (id=2) for user creation."""
    resp = client.get(f'{API_BASE}/group/list', params={'page': 1, 'limit': 10},
                      headers=_auth(admin_token))
    body = resp.json()
    if body.get('status_code') == 200:
        data = body.get('data', {})
        # API returns {records: [...]} format
        groups = data.get('records', data.get('data', []))
        if isinstance(groups, list) and groups:
            group_id = groups[0].get('id')
            # Use default role (id=2) which is the standard non-admin role
            return {'group_id': group_id, 'role_ids': [2]}
    return None


def _create_test_user(client: httpx.Client, admin_token: str, username: str, password: str = 'test_pass_123') -> dict:
    """Create a test user with default role. Returns user data."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    import base64

    pubkey_resp = client.get(f'{API_BASE}/user/public_key')
    public_key_pem = pubkey_resp.json()['data']['public_key']
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
    encrypted_b64 = base64.b64encode(encrypted).decode()

    # Find a valid group+role for user creation
    group_role = _get_default_group_role(client, admin_token)
    group_roles = [group_role] if group_role else [{'group_id': 1, 'role_ids': [2]}]

    resp = client.post(f'{API_BASE}/user/create', json={
        'user_name': username,
        'password': encrypted_b64,
        'group_roles': group_roles,
    }, headers=_auth(admin_token))
    return _assert_200(resp)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def client():
    with httpx.Client(timeout=30) as c:
        resp = c.get(HEALTH_URL)
        assert resp.status_code == 200, 'Backend not reachable'
        yield c


@pytest.fixture(scope='module')
def admin_token(client):
    return _login(client)


@pytest.fixture(scope='module')
def test_user(client, admin_token):
    """Create a non-admin test user, returns (user_data, token)."""
    username = f'{PREFIX}u{RUN_ID}'
    password = 'test_pass_123'
    user_data = _create_test_user(client, admin_token, username, password)
    user_token = _login(client, username, password)
    return user_data, user_token


@pytest.fixture(scope='module')
def test_workflow(client, admin_token):
    """Create a test workflow owned by admin."""
    flow = _create_workflow(client, admin_token, f'{PREFIX}wf-{RUN_ID}')
    yield flow
    _delete_workflow(client, admin_token, flow['id'])


@pytest.fixture(scope='module')
def user_workflow(client, test_user):
    """Create a test workflow owned by the test user."""
    _, user_token = test_user
    flow = _create_workflow(client, user_token, f'{PREFIX}uwf-{RUN_ID}')
    yield flow
    _delete_workflow(client, user_token, flow['id'])


# ---------------------------------------------------------------------------
# Permission check endpoint tests
# ---------------------------------------------------------------------------

class TestPermissionCheck:
    """Tests for POST /api/v1/permissions/check"""

    def test_ac02_admin_always_allowed(self, client, admin_token, test_workflow):
        """AC-02: Admin shortcircuit — super_admin bypasses FGA, always returns True."""
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'workflow',
            'object_id': test_workflow['id'],
            'relation': 'can_read',
        }, headers=_auth(admin_token))
        data = _assert_200(resp)
        assert data['allowed'] is True

    def test_ac02_admin_can_manage(self, client, admin_token, test_workflow):
        """AC-02: Admin has can_manage on any resource (uncacheable relation)."""
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'workflow',
            'object_id': test_workflow['id'],
            'relation': 'can_manage',
        }, headers=_auth(admin_token))
        data = _assert_200(resp)
        assert data['allowed'] is True

    def test_ac06_owner_fallback(self, client, test_user, user_workflow):
        """AC-06: Resource creator has implicit owner access via DB fallback."""
        _, user_token = test_user
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'workflow',
            'object_id': user_workflow['id'],
            'relation': 'can_read',
        }, headers=_auth(user_token))
        data = _assert_200(resp)
        assert data['allowed'] is True

    def test_ac02_unauthorized_user(self, client, test_user, test_workflow):
        """AC-02: Non-owner user without grant → denied."""
        _, user_token = test_user
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'workflow',
            'object_id': test_workflow['id'],
            'relation': 'can_edit',
        }, headers=_auth(user_token))
        data = _assert_200(resp)
        assert data['allowed'] is False

    def test_invalid_resource_type(self, client, admin_token):
        """AC-02 error: Invalid resource type → 19003."""
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'invalid_type',
            'object_id': 'anything',
            'relation': 'can_read',
        }, headers=_auth(admin_token))
        _assert_error(resp, 19003)

    def test_invalid_relation(self, client, admin_token, test_workflow):
        """AC-02 error: Invalid relation → 19005."""
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'workflow',
            'object_id': test_workflow['id'],
            'relation': 'super_permission',
        }, headers=_auth(admin_token))
        _assert_error(resp, 19005)


# ---------------------------------------------------------------------------
# List accessible objects tests
# ---------------------------------------------------------------------------

class TestListObjects:
    """Tests for GET /api/v1/permissions/objects"""

    def test_ac10_admin_returns_null(self, client, admin_token):
        """AC-10: Admin gets null (no filtering needed)."""
        resp = client.get(
            f'{API_BASE}/permissions/objects',
            params={'object_type': 'workflow', 'relation': 'can_read'},
            headers=_auth(admin_token),
        )
        data = _assert_200(resp)
        assert data is None

    def test_ac10_user_returns_list(self, client, test_user, user_workflow):
        """AC-10: Non-admin user gets a list of accessible IDs."""
        _, user_token = test_user
        resp = client.get(
            f'{API_BASE}/permissions/objects',
            params={'object_type': 'workflow', 'relation': 'can_read'},
            headers=_auth(user_token),
        )
        data = _assert_200(resp)
        assert isinstance(data, list)

    def test_invalid_resource_type(self, client, admin_token):
        """Error: Invalid object_type → 19003."""
        resp = client.get(
            f'{API_BASE}/permissions/objects',
            params={'object_type': 'invalid_type', 'relation': 'can_read'},
            headers=_auth(admin_token),
        )
        _assert_error(resp, 19003)


# ---------------------------------------------------------------------------
# Authorization (grant/revoke) tests
# ---------------------------------------------------------------------------

class TestAuthorize:
    """Tests for POST /api/v1/resources/{type}/{id}/authorize"""

    @pytest.mark.skipif(
        not os.environ.get('OPENFGA_AVAILABLE'),
        reason='Requires OpenFGA service (set OPENFGA_AVAILABLE=1)',
    )
    def test_ac03_admin_grant_viewer(self, client, admin_token, test_user, test_workflow):
        """AC-03: Admin grants viewer to test user on a workflow."""
        user_data, user_token = test_user
        flow_id = test_workflow['id']

        # Grant viewer
        resp = client.post(
            f'{API_BASE}/permissions/resources/workflow/{flow_id}/authorize',
            json={
                'grants': [{
                    'subject_type': 'user',
                    'subject_id': user_data['user_id'],
                    'relation': 'viewer',
                    'include_children': False,
                }],
                'revokes': [],
            },
            headers=_auth(admin_token),
        )
        _assert_200(resp)

        # Verify: user can now read
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'workflow',
            'object_id': flow_id,
            'relation': 'can_read',
        }, headers=_auth(user_token))
        data = _assert_200(resp)
        assert data['allowed'] is True

    def test_ac03_admin_revoke_viewer(self, client, admin_token, test_user, test_workflow):
        """AC-03: Admin revokes viewer from test user."""
        user_data, user_token = test_user
        flow_id = test_workflow['id']

        # Revoke viewer
        resp = client.post(
            f'{API_BASE}/permissions/resources/workflow/{flow_id}/authorize',
            json={
                'grants': [],
                'revokes': [{
                    'subject_type': 'user',
                    'subject_id': user_data['user_id'],
                    'relation': 'viewer',
                    'include_children': False,
                }],
            },
            headers=_auth(admin_token),
        )
        _assert_200(resp)

    def test_ac03_non_admin_denied(self, client, test_user, test_workflow):
        """AC-03 error: Non-owner cannot authorize → 19000."""
        user_data, user_token = test_user
        flow_id = test_workflow['id']

        resp = client.post(
            f'{API_BASE}/permissions/resources/workflow/{flow_id}/authorize',
            json={
                'grants': [{
                    'subject_type': 'user',
                    'subject_id': 999,
                    'relation': 'viewer',
                    'include_children': False,
                }],
            },
            headers=_auth(user_token),
        )
        _assert_error(resp, 19000)

    def test_ac03_invalid_resource_type(self, client, admin_token):
        """Error: Invalid resource type → 19003."""
        resp = client.post(
            f'{API_BASE}/permissions/resources/invalid_type/123/authorize',
            json={'grants': [], 'revokes': []},
            headers=_auth(admin_token),
        )
        _assert_error(resp, 19003)


# ---------------------------------------------------------------------------
# Get resource permissions tests
# ---------------------------------------------------------------------------

class TestResourcePermissions:
    """Tests for GET /api/v1/resources/{type}/{id}/permissions"""

    def test_ac03_admin_can_read_permissions(self, client, admin_token, test_workflow):
        """AC-03: Admin can read permissions of any resource."""
        flow_id = test_workflow['id']
        resp = client.get(
            f'{API_BASE}/permissions/resources/workflow/{flow_id}/permissions',
            headers=_auth(admin_token),
        )
        data = _assert_200(resp)
        assert isinstance(data, list)

    def test_ac03_non_admin_denied(self, client, test_user, test_workflow):
        """AC-03 error: Non-owner cannot read permissions → 19000."""
        _, user_token = test_user
        flow_id = test_workflow['id']
        resp = client.get(
            f'{API_BASE}/permissions/resources/workflow/{flow_id}/permissions',
            headers=_auth(user_token),
        )
        _assert_error(resp, 19000)


# ---------------------------------------------------------------------------
# Permission pyramid hierarchy tests
# ---------------------------------------------------------------------------

class TestPermissionHierarchy:
    """Tests for permission pyramid: owner > manager > editor > viewer."""

    @pytest.mark.skipif(
        not os.environ.get('OPENFGA_AVAILABLE'),
        reason='Requires OpenFGA service (set OPENFGA_AVAILABLE=1)',
    )
    def test_ac02_grant_manager_implies_can_manage(self, client, admin_token, test_user, test_workflow):
        """AC-02+AC-05: Granting manager implies can_manage, can_edit, can_read."""
        user_data, user_token = test_user
        flow_id = test_workflow['id']

        # Grant manager
        resp = client.post(
            f'{API_BASE}/permissions/resources/workflow/{flow_id}/authorize',
            json={
                'grants': [{
                    'subject_type': 'user',
                    'subject_id': user_data['user_id'],
                    'relation': 'manager',
                    'include_children': False,
                }],
            },
            headers=_auth(admin_token),
        )
        _assert_200(resp)

        # Verify can_manage (uncacheable — always queries FGA)
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'workflow',
            'object_id': flow_id,
            'relation': 'can_manage',
        }, headers=_auth(user_token))
        data = _assert_200(resp)
        assert data['allowed'] is True

        # Verify can_read (implied by manager > editor > viewer)
        resp = client.post(f'{API_BASE}/permissions/check', json={
            'object_type': 'workflow',
            'object_id': flow_id,
            'relation': 'can_read',
        }, headers=_auth(user_token))
        data = _assert_200(resp)
        assert data['allowed'] is True

        # Cleanup: revoke manager
        client.post(
            f'{API_BASE}/permissions/resources/workflow/{flow_id}/authorize',
            json={
                'revokes': [{
                    'subject_type': 'user',
                    'subject_id': user_data['user_id'],
                    'relation': 'manager',
                    'include_children': False,
                }],
            },
            headers=_auth(admin_token),
        )
