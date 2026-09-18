"""A scenario declared mandatory admits no ``pass`` route (PRD-1 INV-34).

PRD-1 promises in three places that an application release cannot be exempted
from review — RT-03 "平台不提供任何免审配置项", GOV-02 "不提供免审配置项", and
INV-34 "不存在免审配置项". The approval centre is generic and offers a ``pass``
route type to every scenario, so the promise has to be stated on the scenario
and enforced, in two places:

* the admin surface refuses to save such a route (18119), and
* the gate refuses to honour one that reached the table by other means.

The second is not redundant. A route row can arrive from a hand-run UPDATE or a
restore of a backup taken before the refusal existed, and on this scenario the
silent outcome — a release auto-approved and put online with nobody looking — is
far worse than a request parked in the exception queue.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
from bisheng.approval.domain.models.approval_scenario import ApprovalRouteRule, ApprovalScenario
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.approval_scenario_admin_service import ApprovalScenarioAdminService
from bisheng.common.errcode.approval import ApprovalScenarioForbidsPassRouteError
from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id

MANDATORY = "app_publish_request"
EXEMPTABLE = "menu_access_request"


@pytest_asyncio.fixture
async def scenario_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [ApprovalScenario.__table__, ApprovalRouteRule.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))

    @asynccontextmanager
    async def _factory():
        async with AsyncSession(bind=engine) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_scenario_repository.get_async_db_session",
        _factory,
    )
    # The tenant filter raises when multi-tenancy is on and no context is set,
    # and whether it is on depends on which test loaded the settings first — so
    # running this file alone proved nothing. Restore the previous value rather
    # than clearing it: leaving an ambient tenant behind is how test/permission
    # came to poison test/audit.
    previous = get_current_tenant_id()
    set_current_tenant_id(1)
    try:
        yield engine
    finally:
        set_current_tenant_id(previous)
        await engine.dispose()


async def _scenario(code: str) -> ApprovalScenario:
    return await ApprovalScenarioRepository.create_scenario(
        ApprovalScenario(tenant_id=1, scenario_code=code, scenario_name=code, enabled=True)
    )


def _route_payload(route_type: str) -> dict:
    return {"route_name": "默认分支", "route_type": route_type, "sort_order": 0, "match_config": {}}


class TestTheAdminSurfaceRefuses:
    async def test_a_pass_route_cannot_be_created_on_the_release_scenario(self, scenario_db):
        scenario = await _scenario(MANDATORY)

        with pytest.raises(ApprovalScenarioForbidsPassRouteError):
            await ApprovalScenarioAdminService.create_route(
                tenant_id=1, scenario_id=scenario.id, payload=_route_payload("pass")
            )

        assert await ApprovalScenarioRepository.list_route_rules(1, scenario.id) == []

    async def test_a_flow_route_on_the_same_scenario_is_untouched(self, scenario_db):
        scenario = await _scenario(MANDATORY)

        created = await ApprovalScenarioAdminService.create_route(
            tenant_id=1, scenario_id=scenario.id, payload=_route_payload("flow")
        )

        assert created["route_type"] == "flow"

    async def test_an_existing_flow_route_cannot_be_switched_to_pass(self, scenario_db):
        """The create-side refusal buys nothing if the update side lets it through."""
        scenario = await _scenario(MANDATORY)
        created = await ApprovalScenarioAdminService.create_route(
            tenant_id=1, scenario_id=scenario.id, payload=_route_payload("flow")
        )

        with pytest.raises(ApprovalScenarioForbidsPassRouteError):
            await ApprovalScenarioAdminService.update_route(
                tenant_id=1, route_rule_id=created["id"], payload={"route_type": "pass"}
            )

        still = await ApprovalScenarioRepository.get_route_rule(created["id"])
        assert still is not None and still.route_type == "flow"

    async def test_scenarios_that_never_promised_this_keep_their_pass_route(self, scenario_db):
        """The refusal is per scenario, not a change to the approval centre.

        Menu access, channel subscription and knowledge-space joining have always
        been allowed an auto-approval branch, and tightening those would be a
        silent behaviour change for tenants already running them.
        """
        scenario = await _scenario(EXEMPTABLE)

        created = await ApprovalScenarioAdminService.create_route(
            tenant_id=1, scenario_id=scenario.id, payload=_route_payload("pass")
        )

        assert created["route_type"] == "pass"


class TestTheGateRefusesToHonourOne:
    @staticmethod
    def _gate(scenario_code: str, route_type: str) -> tuple[ApprovalGate, SimpleNamespace]:
        handler = SimpleNamespace(
            build_detail=AsyncMock(return_value={}),
            build_title=AsyncMock(return_value="某应用"),
        )
        registry = ApprovalRegistry.with_default_presets()
        registry.get_handler = AsyncMock(return_value=handler)
        route = SimpleNamespace(id=5, route_type=route_type, route_name="默认分支", flow_definition_id=None)
        scenario_repository = SimpleNamespace(
            get_scenario_by_code=AsyncMock(return_value=SimpleNamespace(id=1, scenario_name="应用发布", enabled=True)),
            list_route_rules=AsyncMock(return_value=[route]),
        )
        instance_repository = SimpleNamespace(
            find_duplicate_active_instance=AsyncMock(return_value=None),
            create_instance=AsyncMock(return_value=SimpleNamespace(id=11, business_name="某应用")),
            create_exception=AsyncMock(return_value=SimpleNamespace(id=12)),
            create_outbox=AsyncMock(return_value=SimpleNamespace(id=13)),
            create_task=AsyncMock(),
        )
        gate = ApprovalGate(
            registry=registry,
            scenario_repository=scenario_repository,
            instance_repository=instance_repository,
        )
        gate.route_matcher = AsyncMock(return_value=route)
        return gate, instance_repository

    @staticmethod
    def _request(scenario_code: str) -> ApprovalGateRequest:
        return ApprovalGateRequest(
            tenant_id=1,
            scenario_code=scenario_code,
            business_key="deployment:1",
            business_resource_type="app",
            business_resource_id="app-1",
            business_name="某应用",
            applicant_user_id=7,
            applicant_user_name="alice",
            payload_snapshot={},
        )

    async def test_a_pass_route_does_not_auto_approve_a_release(self, monkeypatch):
        monkeypatch.setattr(
            "bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2",
            AsyncMock(),
        )
        gate, instance_repository = self._gate(MANDATORY, "pass")
        gate._notify_admins_of_exception = AsyncMock()

        await gate.request_or_pass(self._request(MANDATORY))

        created = instance_repository.create_instance.await_args.args[0]
        assert created.status == ApprovalInstanceStatus.EXCEPTION, (
            "a pass route on a mandatory scenario must land in the exception queue, never come back approved"
        )
        instance_repository.create_outbox.assert_not_awaited()

    async def test_a_pass_route_still_works_for_a_scenario_that_allows_it(self, monkeypatch):
        monkeypatch.setattr(
            "bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2",
            AsyncMock(),
        )
        gate, instance_repository = self._gate(EXEMPTABLE, "pass")

        await gate.request_or_pass(self._request(EXEMPTABLE))

        created = instance_repository.create_instance.await_args.args[0]
        assert created.status == ApprovalInstanceStatus.APPROVED
        instance_repository.create_outbox.assert_awaited()
