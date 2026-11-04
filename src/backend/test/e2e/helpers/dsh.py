"""Native desktop PKCE exchange through the deployed public API."""

import base64
import hashlib
import secrets
from urllib.parse import urlsplit

import httpx

from test.e2e.helpers.api import API_BASE
from test.e2e.helpers.auth import auth_headers


def _json_response(response: httpx.Response, *, unified: bool = False) -> dict:
    """Avoid embedding tickets, cookies or provider diagnostics in assertion output."""
    if response.status_code != 200:
        raise AssertionError(f"DSH exchange failed: HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise AssertionError("DSH exchange returned invalid JSON") from None
    if not isinstance(body, dict):
        raise AssertionError("DSH exchange returned an invalid object")
    if unified:
        if body.get("status_code") != 200 or not isinstance(body.get("data"), dict):
            raise AssertionError("DSH approval failed")
        return body["data"]
    return body


def _tokens(response: httpx.Response) -> dict:
    body = _json_response(response)
    if any(not isinstance(body.get(key), str) or not body[key] for key in ("access_token", "refresh_token")):
        raise AssertionError("DSH exchange returned incomplete credentials")
    return body


async def native_desktop_session(
    client: httpx.AsyncClient,
    platform_token: str,
    device_name: str,
    *,
    api_base: str = API_BASE,
    platform_origin: str | None = None,
) -> dict:
    """Create a real PKCE session; legacy callers retain their original defaults."""
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    response = await client.post(
        f"{api_base}/dsh/authorizations",
        json={
            "client_id": "dsh-desktop",
            "redirect_uri": "http://127.0.0.1:49346/dsh/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "device_name": device_name,
            "client_version": "1.1.0",
        },
    )
    authorization = _json_response(response)
    auth_id = authorization.get("auth_id")
    if not isinstance(auth_id, str) or not auth_id:
        raise AssertionError("DSH authorization returned an invalid identifier")
    origin = urlsplit(api_base)
    identity = _json_response(
        await client.post(
            f"{api_base}/dsh/authorize",
            headers={
                **auth_headers(platform_token),
                "Origin": platform_origin or f"{origin.scheme}://{origin.netloc}",
            },
            json={"auth_id": auth_id, "decision": "approve"},
        ),
        unified=True,
    )
    ticket = identity.get("identity_ticket")
    if not isinstance(ticket, str) or not ticket:
        raise AssertionError("DSH approval returned an invalid ticket")
    return _tokens(
        await client.post(
            f"{api_base}/dsh/token",
            json={
                "grant_type": "identity_ticket",
                "auth_id": auth_id,
                "identity_ticket": ticket,
                "code_verifier": verifier,
            },
        )
    )


async def refresh_desktop_session(client: httpx.AsyncClient, refresh_token: str, *, api_base: str = API_BASE) -> dict:
    """Rotate a session through the real refresh endpoint."""
    return _tokens(
        await client.post(f"{api_base}/dsh/token", json={"grant_type": "refresh_token", "refresh_token": refresh_token})
    )


async def logout_desktop_session(client: httpx.AsyncClient, access_token: str, *, api_base: str = API_BASE) -> None:
    """Revoke only the explicitly supplied desktop session."""
    response = await client.post(f"{api_base}/dsh/logout", headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != 204:
        raise AssertionError(f"DSH logout failed: HTTP {response.status_code}")
