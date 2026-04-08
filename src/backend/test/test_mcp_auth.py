from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
import jwt

from bisheng.common.exceptions.auth import JWTDecodeError
from bisheng.mcp_server import auth as mcp_auth
from bisheng.mcp_server.auth import McpAuthorizationMiddleware, create_mcp_access_token, get_login_user_from_mcp_token
from bisheng.user.domain.services.auth import AuthJwt


def create_test_client():
    app = FastAPI()

    @app.get('/secure')
    async def secure():
        login_user = await get_login_user_from_mcp_token()
        return {
            'user_id': login_user.user_id,
            'user_name': login_user.user_name,
        }

    @app.websocket('/ws')
    async def secure_websocket(websocket: WebSocket):
        login_user = await get_login_user_from_mcp_token()
        await websocket.accept()
        await websocket.send_json({
            'user_id': login_user.user_id,
            'user_name': login_user.user_name,
        })
        await websocket.close()

    return TestClient(McpAuthorizationMiddleware(app))


class TestMcpAuthorizationMiddleware(TestCase):
    def test_missing_bearer_token_returns_401(self):
        client = create_test_client()

        response = client.get('/secure')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'invalid_request')
        self.assertIn('WWW-Authenticate', response.headers)
        self.assertIn('Bearer realm="bisheng-mcp"', response.headers['WWW-Authenticate'])

    def test_invalid_bearer_token_returns_401(self):
        client = create_test_client()

        with patch('bisheng.mcp_server.auth._validate_mcp_access_token',
                   AsyncMock(side_effect=JWTDecodeError(status_code=422, message='bad token'))):
            response = client.get('/secure', headers={'Authorization': 'Bearer invalid-token'})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'invalid_token')

    def test_valid_bearer_token_populates_login_user(self):
        client = create_test_client()

        with patch(
            'bisheng.mcp_server.auth._validate_mcp_access_token',
            AsyncMock(return_value=(SimpleNamespace(user_id=7, user_name='admin'), ('workflow.read',))),
        ):
            response = client.get('/secure', headers={'Authorization': 'Bearer valid-token'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'user_id': 7, 'user_name': 'admin'})

    def test_cross_origin_request_is_rejected(self):
        client = create_test_client()

        with patch(
            'bisheng.mcp_server.auth._validate_mcp_access_token',
            AsyncMock(return_value=(SimpleNamespace(user_id=7, user_name='admin'), ('workflow.read',))),
        ):
            response = client.get(
                '/secure',
                headers={
                    'Authorization': 'Bearer valid-token',
                    'Origin': 'https://evil.example.com',
                    'Host': '127.0.0.1:7860',
                },
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error'], 'forbidden_origin')

    def test_valid_websocket_bearer_token_populates_login_user(self):
        client = create_test_client()

        with patch(
            'bisheng.mcp_server.auth._validate_mcp_access_token',
            AsyncMock(return_value=(SimpleNamespace(user_id=7, user_name='admin'), ('workflow.read',))),
        ):
            with client.websocket_connect('/ws', headers={'Authorization': 'Bearer valid-token'}) as websocket:
                self.assertEqual(websocket.receive_json(), {'user_id': 7, 'user_name': 'admin'})


class TestMcpAccessToken(IsolatedAsyncioTestCase):
    async def test_create_and_validate_mcp_token(self):
        login_user = SimpleNamespace(user_id=7, user_name='admin')

        token, payload = create_mcp_access_token(
            login_user,
            'parent-access-token',
            scopes=['workflow.read', 'workflow.write'],
            expires_in=600,
        )

        fake_redis = SimpleNamespace(aget=AsyncMock(return_value='parent-access-token'))
        resolved_user = SimpleNamespace(user_id=7, user_name='admin')
        with patch('bisheng.mcp_server.auth.get_redis_client', AsyncMock(return_value=fake_redis)), \
                patch('bisheng.mcp_server.auth.UserPayload.init_login_user',
                      AsyncMock(return_value=resolved_user)):
            user, scopes = await mcp_auth._validate_mcp_access_token(token)

        self.assertEqual(user.user_id, 7)
        self.assertEqual(user.user_name, 'admin')
        self.assertEqual(scopes, ('workflow.read', 'workflow.write'))
        self.assertEqual(payload['scopes'], ['workflow.read', 'workflow.write'])

    async def test_validate_mcp_token_uses_top_level_user_claims(self):
        login_user = SimpleNamespace(user_id=7, user_name='admin')
        token, _ = create_mcp_access_token(login_user, 'parent-access-token')
        fake_redis = SimpleNamespace(aget=AsyncMock(return_value='parent-access-token'))
        resolved_user = SimpleNamespace(user_id=7, user_name='admin')

        with patch('bisheng.mcp_server.auth.get_redis_client', AsyncMock(return_value=fake_redis)), \
                patch('bisheng.mcp_server.auth.UserPayload.init_login_user',
                      AsyncMock(return_value=resolved_user)):
            user, scopes = await mcp_auth._validate_mcp_access_token(token)

        self.assertEqual(user.user_id, 7)
        self.assertEqual(user.user_name, 'admin')
        self.assertEqual(scopes, ('workflow.read', 'workflow.write', 'workflow.publish'))

    async def test_validate_mcp_token_rejects_non_json_legacy_subject(self):
        token = jwt.encode({
            'sub': '7',
            'iss': 'bisheng-mcp',
            'aud': 'bisheng-workflow-mcp',
            'iat': 1,
            'exp': 9999999999,
            'jti': 'bad-token',
            'token_type': 'mcp_access_token',
            'scope': ['workflow.read'],
            'parent_session_hash': 'hash',
        }, AuthJwt().jwt_secret, algorithm='HS256')

        with self.assertRaises(JWTDecodeError):
            await mcp_auth._validate_mcp_access_token(token)
