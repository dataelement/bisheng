import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.channel.domain.services.information_subscription_reconcile_service import DesiredSubscriptionSnapshot
from bisheng.core.context.tenant import current_tenant_id
from bisheng.worker.information import reconcile as reconcile_mod


def test_subscription_dispatcher_uses_random_countdown_without_sleep():
    with (
        patch.object(reconcile_mod, "_jitter_seconds", return_value=600),
        patch.object(reconcile_mod.random, "randint", return_value=123),
        patch.object(reconcile_mod.reconcile_information_subscriptions, "apply_async") as apply_async,
    ):
        reconcile_mod.dispatch_information_subscription_reconcile.run()

    apply_async.assert_called_once_with(countdown=123)


async def test_desired_snapshot_unions_tenants_and_restores_context():
    async def _read(tenant_id):
        assert current_tenant_id.get() == tenant_id
        return {"A", str(tenant_id)}

    with (
        patch.object(reconcile_mod, "_active_tenant_ids", new=AsyncMock(return_value=[1, 2])),
        patch.object(reconcile_mod, "_read_tenant_source_ids", side_effect=_read),
    ):
        before = current_tenant_id.get()
        snapshot = await reconcile_mod._collect_desired_snapshot()

    assert snapshot == DesiredSubscriptionSnapshot(ids=frozenset({"A", "1", "2"}), complete=True)
    assert current_tenant_id.get() == before


async def test_tenant_read_failure_marks_snapshot_incomplete():
    with (
        patch.object(reconcile_mod, "_active_tenant_ids", new=AsyncMock(return_value=[1, 2])),
        patch.object(reconcile_mod, "_read_tenant_source_ids", side_effect=[{"A"}, RuntimeError("failed")]),
    ):
        snapshot = await reconcile_mod._collect_desired_snapshot()

    assert snapshot.complete is False
    assert snapshot.failed_tenants == (2,)


def test_execution_skips_when_platform_lock_is_not_acquired():
    lock = MagicMock(acquire=MagicMock(return_value=False), redis_available=True)
    with (
        patch.object(reconcile_mod, "_new_platform_lock", return_value=lock),
        patch.object(reconcile_mod, "run_async_task") as run_async,
    ):
        reconcile_mod.reconcile_information_subscriptions.run()

    run_async.assert_not_called()


def test_execution_passes_the_owned_lock_to_async_reconcile():
    lock = MagicMock(acquire=MagicMock(return_value=True), redis_available=True)
    async_result = MagicMock()
    with (
        patch.object(reconcile_mod, "_new_platform_lock", return_value=lock),
        patch.object(
            reconcile_mod,
            "_reconcile_information_subscriptions_async",
            return_value=async_result,
        ) as reconcile_async,
        patch.object(reconcile_mod, "run_async_task", side_effect=lambda factory: asyncio.run(factory())),
    ):
        reconcile_mod.reconcile_information_subscriptions.run()

    reconcile_async.assert_called_once_with(lock)
    lock.release.assert_called_once_with()
