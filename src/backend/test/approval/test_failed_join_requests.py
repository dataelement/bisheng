from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.application import request_state
from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.approval.domain.repositories import request_state_repository
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.common.errcode.approval import ApprovalExecutionFailedError
from bisheng.core.context import tenant
from bisheng.core.database import tenant_filter


@pytest.mark.parametrize(
    "scenario",
    ["knowledge_space_subscribe_request", "channel_subscribe_request", "menu_access_request", "app_publish_request"],
)
async def test_failed_request_requires_recovery_without_new_instance_task_or_outbox(scenario):
    repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=SimpleNamespace(id=16, status="execute_failed")),
        create_instance=AsyncMock(),
        create_task=AsyncMock(),
        create_outbox=AsyncMock(),
    )
    registry = SimpleNamespace(get_handler=AsyncMock())
    gate = ApprovalGate(registry=registry, instance_repository=repository)
    with pytest.raises(ApprovalExecutionFailedError) as exc:
        await gate.request_or_pass(
            ApprovalGateRequest(
                tenant_id=1,
                scenario_code=scenario,
                business_key="space:77:user:10",
                business_resource_type="knowledge_space",
                business_resource_id="77",
                business_name="space",
                applicant_user_id=10,
                applicant_user_name="applicant",
            )
        )
    assert exc.value.to_dict()["status_code"] == 18120
    registry.get_handler.assert_not_awaited()
    repository.create_instance.assert_not_awaited()
    repository.create_task.assert_not_awaited()
    repository.create_outbox.assert_not_awaited()


@pytest.mark.parametrize("status", ["pending", "exception"])
def test_normal_existing_request_decisions_unchanged(status):
    assert ApprovalGate._decision_from_instance_status(status) == status


@pytest_asyncio.fixture
async def isolated_requests(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: ApprovalInstance.__table__.create(c))

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(request_state_repository, "get_async_db_session", factory)
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session", factory
    )
    listeners = []
    original = event.listens_for

    def record(target, identifier, **kwargs):
        def decorate(callback):
            listeners.append((target, identifier, callback))
            return original(target, identifier, **kwargs)(callback)

        return decorate

    monkeypatch.setattr(event, "listens_for", record)
    monkeypatch.setattr(tenant_filter, "_initialized", False)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", set())
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    tenant_filter.register_tenant_filter_events()
    try:
        yield factory
    finally:
        for target, identifier, callback in reversed(listeners):
            event.remove(target, identifier, callback)
        await engine.dispose()


async def test_state_read_uses_latest_request_and_isolates_user_tenant_scenario(isolated_requests):
    with tenant.bypass_tenant_filter():
        async with isolated_requests() as session:
            for tid, user, scenario, key, status in [
                (1, 10, "knowledge_space_subscribe_request", "space:77:user:10", "execute_failed"),
                (1, 10, "knowledge_space_subscribe_request", "space:77:user:10", "pending"),
                (1, 10, "knowledge_space_subscribe_request", "space:78:user:10", "execute_failed"),
                (2, 10, "knowledge_space_subscribe_request", "space:77:user:10", "execute_failed"),
                (1, 11, "knowledge_space_subscribe_request", "space:77:user:10", "execute_failed"),
                (1, 10, "channel_subscribe_request", "space:77:user:10", "execute_failed"),
                (1, 10, "knowledge_space_subscribe_request", "space:79:user:10", "cancelled"),
            ]:
                session.add(
                    ApprovalInstance(
                        tenant_id=tid,
                        applicant_user_id=user,
                        applicant_user_name="applicant",
                        scenario_code=scenario,
                        scenario_name="scenario",
                        handler_key=scenario,
                        business_key=key,
                        business_resource_type="knowledge_space",
                        business_resource_id=key.split(":")[1],
                        business_name="space",
                        status=status,
                    )
                )
            await session.commit()
    assert await request_state.get_failed_request_keys(
        tenant_id=1,
        applicant_user_id=10,
        scenario_code="knowledge_space_subscribe_request",
        business_keys=["space:77:user:10", "space:78:user:10", "space:79:user:10"],
    ) == frozenset({"space:78:user:10"})
    with request_state._applicant_scope(1):
        assert (
            await ApprovalInstanceRepository.find_duplicate_active_instance(
                tenant_id=1,
                scenario_code="knowledge_space_subscribe_request",
                business_key="space:79:user:10",
                applicant_user_id=10,
            )
            is None
        )


async def test_batched_reads_restore_context_even_when_lookup_fails(monkeypatch):
    lookup = AsyncMock(return_value=[])
    monkeypatch.setattr(request_state, "list_active_request_states", lookup)
    kwargs = {"tenant_id": 1, "applicant_user_id": 10, "scenario_code": "knowledge_space_subscribe_request"}
    assert await request_state.get_failed_request_keys(**kwargs, business_keys=[]) == frozenset()
    lookup.assert_not_awaited()
    keys = [f"space:{i}:user:10" for i in range(205)]
    await request_state.get_failed_request_keys(**kwargs, business_keys=keys + keys)
    assert [len(call.kwargs["business_keys"]) for call in lookup.await_args_list] == [100, 100, 5]
    bindings = (
        (tenant.current_tenant_id, 7),
        (tenant.visible_tenant_ids, frozenset({1, 7})),
        (tenant._admin_scope_tenant_id, 88),
        (tenant._bypass_tenant_filter, True),
        (tenant._is_management_api, True),
    )
    tokens = [(var, var.set(value)) for var, value in bindings]
    try:
        lookup.side_effect = RuntimeError("lookup failed")
        with pytest.raises(RuntimeError):
            await request_state.get_failed_request_keys(**kwargs, business_keys=keys[:1])
        assert all(var.get() == value for var, value in bindings)
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
