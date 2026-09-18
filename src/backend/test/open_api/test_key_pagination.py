"""AC-R14: management key pagination with masked data and the original full-list API."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.open_api.api.dependencies import get_service_account_admin
from bisheng.open_api.api.endpoints.service_account_keys import router
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.models.service_account import ServiceAccount
from bisheng.user.domain.services.auth import AuthJwt


@pytest.fixture
async def key_client(open_api_db):
    now = datetime.now()
    async with open_api_db() as session:
        session.add(ServiceAccount(id=3, name="pagination-test", tenant_id=1, resource_owner_user_id=1))
        for key_id in range(1, 27):
            session.add(
                ApiCredential(
                    id=key_id,
                    tenant_id=1,
                    subject_kind="service_account",
                    subject_id=3 if key_id <= 25 else 4,
                    name=f"e2e-f053-pagination-{key_id}",
                    key_prefix="bs-sak-",
                    last4=f"{key_id:04}",
                    token_hash=f"{key_id:064x}",
                    scopes=["knowledge:read"],
                    # The only active keys are outside the first page.
                    revoked_at=now if key_id > 5 else None,
                    expires_at=now - timedelta(days=1) if 3 <= key_id <= 5 else None,
                )
            )
        await session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_service_account_admin] = lambda: SimpleNamespace(tenant_id=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app


async def test_key_pages_count_all_active_keys_without_returning_secrets(key_client):
    """AC-R14: real pages are ordered, disjoint, masked, and count unloaded active keys."""
    client, _ = key_client
    for number, expected_ids in [(1, list(range(25, 5, -1))), (2, list(range(5, 0, -1))), (3, [])]:
        response = await client.get("/api/v1/service-accounts/3/keys/page", params={"page": number})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["status_code"] == 200
        assert "status_message" in envelope
        payload = envelope["data"]
        assert payload["total"] == 25
        assert payload["active_count"] == 2
        assert [row["id"] for row in payload["data"]] == expected_ids
        for row in payload["data"]:
            assert "plaintext" not in row
            assert "token_hash" not in row
            assert row["key_mask"].startswith("bs-sak-********")
            assert row["delegate_scopes"] == []
        if number == 1:
            assert not any(row["is_valid"] for row in payload["data"])


async def test_full_key_list_stays_compatible(key_client):
    """AC-R14: grants and existing readers still receive the original complete array."""
    client, _ = key_client
    response = await client.get("/api/v1/service-accounts/3/keys")
    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    assert [row["id"] for row in response.json()["data"]] == list(range(25, 0, -1))


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
async def test_invalid_pagination_is_rejected(key_client, params):
    """AC-R14: page sizes are bounded before hitting the repository."""
    client, _ = key_client
    response = await client.get("/api/v1/service-accounts/3/keys/page", params=params)
    assert response.status_code == 422


async def test_key_pagination_requires_management_permission(key_client, monkeypatch):
    """AC-R14: the new page route uses the existing administrator admission dependency."""
    client, app = key_client
    app.dependency_overrides.pop(get_service_account_admin)
    app.dependency_overrides[AuthJwt] = lambda: None
    check = AsyncMock(side_effect=UnAuthorizedError())
    monkeypatch.setattr(UserPayload, "get_tenant_admin_user", check)
    # This isolated ASGI app deliberately has no deployment exception middleware.
    with pytest.raises(UnAuthorizedError) as rejected:
        await client.get("/api/v1/service-accounts/3/keys/page")
    assert rejected.value.code == 403
    check.assert_awaited_once()
