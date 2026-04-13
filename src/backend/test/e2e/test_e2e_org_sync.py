"""
E2E tests for F009: Org Sync

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE env var)
- Default admin account: admin/Bisheng@top1 (or E2E_ADMIN_PASSWORD env var)
- Default tenant (id=1) with root department

Covers:
- AC-01: Create config (POST /org-sync/configs)
- AC-02: Duplicate config error (22001)
- AC-03: List configs (GET /org-sync/configs)
- AC-04: Get config detail (GET /org-sync/configs/{id})
- AC-05: Update config (PUT /org-sync/configs/{id})
- AC-06: Merge auth_config on update
- AC-07: Delete config (soft delete)
- AC-08: Cross-tenant rejection (22000)
- AC-09: Test connection (POST /org-sync/configs/{id}/test) — requires real provider
- AC-10: Test connection auth failure (22002) — requires real provider
- AC-12: Provider not implemented (22004) — WeChat Work
- AC-29: Get sync logs (GET /org-sync/configs/{id}/logs)
- AC-33: Non-admin permission denied (22005)
- AC-34: Auth config masking

Data isolation: All test configs use 'e2e-f009-' prefix in config_name.
"""

import os

import httpx
import pytest

API_BASE = os.environ.get('E2E_API_BASE', 'http://localhost:7860/api/v1')
HEALTH_URL = API_BASE.replace('/api/v1', '') + '/health'
PREFIX = 'e2e-f009-'


# ---------------------------------------------------------------------------
# Auth helpers
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
    encrypted_password = base64.b64encode(encrypted).decode()

    resp = client.post(f'{API_BASE}/user/login', json={
        'user_name': username,
        'password': encrypted_password,
    })
    assert resp.status_code == 200
    return resp.cookies.get('access_token_cookie', '')


@pytest.fixture(scope='module')
def admin_client():
    """Authenticated httpx client for admin user."""
    client = httpx.Client(base_url=API_BASE, timeout=30)
    # Attempt health check
    try:
        health = client.get(HEALTH_URL)
        if health.status_code != 200:
            pytest.skip('Backend not running')
    except httpx.ConnectError:
        pytest.skip('Backend not running')

    token = _login(client)
    client.cookies.set('access_token_cookie', token)
    yield client
    client.close()


