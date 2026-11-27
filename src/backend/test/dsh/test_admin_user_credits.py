"""F016: the administrator's usage page reads a member's month balance with the member's own arithmetic."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from bisheng.dsh.domain.schemas.unified_policy import UNLIMITED_TOKEN_LIMIT


@pytest.fixture
async def credits_api(monkeypatch):
    from bisheng.dsh.api.endpoints import unified_policy as api

    state = SimpleNamespace(allowed=True, attempts=[], limit=1_000_000_000)
    snapshot = {"quota_state": "ready", "used": 100_512_720}

    async def authorize(actor, tenant, target=None):
        state.attempts.append((actor, tenant, target))
        if not state.allowed:
            raise HTTPException(status_code=403, detail="Management scope rejected")
        return actor, tenant

    policy_reader = AsyncMock(side_effect=lambda user_id: SimpleNamespace(monthly_token_limit=state.limit))
    model_runtime = SimpleNamespace(prepare_month=AsyncMock(side_effect=lambda principal, month: dict(snapshot)))
    monkeypatch.setattr(api, "read_policy", policy_reader)
    monkeypatch.setattr(api, "get_model_runtime", AsyncMock(return_value=model_runtime))
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.admin_user] = lambda: SimpleNamespace(user_id=90)
    app.dependency_overrides[api.get_management] = lambda: SimpleNamespace(authorize=authorize)
    app.dependency_overrides[api.get_runtime] = lambda: SimpleNamespace(
        settings=SimpleNamespace(billing_timezone="Asia/Shanghai")
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            state=state,
            snapshot=snapshot,
            read_policy=policy_reader,
            prepare_month=model_runtime.prepare_month,
        )


async def test_admin_reads_the_selected_members_balance_in_the_authorized_tenant(credits_api):
    response = await credits_api.client.get("/api/v1/dsh/admin/users/20/credits?tenant_id=2")
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["limit"], data["used"], data["remaining"], data["unlimited"]) == (
        "1000",
        "100.51272",
        "899.48728",
        False,
    )
    assert data["billing_timezone"] == "Asia/Shanghai" and data["reset_at"].endswith("T16:00:00Z")
    assert credits_api.state.attempts == [(90, 2, 20)]
    credits_api.read_policy.assert_awaited_once_with(20)
    principal, month = credits_api.prepare_month.await_args.args
    assert (principal.tenant_id, principal.user_id, month) == (2, 20, data["month"])


async def test_admin_reads_negative_remaining_when_member_overdrew(credits_api):
    credits_api.snapshot.update(used=1_284_754_515)
    response = await credits_api.client.get("/api/v1/dsh/admin/users/20/credits?tenant_id=2")
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["limit"], data["used"], data["remaining"], data["unlimited"]) == (
        "1000",
        "1284.754515",
        "-284.754515",
        False,
    )


async def test_uncapped_member_and_unready_ledger_stay_explicit(credits_api):
    credits_api.state.limit = UNLIMITED_TOKEN_LIMIT
    credits_api.snapshot.update(quota_state="unavailable", used=None)
    data = (await credits_api.client.get("/api/v1/dsh/admin/users/20/credits?tenant_id=2")).json()["data"]
    assert data["unlimited"] is True
    assert data["used"] is None and data["remaining"] is None


async def test_authorization_precedes_any_policy_or_ledger_read(credits_api):
    credits_api.state.allowed = False
    response = await credits_api.client.get("/api/v1/dsh/admin/users/20/credits?tenant_id=2")
    assert response.status_code == 403
    credits_api.read_policy.assert_not_awaited()
    credits_api.prepare_month.assert_not_awaited()


async def test_rule_editor_previews_the_balance_with_the_members_own_rule(credits_api, monkeypatch):
    from bisheng.dsh.api.endpoints import unified_policy as api

    previews = []

    class Repo:
        def preview_user_limit(self, user_id, value):
            previews.append((user_id, value.monthly_credits, value.enabled))
            return 1_500_000_000

    async def transaction(callback):
        return callback(Repo())

    monkeypatch.setattr(api, "policy_transaction", transaction)
    response = await credits_api.client.get("/api/v1/dsh/admin/users/20/credits?tenant_id=2&monthly_credits=1500")
    data = response.json()["data"]
    assert (data["limit"], data["used"], data["remaining"]) == ("1500", "100.51272", "1399.48728")
    assert previews == [(20, "1500", True)]
    credits_api.read_policy.assert_not_awaited()
    assert credits_api.state.attempts == [(90, 2, 20)]


@pytest.mark.parametrize("value", ["abc", "1000000.5", "-1", "1.25"])
async def test_rule_preview_rejects_what_the_rule_editor_would_reject(credits_api, value):
    response = await credits_api.client.get(f"/api/v1/dsh/admin/users/20/credits?monthly_credits={value}")
    assert response.status_code == 422
    assert credits_api.state.attempts == []
