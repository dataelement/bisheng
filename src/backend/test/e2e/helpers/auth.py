"""E2E authentication helpers for BiSheng.

Handles RSA-encrypted login, JWT token retrieval, and test user creation.
"""

import base64
import os

import httpx

from test.e2e.helpers.api import API_BASE, assert_resp_200


# Default test admin password. 114 and other non-default-password deployments
# override via the ``E2E_ADMIN_PASSWORD`` env var (e.g. ``Bisheng@top1`` on
# 192.168.106.114). Local dev / CI leaves the helper's built-in default.
_DEFAULT_ADMIN_PASSWORD = 'admin123'
_DEFAULT_USER_PASSWORD = 'test_password_123'


async def get_public_key(client: httpx.AsyncClient) -> str:
    """Fetch RSA public key from backend."""
    resp = await client.get(f'{API_BASE}/user/public_key')
    data = assert_resp_200(resp)
    return data['public_key']


def encrypt_password(password: str, public_key_pem: str) -> str:
    """Encrypt password with RSA public key (PKCS1v15 padding)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    """Login and return JWT access token."""
    pubkey = await get_public_key(client)
    encrypted_pwd = encrypt_password(password, pubkey)

    resp = await client.post(
        f'{API_BASE}/user/login',
        json={'user_name': username, 'password': encrypted_pwd},
    )
    data = assert_resp_200(resp)
    return data['access_token']


async def get_admin_token(client: httpx.AsyncClient) -> str:
    """Get admin JWT token.

    Password resolution order:
      1. ``E2E_ADMIN_PASSWORD`` env var (set this on servers with non-default
         admin passwords, e.g. ``Bisheng@top1`` on 192.168.106.114).
      2. Hard-coded default ``admin123`` (local dev / CI).
    """
    password = os.environ.get('E2E_ADMIN_PASSWORD', _DEFAULT_ADMIN_PASSWORD)
    return await login(client, 'admin', password)


async def get_user_token(
    client: httpx.AsyncClient, username: str, password: str,
) -> str:
    """Get JWT token for a specific user."""
    return await login(client, username, password)


def auth_headers(token: str) -> dict:
    """Build authentication request headers with JWT cookie."""
    return {'Cookie': f'access_token_cookie={token}'}


async def create_test_user(
    client: httpx.AsyncClient,
    admin_token: str,
    username: str,
    role_id: int = 2,
    password: str = _DEFAULT_USER_PASSWORD,
) -> dict:
    """Create a test user via admin ``POST /user/create``.

    The backend endpoint expects an **RSA-encrypted** password (``UserService.
    create_user`` → ``decrypt_md5_password`` which RSA-decrypts then md5-hashes
    before storing). This helper accepts a **plain** password, encrypts it
    against the backend's public key, and sends the ciphertext — mirroring
    what ``login`` does. Passing plain text directly made later ``login`` calls
    fail with 10600 because the stored md5 hash did not match the freshly
    RSA-encrypted+md5-decrypted login plaintext.
    """
    headers = auth_headers(admin_token)
    pubkey = await get_public_key(client)
    encrypted_pwd = encrypt_password(password, pubkey)
    resp = await client.post(
        f'{API_BASE}/user/create',
        json={
            'user_name': username,
            'password': encrypted_pwd,
            'role_id': role_id,
        },
        headers=headers,
    )
    return assert_resp_200(resp)
