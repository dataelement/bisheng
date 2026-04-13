from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.mcp_server.device_flow import McpDeviceSession, load_device_session_by_device_code
from bisheng.user.api.user import router


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def aset(self, key, value, expiration=3600):
        self.store[key] = value
        return True

    async def aget(self, key):
        return self.store.get(key)

    async def adelete(self, key):
        self.store.pop(key, None)
        return 1


def create_test_client():
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    return TestClient(app)


class TestMcpDeviceFlow(TestCase):
    def test_device_authorization_creates_codes(self):
        fake_redis = FakeRedis()
        client = create_test_client()

        with patch('bisheng.user.api.user.get_redis_client', AsyncMock(return_value=fake_redis)):
            response = client.post('/api/v1/user/mcp/device/authorize', json={
                'client_id': 'codex-cli',
                'client_name': 'Codex CLI',
                'scope': 'workflow.read workflow.write',
                'expires_in': 600,
                'interval': 5,
            })

        self.assertEqual(response.status_code, 200)
        payload = response.json()['data']
        self.assertEqual(payload['scope'], 'workflow.read workflow.write')
        self.assertIn('verification_uri_complete', payload)
        self.assertIn('device_code', payload)
        self.assertIn('user_code', payload)

    def test_device_token_returns_pending_before_approval(self):
        fake_redis = FakeRedis()
        client = create_test_client()

        with patch('bisheng.user.api.user.get_redis_client', AsyncMock(return_value=fake_redis)):
            created = client.post('/api/v1/user/mcp/device/authorize', json={
                'client_id': 'codex-cli',
                'scope': 'workflow.read',
            }).json()['data']
            response = client.post('/api/v1/user/mcp/device/token', json={
                'device_code': created['device_code'],
                'client_id': 'codex-cli',
            })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'authorization_pending')

    def test_verify_page_requires_login_before_approval(self):
        fake_redis = FakeRedis()
        client = create_test_client()

        with patch('bisheng.user.api.user.get_redis_client', AsyncMock(return_value=fake_redis)):
            created = client.post('/api/v1/user/mcp/device/authorize', json={
                'client_id': 'codex-cli',
                'client_name': 'Codex CLI',
            }).json()['data']
            response = client.get(f"/api/v1/user/mcp/device/verify?user_code={created['user_code']}")

        self.assertEqual(response.status_code, 200)
        self.assertIn('Login required', response.text)

    def test_verify_and_exchange_device_token(self):
        fake_redis = FakeRedis()
        client = create_test_client()

        with patch('bisheng.user.api.user.get_redis_client', AsyncMock(return_value=fake_redis)):
            created = client.post('/api/v1/user/mcp/device/authorize', json={
                'client_id': 'codex-cli',
                'client_name': 'Codex CLI',
                'scope': 'workflow.read workflow.write',
            }).json()['data']

            with patch('bisheng.user.api.user.get_request_bisheng_access_token', return_value='parent-access-token'), \
                    patch(
                        'bisheng.user.api.user.resolve_login_user_from_bisheng_access_token',
                        AsyncMock(return_value=SimpleNamespace(user_id=7, user_name='demo')),
                    ):
                approval = client.post('/api/v1/user/mcp/device/verify', data={
                    'user_code': created['user_code'],
                    'action': 'approve',
                })

            self.assertEqual(approval.status_code, 200)
            self.assertIn('Request approved', approval.text)

            token_response = client.post('/api/v1/user/mcp/device/token', json={
                'device_code': created['device_code'],
                'client_id': 'codex-cli',
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            })

        self.assertEqual(token_response.status_code, 200)
        token_payload = token_response.json()
        self.assertEqual(token_payload['token_type'], 'Bearer')
        self.assertEqual(token_payload['scope'], 'workflow.read workflow.write')
        self.assertEqual(token_payload['mcp_url'], '/mcp')
        self.assertTrue(token_payload['access_token'])


class TestMcpDeviceFlowStorage(IsolatedAsyncioTestCase):
    async def test_approved_session_is_persisted(self):
        fake_redis = FakeRedis()
        session = McpDeviceSession(
            device_code='device-code',
            user_code='ABCD-EFGH',
            client_id='codex-cli',
            scopes=['workflow.read'],
            expires_at=4102444800,
        )
        fake_redis.store['mcp:device:code:device-code'] = session.model_dump()
        stored = await load_device_session_by_device_code(fake_redis, 'device-code')
        self.assertIsNotNone(stored)
        self.assertEqual(stored.user_code, 'ABCD-EFGH')
