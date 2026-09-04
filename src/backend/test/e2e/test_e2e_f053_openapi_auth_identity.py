"""Live E2E coverage for F053 Open API authentication and identity.

Prerequisites:
- Set ``F053_E2E=1`` only for a dedicated deployment with MySQL, Redis,
  OpenFGA, object storage, and the F053 migrations/model release installed.
- Set ``E2E_API_BASE`` to that deployment's ``/api/v1`` base URL.
- Enable the deployment-level PAT switch and public guest access.
- Provide the F053-specific environment variables read by ``_required_env``.

The suite creates only ``e2e-f053-openapi-*`` service accounts. Cleanup runs
before and after the suite and never addresses resources outside that prefix.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token

PREFIX = "e2e-f053-openapi-"
API_ORIGIN = API_BASE.removesuffix("/api/v1")
E2E_ENABLED = os.environ.get("F053_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not E2E_ENABLED,
    reason="set F053_E2E=1 only against a dedicated F053 test deployment",
)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required when F053_E2E=1")
    return value


async def _cleanup_service_accounts(client: httpx.AsyncClient, token: str) -> None:
    """Delete only service accounts created by this suite."""

    response = await client.get(
        f"{API_BASE}/service-accounts",
        params={"keyword": PREFIX, "page": 1, "page_size": 200},
        headers=auth_headers(token),
    )
    page = assert_resp_200(response)
    for item in page.get("data", []):
        if str(item.get("name", "")).startswith(PREFIX):
            assert_resp_200(
                await client.delete(
                    f"{API_BASE}/service-accounts/{item['id']}",
                    headers=auth_headers(token),
                )
            )


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=30.0) as value:
        yield value


@pytest.fixture(scope="module")
async def admin_token(client: httpx.AsyncClient) -> str:
    return await get_admin_token(client)


@pytest.fixture(scope="module")
async def service_account(
    client: httpx.AsyncClient,
    admin_token: str,
):
    await _cleanup_service_accounts(client, admin_token)
    name = f"{PREFIX}{uuid4().hex[:12]}"
    created = assert_resp_200(
        await client.post(
            f"{API_BASE}/service-accounts",
            json={
                "name": name,
                "description": "F053 dedicated E2E subject",
                "resource_owner_user_id": int(_required_env("F053_E2E_OWNER_USER_ID")),
            },
            headers=auth_headers(admin_token),
        )
    )
    persisted = assert_resp_200(
        await client.get(
            f"{API_BASE}/service-accounts/{created['id']}",
            headers=auth_headers(admin_token),
        )
    )
    assert persisted["name"] == name

    issued = assert_resp_200(
        await client.post(
            f"{API_BASE}/service-accounts/{created['id']}/keys",
            json={
                "name": f"{PREFIX}key",
                "scopes": ["chat:invoke", "knowledge:read"],
                "delegate_scopes": [],
            },
            headers=auth_headers(admin_token),
        )
    )
    try:
        yield {"account": created, "key": issued}
    finally:
        await _cleanup_service_accounts(client, admin_token)


@pytest.fixture(scope="module")
async def personal_token(client: httpx.AsyncClient, admin_token: str):
    user_token = await get_user_token(
        client,
        _required_env("F053_E2E_USER_NAME"),
        _required_env("F053_E2E_USER_PASSWORD"),
    )
    original = assert_resp_200(
        await client.get(
            f"{API_BASE}/personal-tokens/settings",
            headers=auth_headers(admin_token),
        )
    )
    assert original["deployment_enabled"] is True
    assert_resp_200(
        await client.put(
            f"{API_BASE}/personal-tokens/settings",
            json={"pat_enabled": True, "pat_ttl_days": 30},
            headers=auth_headers(admin_token),
        )
    )
    issued = assert_resp_200(
        await client.post(
            f"{API_BASE}/me/api-token",
            headers=auth_headers(user_token),
        )
    )
    try:
        yield issued
    finally:
        await client.delete(
            f"{API_BASE}/me/api-token",
            headers=auth_headers(user_token),
        )
        await client.put(
            f"{API_BASE}/personal-tokens/settings",
            json={
                "pat_enabled": original["pat_enabled"],
                "pat_ttl_days": original["pat_ttl_days"],
            },
            headers=auth_headers(admin_token),
        )


class TestE2EF053OpenApiAuthIdentity:
    """F053 live API isolation, key, PAT, daily, and public-v3 checks."""

    async def test_ac_f053_01_v2_rejects_missing_key_and_jwt_fallback(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
    ) -> None:
        """AC-F053-01: v2 requires an API key even when JWT is present."""

        missing = await client.get(f"{API_ORIGIN}/api/v2/auth/whoami")
        assert missing.status_code == 401
        assert_resp_error(missing, 26001)

        jwt_only = await client.get(
            f"{API_ORIGIN}/api/v2/auth/whoami",
            headers=auth_headers(admin_token),
        )
        assert jwt_only.status_code == 401
        assert_resp_error(jwt_only, 26001)

    async def test_ac_f053_02_sak_is_an_independent_subject(
        self,
        client: httpx.AsyncClient,
        service_account: dict,
    ) -> None:
        """AC-F053-02: SAK authenticates the independent service-account subject."""

        account = service_account["account"]
        key = service_account["key"]
        data = assert_resp_200(
            await client.get(
                f"{API_ORIGIN}/api/v2/auth/whoami",
                headers={"Authorization": f"Bearer {key['plaintext']}"},
            )
        )
        assert data["actor_kind"] == "service_account"
        assert data["actor_id"] == account["id"]
        assert data["authorization_subject_type"] == "service_account"
        assert data["authorization_subject_id"] == account["id"]
        assert "plaintext" not in data

    async def test_ac_f053_03_identity_input_is_strict(
        self,
        client: httpx.AsyncClient,
        service_account: dict,
    ) -> None:
        """AC-F053-03: legacy identity headers and conflicting new headers fail."""

        bearer = {"Authorization": f"Bearer {service_account['key']['plaintext']}"}
        legacy = await client.get(
            f"{API_ORIGIN}/api/v2/auth/whoami",
            headers={**bearer, "X-Bisheng-End-User": "legacy"},
        )
        assert legacy.status_code == 400
        assert_resp_error(legacy, 26019)

        conflicting = await client.get(
            f"{API_ORIGIN}/api/v2/auth/whoami",
            headers={**bearer, "X-End-User": "external-1", "X-On-Behalf-Of": "1"},
        )
        assert conflicting.status_code == 400
        assert_resp_error(conflicting, 26010)

    async def test_ac_f053_04_daily_config_is_key_only_and_narrow(
        self,
        client: httpx.AsyncClient,
        service_account: dict,
    ) -> None:
        """AC-F053-04: the daily config uses SAK only and returns models/tools."""

        data = assert_resp_200(
            await client.get(
                f"{API_ORIGIN}/api/v2/workstation/config",
                headers={"Authorization": f"Bearer {service_account['key']['plaintext']}"},
            )
        )
        assert set(data) == {"models", "tools"}
        assert isinstance(data["models"], list)
        assert isinstance(data["tools"], list)

    async def test_ac_f053_05_pat_is_natural_person_and_read_only(
        self,
        client: httpx.AsyncClient,
        personal_token: dict,
    ) -> None:
        """AC-F053-05: PAT resolves a natural person with only knowledge:read."""

        data = assert_resp_200(
            await client.get(
                f"{API_ORIGIN}/api/v2/auth/whoami",
                headers={"Authorization": f"Bearer {personal_token['plaintext']}"},
            )
        )
        assert data["actor_kind"] == "natural_person"
        assert data["authorization_subject_type"] == "user"
        assert data["scopes"] == ["knowledge:read"]

    async def test_ac_f053_06_public_v3_is_anonymous_and_allowlisted(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """AC-F053-06: published v3 is anonymous and exposes no assistant list."""

        assistant_id = _required_env("F053_E2E_PUBLISHED_ASSISTANT_ID")
        assert_resp_200(
            await client.get(f"{API_ORIGIN}/api/v3/assistant/info/{assistant_id}")
        )

        forbidden_header = await client.get(
            f"{API_ORIGIN}/api/v3/assistant/info/{assistant_id}",
            headers={"X-End-User": "external-1"},
        )
        assert forbidden_header.status_code == 403

        missing_route = await client.get(f"{API_ORIGIN}/api/v3/assistant/list")
        assert missing_route.status_code == 404

    async def test_ac_f053_07_live_openapi_has_exact_public_http_surface(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """AC-F053-07: live schema exposes exactly seven public-v3 HTTP routes."""

        schema_response = await client.get(f"{API_ORIGIN}/openapi.json")
        assert schema_response.status_code == 200
        paths = schema_response.json()["paths"]
        assert {path for path in paths if path.startswith("/api/v3/")} == {
            "/api/v3/workflow/invoke",
            "/api/v3/workflow/stop",
            "/api/v3/assistant/chat/completions",
            "/api/v3/assistant/info/{assistant_id}",
            "/api/v3/flows/{flow_id}",
            "/api/v3/chat/history",
            "/api/v3/chat/gen_title",
        }
