"""Durable retry policy for failed automatic Vibe recovery operations."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeAssignment, RuntimeNode, RuntimeRoute
from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService


def operation(attempt=1, *, origin="system_recovery"):
    return SimpleNamespace(
        payload={
            "authorization_context": {"origin_kind": origin},
            "recovery_attempt": attempt,
        }
    )


def test_failed_clean_recovery_is_scheduled_with_exponential_backoff():
    now = datetime(2026, 11, 11, 13, 16)
    service = RuntimeOperationService(
        repository=SimpleNamespace(), artifacts=object(), app_loader=lambda _: None, clock=lambda: now
    )

    first = service._recovery_retry_metadata(operation(1), "failed", {"cleanup_complete": True})
    second = service._recovery_retry_metadata(operation(2), "timed_out", {"cleanup_complete": True})

    assert datetime.fromisoformat(first["recovery_retry_at"]) == now + timedelta(seconds=15)
    assert datetime.fromisoformat(second["recovery_retry_at"]) == now + timedelta(seconds=30)
    assert first["recovery_retry_status"] == second["recovery_retry_status"] == "scheduled"


def test_recovery_budget_exhaustion_is_durable_and_other_failures_do_not_retry():
    service = RuntimeOperationService(repository=SimpleNamespace(), artifacts=object(), app_loader=lambda _: None)

    assert service._recovery_retry_metadata(operation(3), "failed", {"cleanup_complete": True}) == {
        "recovery_attempt": 3,
        "recovery_budget": 3,
        "recovery_retry_status": "exhausted",
    }
    assert service._recovery_retry_metadata(operation(1), "cancelled", {"cleanup_complete": True}) == {}
    assert service._recovery_retry_metadata(operation(1), "failed", {"cleanup_complete": False}) == {}
    assert (
        service._recovery_retry_metadata(operation(1, origin="user_request"), "failed", {"cleanup_complete": True})
        == {}
    )


async def test_node_plan_dispatches_due_active_retry_and_survives_restart(monkeypatch):
    now = datetime(2026, 11, 11, 13, 17)
    op = SimpleNamespace(
        id="failed-recovery",
        app_id="app-a",
        tenant_id=3,
        status="failed",
        cleanup_status="complete",
        payload={},
        failure={
            "recovery_retry_status": "scheduled",
            "recovery_retry_at": (now - timedelta(seconds=1)).isoformat(),
        },
    )
    assignment = SimpleNamespace(active_operation_id=op.id)
    route = SimpleNamespace(id="route-a")
    app = SimpleNamespace(id="app-a")

    class Repo:
        async def purge_diagnostics(self, *args):
            return None

        async def node_operations(self, node_id):
            return [op]

        async def find(self, model, **kwargs):
            if model is RuntimeAssignment:
                return [assignment]
            if model is RuntimeRoute:
                return [route]
            return []

        async def get(self, model, key, **kwargs):
            return None if model is RuntimeNode else app

        async def get_application(self, app_id):
            return app

        async def capacity_snapshot(self, node_id):
            return {}

    recover = AsyncMock()
    monkeypatch.setattr(RuntimeDeliveryCoordinator, "recover", recover)
    service = RuntimeOperationService(
        repository=Repo(), artifacts=object(), app_loader=AsyncMock(return_value=app), clock=lambda: now
    )
    service.describe = AsyncMock(return_value={"operation_id": op.id})

    plan = await service.node_plan(SimpleNamespace(node_id="node-a"))

    recover.assert_awaited_once_with(app, route, running=False, retry_from=op)
    assert plan["operations"] == [{"operation_id": op.id}]
