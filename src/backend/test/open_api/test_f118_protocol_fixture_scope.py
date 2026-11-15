"""Local F118 provision boundary regression, not live identity/E2E evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.common.errcode.open_api import ServiceAccountOperationForbiddenError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.open_api.domain.services import service_account_scope_service as scope
from test.e2e.helpers.f118_open_protocols import F118OpenProtocols
from test.e2e.helpers.f118_unification import F118Environment


class ProvisionBoundaryReached(Exception):
    """Stop once both real helper clean-list calls reached their own scopes."""


async def test_f118_child_provision_never_selects_super_management_scope(monkeypatch):
    monkeypatch.setattr(scope.settings.multi_tenant, "enabled", True)
    available = AsyncMock()
    global_scope = AsyncMock(side_effect=AssertionError("Child must not read global selection"))
    monkeypatch.setattr(scope, "ensure_service_account_tenant_available", available)
    monkeypatch.setattr(scope, "current_admin_scope", global_scope)
    actors = {}
    observed = []

    async def prepared_child(env):
        # Live F118Environment.prepare already verifies a Child administrator.
        env.tenant_id = 31 if env.run_id == "opunit" else 32
        env.owner_id = env.tenant_id + 100
        env.owner = {
            "Cookie": f"access_token_cookie=unit-child-{env.tenant_id}",
            "X-Management-Tenant": str(env.tenant_id),
        }
        actors[env.owner["Cookie"]] = SimpleNamespace(
            user_id=env.owner_id, tenant_id=env.tenant_id, is_global_super=False
        )

    monkeypatch.setattr(F118Environment, "prepare", prepared_child)

    async def transport(request):
        actor = actors[request.headers["Cookie"]]
        if request.url.path.endswith("/management-scope"):
            # Keep the real super-only refusal; never fake a successful switch.
            try:
                await scope.ServiceAccountScopeService.set_scope(actor, actor.tenant_id)
            except ServiceAccountOperationForbiddenError:
                return httpx.Response(
                    403,
                    json={"status_code": 26022, "status_message": "super-only", "data": None},
                )
            pytest.fail("Non-super scope selection unexpectedly admitted")
        if request.url.path.endswith("/service-accounts/scopes"):
            assert len(observed) == 2
            raise ProvisionBoundaryReached()
        assert request.method == "GET" and request.url.path.endswith("/service-accounts")
        run_id = "opunit" if actor.tenant_id == 31 else "oqunit"
        assert request.url.params["keyword"] == f"e2e-f118-{run_id}-protocol-"
        async with scope.ServiceAccountScopeService.bind_request(
            actor,
            expected_tenant=request.headers.get("X-Service-Account-Tenant"),
            writing=False,
        ) as tenant_id:
            observed.append((actor.tenant_id, tenant_id, get_current_tenant_id()))
            return httpx.Response(
                200,
                json={"status_code": 200, "status_message": "success", "data": {"data": [], "total": 0}},
            )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:

        def child(run_id):
            return F118Environment(
                client=client,
                run_id=run_id,
                parent_id=1,
                member_password="unit-only",
                credentials={},
                model_fixture={},
            )

        fixture = F118OpenProtocols(client, child("opunit"), child("oqunit"))
        with pytest.raises(ProvisionBoundaryReached):
            await fixture.prepare()
        assert observed == [(31, 31, 31), (32, 32, 32)]
        assert available.await_args_list[0].args == (31,)
        assert available.await_args_list[1].args == (32,)
        global_scope.assert_not_awaited()
        assert all(headers["X-Service-Account-Tenant"] == str(tenant) for tenant, headers in fixture.managers.items())
