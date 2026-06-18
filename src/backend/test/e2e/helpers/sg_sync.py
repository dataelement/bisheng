"""E2E helpers for SG (首钢) sync endpoints.

SG routes use fixed-header auth: the configured ``signature_header`` value
must exactly equal ``sso_sync.gateway_hmac_secret`` (not HMAC signing).
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx

from test.e2e.helpers.api import API_BASE

DEPTS_SG_PATH = '/departments/sg-sync'
USERS_SG_PATH = '/users/sg-sync'
SSO_SG_PATH = '/users/sg-sso-sync'

HEADER_SECRET = os.environ.get(
    'E2E_SG_HEADER_SECRET',
    os.environ.get('E2E_HMAC_SECRET', ''),
)
SIGNATURE_HEADER = os.environ.get('E2E_SIGNATURE_HEADER', 'X-Signature')
DEFAULT_MDM_ID = int(os.environ.get('E2E_SG_MDM_ID', '9001'))
DEFAULT_BUSINESS_SYSTEM = int(os.environ.get('E2E_SG_BUSINESS_SYSTEM', '1'))


def new_run_prefix() -> str:
    """Unique prefix for one E2E run (≥5 chars, ``e2e-sg-`` namespace)."""
    return f'e2e-sg-{uuid.uuid4().hex[:8]}'


def sg_auth_headers(secret: str | None = None) -> dict[str, str]:
    """Build fixed-header auth headers for SG sync routes."""
    value = secret if secret is not None else HEADER_SECRET
    return {
        'Content-Type': 'application/json',
        SIGNATURE_HEADER: value,
    }


def build_department_payload(
    *,
    run_id: str,
    mdm_id: int = DEFAULT_MDM_ID,
    business_system: int = DEFAULT_BUSINESS_SYSTEM,
    parent_code: str = '',
    dept_suffix: str = 'root',
    name: str | None = None,
    state: str = '0',
) -> dict[str, Any]:
    code = f'{run_id}-{dept_suffix}'
    return {
        'mdmId': mdm_id,
        'BusinessSystem': business_system,
        'uuid': f'{run_id}-dept-batch',
        'Field': [
            {
                'uuid': f'{run_id}-dept-{dept_suffix}',
                'code': code,
                'pid': parent_code,
                'remark': name or f'E2E SG Dept {dept_suffix}',
                'state': state,
            },
        ],
    }


def build_user_payload(
    *,
    run_id: str,
    dept_code: str,
    user_suffix: str = 'u1',
    mdm_id: int = DEFAULT_MDM_ID,
    business_system: int = DEFAULT_BUSINESS_SYSTEM,
    display_name: str | None = None,
    job_status: str = '01',
) -> dict[str, Any]:
    code = f'{run_id}-{user_suffix}'
    return {
        'mdmId': mdm_id,
        'BusinessSystem': business_system,
        'uuid': f'{run_id}-user-batch',
        'Field': [
            {
                'uuid': f'{run_id}-user-{user_suffix}',
                'code': code,
                'desc34': dept_code,
                'desc1': display_name or f'E2E SG User {user_suffix}',
                'desc93': job_status,
            },
        ],
    }


def build_sso_account_payload(
    *,
    person_no: str,
    user_name: str,
    guid: str = '',
) -> dict[str, Any]:
    return {
        'HEADER': {
            'INT_KEY': 'e2e',
            'SED_NAME': 'sg-esb',
            'REC_NAME': 'bisheng',
            'SENDDATE': '20260617',
            'SENDTIME': '120000',
        },
        'ROW': [
            {
                'PersonNO': person_no,
                'UserName': user_name,
                'Guid': guid,
            },
        ],
    }


def post_sg(
    client: httpx.Client,
    path: str,
    payload: dict[str, Any],
    *,
    secret: str | None = None,
    include_auth: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    headers: dict[str, str] = {'Content-Type': 'application/json'}
    if include_auth:
        headers.update(sg_auth_headers(secret))
    if extra_headers:
        headers.update(extra_headers)
    return client.post(path, content=json.dumps(payload, ensure_ascii=False).encode(), headers=headers)


def assert_esb_success(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Assert top-level ESB success and return per-row DATAINFO list."""
    assert 'ESB' in body, f'missing ESB envelope: {body}'
    esb = body['ESB']
    assert esb.get('CODE') == '0', (
        f"ESB CODE={esb.get('CODE')} DESC={esb.get('DESC')} "
        f"rows={esb.get('DATA', {}).get('DATAINFOS', {}).get('DATAINFO')}"
    )
    rows = esb['DATA']['DATAINFOS']['DATAINFO']
    assert isinstance(rows, list) and rows, 'DATAINFO must be a non-empty list'
    assert all(row.get('status') == '0' for row in rows), rows
    return rows


def assert_esb_partial_failure(body: dict[str, Any]) -> list[dict[str, Any]]:
    assert body['ESB']['CODE'] == '1'
    rows = body['ESB']['DATA']['DATAINFOS']['DATAINFO']
    assert any(row.get('status') == '1' for row in rows), rows
    return rows


def assert_sso_success(body: dict[str, Any]) -> list[dict[str, Any]]:
    assert 'TIEM' in body, f'missing TIEM envelope: {body}'
    rows = body['TIEM']
    assert isinstance(rows, list) and rows, 'TIEM must be a non-empty list'
    assert rows[0].get('Result') == '0', rows
    return rows


def assert_auth_rejected(resp: httpx.Response) -> None:
    """SG auth failures are wrapped as UnifiedResponseModel with 19301."""
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body.get('status_code') == 19301, (
        f'expected 19301, got {body.get("status_code")}: '
        f'{body.get("status_message")}'
    )


def full_url(path: str) -> str:
    return f'{API_BASE.rstrip("/")}{path}'


def login_admin_sync(client: httpx.Client) -> str:
    """Login as admin and return JWT (sync, for E2E verification)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    import base64

    pubkey_resp = client.get(f'{API_BASE}/user/public_key')
    assert pubkey_resp.status_code == 200
    public_key_pem = pubkey_resp.json()['data']['public_key']
    password = os.environ.get('E2E_ADMIN_PASSWORD', 'Bisheng@top1')

    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
    encrypted_password = base64.b64encode(encrypted).decode()

    resp = client.post(
        f'{API_BASE}/user/login',
        json={'user_name': 'admin', 'password': encrypted_password},
    )
    assert resp.status_code == 200
    body = resp.json()
    token = body.get('data', {}).get('access_token') or resp.cookies.get(
        'access_token_cookie', '',
    )
    assert token, f'admin login failed: {body}'
    return token
