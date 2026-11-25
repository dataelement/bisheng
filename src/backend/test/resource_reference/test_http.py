"""Local ASGI integration for AC-03/04/05/12; external auth/FGA transports are doubles."""

from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, text

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.models.llm_server import LLMServer
from test.e2e.helpers.api import assert_resp_200, assert_resp_error
from test.knowledge_unification import test_model_deletion_http as fixtures

business, impact, model_owner_tenant = fixtures.business, fixtures.impact, fixtures.model_owner_tenant
ready, removal_session = fixtures.ready, fixtures.removal_session


@pytest.mark.parametrize("failure", ["sql", "metadata"])
async def test_model_precheck_and_delete_survive_hint_query_failure(business, monkeypatch, failure):
    """AC-04: failed hints leave a real reviewable confirmation and allow deletion."""
    factory, _, references, _, _ = business
    await fixtures.install(monkeypatch, business)
    business_sessions = []
    real_read = references.repository.alock_removal_targets

    async def read(session, **kwargs):
        business_sessions.append(session)
        return await real_read(session, **kwargs)

    monkeypatch.setattr(references.repository, "alock_removal_targets", read)
    if failure == "sql":
        from bisheng.resource_reference.domain.repositories.reference_hint_repository import ReferenceHintRepository

        async def fail_query(self, session, targets, **kwargs):
            assert all(session is not active for active in business_sessions)
            await session.execute(text("SELECT * FROM e2e_reference_missing_index"))

        monkeypatch.setattr(ReferenceHintRepository, "aread", fail_query)
    else:
        monkeypatch.setattr(
            references, "_disclose", AsyncMock(side_effect=ReferenceCoverageNotReadyError(reason="hint_down"))
        )
    with fixtures.actual.native.actor() as user:
        fixtures.actual.web(user)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fixtures.http_application(user)), base_url="http://offline"
        ) as client:
            plan = assert_resp_200(await client.post("/api/v1/llm/server-removal-plan", json={"server_id": 1}))
            assert plan["inspection"]["check_complete"] is False
            control = plan["confirmation"]
            assert_resp_200(
                await client.request(
                    "DELETE",
                    "/api/v1/llm",
                    json={"server_id": 1},
                    params={"confirmation_id": control["confirmation_id"], "plan_digest": control["plan_digest"]},
                )
            )
    async with factory() as session:
        assert await session.get(LLMServer, 1) is None
        plans = (await session.execute(select(KnowledgeOperationPlan))).scalars().all()
        assert any(row.model_execution_state == "COMPLETED" for row in plans)


async def test_foreign_provider_still_denied_despite_optional_hints(business, monkeypatch):
    """AC-12: cross-tenant provider deletion still returns the actual 19802 error."""
    await fixtures.install(monkeypatch, business)
    with fixtures.actual.native.actor() as user:
        fixtures.actual.web(user)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fixtures.http_application(user)), base_url="http://offline"
        ) as client:
            assert_resp_error(await client.post("/api/v1/llm/server-removal-plan", json={"server_id": 3}), 19802)
