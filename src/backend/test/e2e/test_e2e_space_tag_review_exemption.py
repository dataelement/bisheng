"""
E2E：知识空间新增标签免审规则（API + 创建响应 review_status）。

前置：backend :7860 可用；admin 可登录。
环境变量（可选）：
  E2E_API_BASE — 默认 http://localhost:7860/api/v1
  E2E_ADMIN_PASSWORD — 默认 Bisheng@top1
  E2E_PUBLIC_SPACE_ID — public 库 ID；未设则尝试从列表取第一个 public 库
  E2E_TAG_NAME_PREFIX — 默认 e2e-tag-exempt-
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

API_BASE = os.environ.get("E2E_API_BASE", "http://localhost:7860/api/v1")
HEALTH_URL = API_BASE.replace("/api/v1", "") + "/health"
TAG_PREFIX = os.environ.get("E2E_TAG_NAME_PREFIX", "e2e-tag-exempt-")


def _backend_up() -> bool:
    try:
        return httpx.get(HEALTH_URL, timeout=3.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _backend_up(), reason="backend not reachable on :7860")


def _login(client: httpx.Client, username: str = "admin", password: str | None = None) -> str:
    from base64 import b64encode

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pubkey_resp = client.get(f"{API_BASE}/user/public_key")
    assert pubkey_resp.status_code == 200
    public_key_pem = pubkey_resp.json()["data"]["public_key"]

    if password is None:
        password = os.environ.get("E2E_ADMIN_PASSWORD", "Bisheng@top1")

    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(
        password.encode(),
        padding.PKCS1v15(),
    )
    enc_b64 = b64encode(encrypted).decode()

    captcha_resp = client.get(f"{API_BASE}/user/get_captcha")
    captcha = captcha_resp.json().get("data") or {}

    login_resp = client.post(
        f"{API_BASE}/user/login",
        json={
            "user_name": username,
            "password": enc_b64,
            "captcha_key": captcha.get("captcha_key", ""),
            "captcha": "",
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    body = login_resp.json()
    if body.get("status_code") != 200:
        pytest.skip(f"login unavailable for e2e: {body.get('status_message')}")
    token = body["data"]["access_token"]
    client.cookies.set("access_token_cookie", token)
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Cookie": f"access_token_cookie={token}",
    }


def _resolve_public_space_id(client: httpx.Client, token: str) -> int:
    env_id = os.environ.get("E2E_PUBLIC_SPACE_ID")
    if env_id:
        return int(env_id)

    resp = client.get(
        f"{API_BASE}/knowledge/space/level/public",
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    rows = payload.get("data") or []
    if not rows:
        pytest.skip("no public knowledge space found for admin")
    first = rows[0]
    space_id = first.get("id") or first.get("space_id")
    return int(space_id)


def _add_space_tag(client: httpx.Client, token: str, space_id: int, tag_name: str) -> dict:
    resp = client.post(
        f"{API_BASE}/knowledge/space/{space_id}/tag",
        headers=_auth_headers(token),
        json={"tag_name": tag_name},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status_code") == 200, body
    data = body.get("data")
    assert isinstance(data, dict), body
    return data


class TestSpaceTagReviewExemptionE2E:
    """API-EX：public 库 admin 免审创建应返回 review_status=1。"""

    def test_admin_add_tag_on_public_space_is_auto_approved(self):
        tag_name = f"{TAG_PREFIX}{uuid.uuid4().hex[:8]}"
        with httpx.Client(timeout=30.0) as client:
            token = _login(client)
            space_id = _resolve_public_space_id(client, token)
            data = _add_space_tag(client, token, space_id, tag_name)

        assert data.get("name") == tag_name
        assert data.get("review_status") == 1, data
        assert data.get("id") is not None

    def test_lookup_after_exempt_create_returns_approved(self):
        tag_name = f"{TAG_PREFIX}{uuid.uuid4().hex[:8]}"
        with httpx.Client(timeout=30.0) as client:
            token = _login(client)
            space_id = _resolve_public_space_id(client, token)
            created = _add_space_tag(client, token, space_id, tag_name)
            assert created.get("review_status") == 1

            lookup = client.get(
                f"{API_BASE}/knowledge/space/{space_id}/tag/lookup",
                headers=_auth_headers(token),
                params={"tag_name": tag_name},
            )
            assert lookup.status_code == 200
            row = lookup.json().get("data") or {}
            assert row.get("review_status") == 1
            assert row.get("name") == tag_name
