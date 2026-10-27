"""Native desktop PKCE exchange through the deployed public API."""

import base64
import hashlib
import secrets
from urllib.parse import urlsplit

import httpx

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers


async def native_desktop_session(client: httpx.AsyncClient, platform_token: str, device_name: str) -> dict:
    """Create a fresh desktop session without reading or trusting Gateway state."""
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    response = await client.post(
        f"{API_BASE}/dsh/authorizations",
        json={
            "client_id": "dsh-desktop",
            "redirect_uri": "http://127.0.0.1:49346/dsh/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(32),
            "device_name": device_name,
            "client_version": "1.1.0",
        },
    )
    assert response.status_code == 200, response.text
    auth_id = response.json()["auth_id"]
    origin = urlsplit(API_BASE)
    identity = assert_resp_200(
        await client.post(
            f"{API_BASE}/dsh/authorize",
            headers={**auth_headers(platform_token), "Origin": f"{origin.scheme}://{origin.netloc}"},
            json={"auth_id": auth_id, "decision": "approve"},
        )
    )
    response = await client.post(
        f"{API_BASE}/dsh/token",
        json={
            "grant_type": "identity_ticket",
            "auth_id": auth_id,
            "identity_ticket": identity["identity_ticket"],
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()
