"""F011 HTTP acceptance against an explicitly provisioned test-only identity.

The fixture account, tenant and nickname must all have the e2e-f011- prefix.
No real account is selected and no account is created/deleted by this suite.
"""

import json
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

_FIXTURE = os.environ.get("E2E_F011_FIXTURE", "")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _FIXTURE, reason="Dedicated F011 backend fixture is not configured"),
]


@pytest.fixture
async def own_identity():
    fixture = json.loads(_FIXTURE)
    assert fixture["account"].startswith("e2e-f011-")
    assert fixture["tenant_name"].startswith("e2e-f011-") and fixture["tenant_id"] > 1
    assert fixture["nickname"].startswith("e2e-f011-") and len(fixture["nickname"]) <= 32
    token = os.environ["E2E_F011_USER_TOKEN"]
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        headers = auth_headers(token)
        original = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
        assert original["user_id"] == fixture["user_id"] and original["external_id"] == fixture["account"]
        assert (original.get("leaf_tenant_id") or original.get("tenant_id")) == fixture["tenant_id"]
        assert original["user_name"] == fixture["nickname"] and original["role"] != "admin"
        # Setup cleanup: only this explicitly owned user, using its valid original nickname.
        assert_resp_200(
            await client.patch(
                f"{API_BASE}/user/profile/nickname", headers=headers, json={"user_name": fixture["nickname"]}
            )
        )
        try:
            yield client, headers, fixture
        finally:
            assert_resp_200(
                await client.patch(
                    f"{API_BASE}/user/profile/nickname", headers=headers, json={"user_name": fixture["nickname"]}
                )
            )
            restored = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
            assert restored["user_name"] == fixture["nickname"] and restored["external_id"] == fixture["account"]


async def test_self_rename_updates_profile_with_the_existing_session(own_identity):
    """AC-16, AC-20, AC-21, AC-24: an ordinary user changes their own nickname."""
    client, headers, fixture = own_identity
    value = "e2e-f011-UpdatedNickname"
    saved = assert_resp_200(
        await client.patch(f"{API_BASE}/user/profile/nickname", headers=headers, json={"user_name": value})
    )
    assert saved == {"user_id": fixture["user_id"], "user_name": value, "external_id": fixture["account"]}
    current = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
    assert current["user_name"] == value and current["external_id"] == fixture["account"]


@pytest.mark.parametrize("proposed", ["x" * 33, "invalid nickname", "invalid\u200bname"])
async def test_invalid_nickname_keeps_the_original_profile(own_identity, proposed):
    """AC-04, AC-06, AC-07, AC-20: failed writes preserve the current nickname."""
    client, headers, fixture = own_identity
    assert_resp_error(
        await client.patch(f"{API_BASE}/user/profile/nickname", headers=headers, json={"user_name": proposed}), 10614
    )
    current = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
    assert current["user_name"] == fixture["nickname"]


async def test_self_endpoint_rejects_another_target(own_identity):
    """AC-16, AC-22: self-service cannot rename another authenticated identity."""
    client, headers, fixture = own_identity
    response = await client.patch(
        f"{API_BASE}/user/profile/nickname",
        headers=headers,
        json={
            "user_id": fixture["user_id"] + 1,
            "user_name": "e2e-f011-OtherTarget",
        },
    )
    assert response.status_code == 422
    current = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
    assert current["user_name"] == fixture["nickname"]


async def test_unauthenticated_request_is_denied(own_identity):
    """AC-16, AC-22: an unauthenticated caller cannot change a nickname."""
    _, _, _fixture = own_identity
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as anonymous:
        response = await anonymous.patch(f"{API_BASE}/user/profile/nickname", json={"user_name": "e2e-f011-Anonymous"})
        assert response.status_code == 401
