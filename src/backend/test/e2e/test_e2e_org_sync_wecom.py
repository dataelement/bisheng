"""E2E tests for F021: WeCom Org Sync Provider.

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE env var)
- Default admin account: admin/Bisheng@top1 (or E2E_ADMIN_PASSWORD env var)

Two coverage tiers:
1. **Schema / CRUD E2E (always runs)** — validates AC-35~AC-38 through the
   public REST API: missing-field rejection, allow_dept_ids validation,
   response masking, partial-update merge semantics.
2. **Live WeCom E2E (opt-in)** — activates when the env var
   `E2E_WECOM_TEST_LIVE=1` is set along with real credentials. Exercises
   AC-39 test_connection. Skipped by default to keep CI offline-safe.

All created configs use the 'e2e-f021-' prefix for isolation.
"""

import os
import time

import httpx
import pytest

API_BASE = os.environ.get('E2E_API_BASE', 'http://localhost:7860/api/v1')
HEALTH_URL = API_BASE.replace('/api/v1', '') + '/health'
PREFIX = 'e2e-f021-'


# ---------------------------------------------------------------------------
# Auth helpers (reused style from test_e2e_org_sync.py)
# ---------------------------------------------------------------------------

def _login(client: httpx.Client, username: str = 'admin', password: str = None) -> str:
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

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
    client = httpx.Client(base_url=API_BASE, timeout=30)
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


VALID_WECOM_AUTH = {
    'corpid': 'wwe2etestCORPID',
    'corpsecret': 'e2e-test-SECRET-do-not-use-in-prod',
    'agent_id': '1000017',
    'allow_dept_ids': [1],
}


@pytest.fixture
def cleanup_ids():
    """Collect config ids and soft-delete them after the test."""
    ids: list[int] = []
    yield ids
    # Best-effort cleanup — ignore failures (test may have deleted already).


def _delete_config(client: httpx.Client, config_id: int) -> None:
    try:
        client.delete(f'/org-sync/configs/{config_id}')
    except httpx.HTTPError:
        pass


# ---------------------------------------------------------------------------
# Tier 1: Schema / CRUD E2E (always-run)
# ---------------------------------------------------------------------------

