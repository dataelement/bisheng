from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.exceptions.auth import JWTDecodeError
from bisheng.mcp_server.auth import McpAuthorizationMiddleware, get_login_user_from_mcp_token


def create_test_client():
    app = FastAPI()

    @app.get('/secure')
    async def secure():
        login_user = await get_login_user_from_mcp_token()
        return {
            'user_id': login_user.user_id,
            'user_name': login_user.user_name,
        }

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

        with patch('bisheng.mcp_server.auth._resolve_login_user_from_token',
                   AsyncMock(side_effect=JWTDecodeError(status_code=422, message='bad token'))):
            response = client.get('/secure', headers={'Authorization': 'Bearer invalid-token'})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'invalid_token')

    def test_valid_bearer_token_populates_login_user(self):
        client = create_test_client()

        with patch(
            'bisheng.mcp_server.auth._resolve_login_user_from_token',
            AsyncMock(return_value=SimpleNamespace(user_id=7, user_name='admin')),
        ):
            response = client.get('/secure', headers={'Authorization': 'Bearer valid-token'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'user_id': 7, 'user_name': 'admin'})

    def test_cross_origin_request_is_rejected(self):
        client = create_test_client()

        with patch(
            'bisheng.mcp_server.auth._resolve_login_user_from_token',
            AsyncMock(return_value=SimpleNamespace(user_id=7, user_name='admin')),
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
