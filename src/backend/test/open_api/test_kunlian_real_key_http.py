"""Real key lifecycle through formal HTTP admission; external identity stays a port."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.open_api.application.kunlian_access import KunlianAccessService
from bisheng.open_api.domain.services.kunlian_credential import KunlianCredentialService
from bisheng.open_endpoints.api.endpoints.kunlian_workflow_api import router
from test.open_api.test_kunlian_credential import Store


async def test_formal_list_checks_real_key_tenant_scope_and_revocation():
    credentials = KunlianCredentialService(Store())
    issued = await credentials.issue(
        is_global_super=True,
        created_by=1,
        connection_id="kunlian",
        integration_id="e2e-f133",
        tenant_ids=["allowed"],
        capabilities=["read"],
    )
    accounts = SimpleNamespace(
        resolve_account=AsyncMock(
            side_effect=[
                SimpleNamespace(user_id=17, tenant_id=7, external_tenant_id="allowed", external_user_id="subject"),
                SimpleNamespace(user_id=18, tenant_id=8, external_tenant_id="other", external_user_id="other-subject"),
            ]
        )
    )
    identities = SimpleNamespace(resolve=AsyncMock(return_value=SimpleNamespace(user_id=17, tenant_id=7)))
    app = FastAPI()
    app.state.kunlian_access_service = KunlianAccessService(
        credentials,
        identities,
        account_resolver=accounts,
        privilege_reader=AsyncMock(return_value=(False, False)),
    )
    app.state.kunlian_request_limiter = AsyncMock()
    app.state.kunlian_audit_service = SimpleNamespace(begin=AsyncMock(return_value="audit"), finish=AsyncMock())
    business = AsyncMock(return_value={"data": [{"id": "f" * 32}], "has_more": False})
    app.state.kunlian_workflow_api = SimpleNamespace(list=business)
    app.include_router(router)
    headers = {"Authorization": "Bearer " + issued["api_key"]}
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            "/api/v2/kunlian/workflows",
            headers=headers,
            params={"user_account": "allowed-account"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["data"][0]["id"] == "f" * 32
        business.assert_awaited_once()
        denied = await client.get(
            "/api/v2/kunlian/workflows",
            headers=headers,
            params={"user_account": "other-account"},
        )
        assert denied.status_code == 403
        assert identities.resolve.await_count == 1
        await credentials.revoke(issued["id"], is_global_super=True)
        revoked = await client.get(
            "/api/v2/kunlian/workflows",
            headers=headers,
            params={"user_account": "allowed-account"},
        )
        assert revoked.status_code == 401
        assert business.await_count == 1
        assert identities.resolve.await_count == 1
        assert accounts.resolve_account.await_count == 2
        assert [call.kwargs for call in accounts.resolve_account.await_args_list] == [
            {"connection_id": "kunlian", "user_account": "allowed-account"},
            {"connection_id": "kunlian", "user_account": "other-account"},
        ]
        identities.resolve.assert_awaited_once_with(
            connection_id="kunlian", external_tenant_id="allowed", external_user_id="subject"
        )