class TestWeComConfigCRUD:

    @pytest.mark.parametrize('missing', ['corpid', 'corpsecret', 'agent_id'])
    def test_create_missing_required_field_rejected(self, admin_client, missing):
        """AC-36: missing a required field → 22006 (or 422)."""
        bad = {k: v for k, v in VALID_WECOM_AUTH.items() if k != missing}
        resp = admin_client.post('/org-sync/configs', json={
            'provider': 'wecom',
            'config_name': f'{PREFIX}missing-{missing}-{int(time.time())}',
            'auth_type': 'api_key',
            'auth_config': bad,
        })
        data = resp.json()
        # Pydantic returns 422 for shape violations at the entry layer,
        # 22006 when the validator is engaged.
        assert data['status_code'] in (22006, 500, 422), f'got {data}'

    def test_create_invalid_allow_dept_ids_rejected(self, admin_client):
        """AC-37: allow_dept_ids must be list[int]."""
        auth = {**VALID_WECOM_AUTH, 'allow_dept_ids': '1,2,3'}
        resp = admin_client.post('/org-sync/configs', json={
            'provider': 'wecom',
            'config_name': f'{PREFIX}bad-dept-{int(time.time())}',
            'auth_type': 'api_key',
            'auth_config': auth,
        })
        data = resp.json()
        assert data['status_code'] in (22006, 500, 422), f'got {data}'

    def test_full_wecom_lifecycle(self, admin_client, cleanup_ids):
        """AC-35/38: create → read masked → update (keeps secret) → delete."""
        name = f'{PREFIX}lifecycle-{int(time.time())}'
        resp = admin_client.post('/org-sync/configs', json={
            'provider': 'wecom',
            'config_name': name,
            'auth_type': 'api_key',
            'auth_config': VALID_WECOM_AUTH,
        })
        data = resp.json()
        assert data['status_code'] == 200, f'create failed: {data}'
        cid = data['data']['id']
        cleanup_ids.append(cid)

        try:
            # AC-38: corpsecret masked on read
            resp = admin_client.get(f'/org-sync/configs/{cid}')
            detail = resp.json()['data']
            assert detail['auth_config']['corpsecret'] == '****'
            assert detail['auth_config']['corpid'] == VALID_WECOM_AUTH['corpid']
            assert detail['auth_config']['agent_id'] == VALID_WECOM_AUTH['agent_id']
            assert detail['auth_config']['allow_dept_ids'] == [1]

            # AC-06 equivalent: submitting corpsecret=**** keeps stored value
            resp = admin_client.put(f'/org-sync/configs/{cid}', json={
                'auth_config': {
                    'corpid': 'wwUPDATED',
                    'corpsecret': '****',  # sentinel — preserve
                    'agent_id': '1000017',
                },
            })
            assert resp.json()['status_code'] == 200, resp.json()
            detail = admin_client.get(f'/org-sync/configs/{cid}').json()['data']
            assert detail['auth_config']['corpid'] == 'wwUPDATED'
            assert detail['auth_config']['corpsecret'] == '****'

            # Real-secret update works and is re-masked in response
            resp = admin_client.put(f'/org-sync/configs/{cid}', json={
                'auth_config': {'corpsecret': 'freshly-rotated-SECRET'},
            })
            assert resp.json()['status_code'] == 200
            detail = admin_client.get(f'/org-sync/configs/{cid}').json()['data']
            assert detail['auth_config']['corpsecret'] == '****'

            # _config_id leak attempt is silently dropped (never persisted)
            resp = admin_client.put(f'/org-sync/configs/{cid}', json={
                'auth_config': {'_config_id': 999},
            })
            detail = admin_client.get(f'/org-sync/configs/{cid}').json()['data']
            assert '_config_id' not in detail['auth_config']

        finally:
            _delete_config(admin_client, cid)

    def test_update_bad_allow_dept_ids_rejected(self, admin_client, cleanup_ids):
        """AC-37 on update path."""
        name = f'{PREFIX}upd-bad-dept-{int(time.time())}'
        resp = admin_client.post('/org-sync/configs', json={
            'provider': 'wecom',
            'config_name': name,
            'auth_type': 'api_key',
            'auth_config': VALID_WECOM_AUTH,
        })
        cid = resp.json()['data']['id']
        cleanup_ids.append(cid)

        try:
            resp = admin_client.put(f'/org-sync/configs/{cid}', json={
                'auth_config': {'allow_dept_ids': [1, 'bad']},
            })
            data = resp.json()
            assert data['status_code'] in (22006, 500, 422)
        finally:
            _delete_config(admin_client, cid)


# ---------------------------------------------------------------------------
# Tier 2: Live WeCom E2E (opt-in)
# ---------------------------------------------------------------------------

_LIVE_FLAG = os.environ.get('E2E_WECOM_TEST_LIVE') == '1'
_LIVE_CORPID = os.environ.get('E2E_WECOM_CORPID')
_LIVE_SECRET = os.environ.get('E2E_WECOM_CORPSECRET')
_LIVE_AGENT = os.environ.get('E2E_WECOM_AGENT_ID')


@pytest.mark.skipif(
    not (_LIVE_FLAG and _LIVE_CORPID and _LIVE_SECRET and _LIVE_AGENT),
    reason='Live WeCom E2E disabled (set E2E_WECOM_TEST_LIVE=1 + credentials)',
)
class TestWeComLiveConnection:

    def test_test_connection_with_real_credentials(
        self, admin_client, cleanup_ids,
    ):
        """AC-39: test_connection against the real WeCom API.

        Requires a reachable network from the backend host to
        qyapi.weixin.qq.com. Enable by setting E2E_WECOM_TEST_LIVE=1.
        """
        name = f'{PREFIX}live-{int(time.time())}'
        resp = admin_client.post('/org-sync/configs', json={
            'provider': 'wecom',
            'config_name': name,
            'auth_type': 'api_key',
            'auth_config': {
                'corpid': _LIVE_CORPID,
                'corpsecret': _LIVE_SECRET,
                'agent_id': _LIVE_AGENT,
                'allow_dept_ids': [1],
            },
        })
        cid = resp.json()['data']['id']
        cleanup_ids.append(cid)

        try:
            resp = admin_client.post(f'/org-sync/configs/{cid}/test')
            data = resp.json()
            assert data['status_code'] == 200, f'test failed: {data}'
            body = data['data']
            assert body['connected'] is True
            assert isinstance(body['total_depts'], int)
            assert isinstance(body['total_members'], int)
            # AC-58: never leak token / secret
            serialized = str(data)
            assert 'access_token' not in serialized.lower()
            assert _LIVE_SECRET not in serialized
        finally:
            _delete_config(admin_client, cid)