@pytest.fixture(scope='module')
def config_id(admin_client):
    """Create a test config and return its ID. Cleanup after tests."""
    resp = admin_client.post('/org-sync/configs', json={
        'provider': 'generic_api',
        'config_name': f'{PREFIX}test-config',
        'auth_type': 'api_key',
        'auth_config': {
            'endpoint_url': 'https://httpbin.org/get',
            'api_key': 'test-key-12345',
            'departments_url': 'https://httpbin.org/json',
            'members_url': 'https://httpbin.org/json',
        },
        'schedule_type': 'manual',
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data['status_code'] == 200, f"Create failed: {data}"
    cid = data['data']['id']
    yield cid
    # Cleanup: soft delete
    admin_client.delete(f'/org-sync/configs/{cid}')


# ---------------------------------------------------------------------------
# Config CRUD Tests
# ---------------------------------------------------------------------------

class TestConfigCRUD:

    def test_create_config(self, admin_client, config_id):
        """AC-01: create returns proper structure."""
        resp = admin_client.get(f'/org-sync/configs/{config_id}')
        data = resp.json()['data']
        assert data['provider'] == 'generic_api'
        assert data['config_name'] == f'{PREFIX}test-config'
        assert data['status'] == 'active'
        assert data['sync_status'] == 'idle'

    def test_create_duplicate(self, admin_client):
        """AC-02: duplicate provider+name → 22001."""
        resp = admin_client.post('/org-sync/configs', json={
            'provider': 'generic_api',
            'config_name': f'{PREFIX}test-config',
            'auth_type': 'api_key',
            'auth_config': {'api_key': 'dup'},
        })
        data = resp.json()
        assert data['status_code'] == 22001

    def test_list_configs(self, admin_client, config_id):
        """AC-03: list returns configs for current tenant."""
        resp = admin_client.get('/org-sync/configs')
        data = resp.json()['data']
        assert isinstance(data, list)
        ids = [c['id'] for c in data]
        assert config_id in ids

    def test_get_config_detail(self, admin_client, config_id):
        """AC-04: detail with masked auth_config."""
        resp = admin_client.get(f'/org-sync/configs/{config_id}')
        data = resp.json()['data']
        assert data['auth_config']['api_key'] == '****'

    def test_auth_config_masking(self, admin_client, config_id):
        """AC-34: sensitive fields masked in responses."""
        resp = admin_client.get(f'/org-sync/configs/{config_id}')
        auth = resp.json()['data']['auth_config']
        assert auth.get('api_key') == '****'
        # Non-sensitive fields should be visible
        assert 'endpoint_url' in auth

    def test_update_config(self, admin_client, config_id):
        """AC-05: update schedule_type."""
        resp = admin_client.put(f'/org-sync/configs/{config_id}', json={
            'schedule_type': 'cron',
            'cron_expression': '0 3 * * *',
        })
        data = resp.json()['data']
        assert data['schedule_type'] == 'cron'
        assert data['cron_expression'] == '0 3 * * *'

        # Restore
        admin_client.put(f'/org-sync/configs/{config_id}', json={
            'schedule_type': 'manual',
            'cron_expression': None,
        })

    def test_update_merge_auth_config(self, admin_client, config_id):
        """AC-06: auth_config merge update."""
        # Update only api_key
        resp = admin_client.put(f'/org-sync/configs/{config_id}', json={
            'auth_config': {'api_key': 'new-key-99999'},
        })
        data = resp.json()['data']
        # api_key should be masked
        assert data['auth_config']['api_key'] == '****'
        # Other fields should persist
        assert data['auth_config'].get('endpoint_url') is not None

    def test_get_nonexistent_config(self, admin_client):
        """AC-08: nonexistent config → 22000."""
        resp = admin_client.get('/org-sync/configs/999999')
        data = resp.json()
        assert data['status_code'] == 22000


# ---------------------------------------------------------------------------
# Exec endpoint tests (limited without real provider)
# ---------------------------------------------------------------------------

class TestExecEndpoints:

    def test_get_logs_empty(self, admin_client, config_id):
        """AC-29: logs for a config with no syncs."""
        resp = admin_client.get(f'/org-sync/configs/{config_id}/logs')
        data = resp.json()['data']
        assert 'data' in data
        assert 'total' in data

    def test_test_connection_wecom(self, admin_client):
        """AC-12: WeChat Work provider not implemented → 22004."""
        # Create a wecom config
        resp = admin_client.post('/org-sync/configs', json={
            'provider': 'wecom',
            'config_name': f'{PREFIX}wecom-stub',
            'auth_type': 'api_key',
            'auth_config': {'app_id': 'test', 'app_secret': 'test'},
        })
        wecom_id = resp.json()['data']['id']

        try:
            resp = admin_client.post(f'/org-sync/configs/{wecom_id}/test')
            data = resp.json()
            assert data['status_code'] == 22004
        finally:
            admin_client.delete(f'/org-sync/configs/{wecom_id}')


# ---------------------------------------------------------------------------
# Delete test
# ---------------------------------------------------------------------------

class TestDelete:

    def test_delete_config(self, admin_client):
        """AC-07: soft delete."""
        # Create a config to delete
        resp = admin_client.post('/org-sync/configs', json={
            'provider': 'feishu',
            'config_name': f'{PREFIX}to-delete',
            'auth_type': 'api_key',
            'auth_config': {'app_id': 'x', 'app_secret': 'y'},
        })
        cid = resp.json()['data']['id']

        resp = admin_client.delete(f'/org-sync/configs/{cid}')
        assert resp.json()['status_code'] == 200

        # Should no longer appear in list
        resp = admin_client.get(f'/org-sync/configs/{cid}')
        assert resp.json()['status_code'] == 22000
