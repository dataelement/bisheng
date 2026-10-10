from unittest.mock import AsyncMock, MagicMock

from bisheng.channel.domain.services.information_subscription_reconcile_service import (
    DesiredSubscriptionSnapshot,
    InformationSubscriptionReconcileService,
)
from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.external.bisheng_information_client.response_schema import InformationSubscriptionItem


def _item(source_id: str) -> InformationSubscriptionItem:
    return InformationSubscriptionItem(
        id=source_id,
        source_id=f"external-{source_id}",
        business_type="website",
        name=source_id,
    )


async def test_incomplete_desired_snapshot_makes_no_remote_calls():
    client = AsyncMock()
    service = InformationSubscriptionReconcileService(client, AsyncMock())

    result = await service.reconcile(
        DesiredSubscriptionSnapshot(ids=frozenset({"A"}), complete=False, failed_tenants=(2,)),
        AsyncMock(),
    )

    assert result["result"] == "desired_incomplete"
    client.list_all_subscriptions.assert_not_awaited()
    client.subscribe_one.assert_not_awaited()
    client.unsubscribe_one.assert_not_awaited()


async def test_reconcile_converges_in_stable_single_source_calls_and_upserts_metadata():
    client = AsyncMock()
    client.conf = IntelligenceCenterConf(information_subscription_auto_unsubscribe_enabled=True)
    client.list_all_subscriptions.side_effect = [
        [_item("B"), _item("C")],
        [_item("A"), _item("B"), _item("C")],
        [_item("A"), _item("B")],
    ]
    metadata = AsyncMock()
    reload_desired = AsyncMock(return_value=DesiredSubscriptionSnapshot(ids=frozenset({"A", "B"}), complete=True))
    service = InformationSubscriptionReconcileService(client, metadata)

    result = await service.reconcile(
        DesiredSubscriptionSnapshot(ids=frozenset({"B", "A"}), complete=True),
        reload_desired,
    )

    client.subscribe_one.assert_awaited_once_with("A")
    client.unsubscribe_one.assert_awaited_once_with("C")
    metadata.upsert_metadata.assert_awaited_once()
    assert [row.id for row in metadata.upsert_metadata.await_args.args[0]] == ["A", "B"]
    assert result["remaining_missing"] == []
    assert result["remaining_extra"] == []
    assert result["result"] == "converged"


async def test_item_failure_is_isolated_and_reported_by_final_drift():
    client = AsyncMock()
    client.conf = IntelligenceCenterConf(information_subscription_auto_unsubscribe_enabled=False)
    client.list_all_subscriptions.side_effect = [[], []]
    client.subscribe_one.side_effect = [RuntimeError("A failed"), None]
    service = InformationSubscriptionReconcileService(client, AsyncMock())

    result = await service.reconcile(
        DesiredSubscriptionSnapshot(ids=frozenset({"B", "A"}), complete=True),
        AsyncMock(),
    )

    assert [call.args[0] for call in client.subscribe_one.await_args_list] == ["A", "B"]
    assert result["failed"] == ["subscribe:A"]
    assert result["remaining_missing"] == ["A", "B"]


async def test_second_snapshot_failure_never_unsubscribes():
    client = AsyncMock()
    client.conf = IntelligenceCenterConf(information_subscription_auto_unsubscribe_enabled=True)
    client.list_all_subscriptions.side_effect = [[_item("X")], [_item("X")]]
    service = InformationSubscriptionReconcileService(client, AsyncMock())

    result = await service.reconcile(
        DesiredSubscriptionSnapshot(ids=frozenset(), complete=True),
        AsyncMock(return_value=DesiredSubscriptionSnapshot(ids=frozenset(), complete=False)),
    )

    client.unsubscribe_one.assert_not_awaited()
    assert result["result"] == "desired_reload_incomplete"


async def test_final_snapshot_failure_reports_unknown_not_converged():
    client = AsyncMock()
    client.conf = IntelligenceCenterConf(information_subscription_auto_unsubscribe_enabled=False)
    client.list_all_subscriptions.side_effect = [[], RuntimeError("read failed")]
    service = InformationSubscriptionReconcileService(client, AsyncMock())

    result = await service.reconcile(
        DesiredSubscriptionSnapshot(ids=frozenset(), complete=True),
        AsyncMock(),
    )

    assert result["result"] == "unknown"
    assert result["remaining_missing"] is None
    assert result["remaining_extra"] is None


async def test_lock_loss_stops_before_the_next_remote_mutation():
    client = AsyncMock()
    client.conf = IntelligenceCenterConf(information_subscription_auto_unsubscribe_enabled=False)
    client.list_all_subscriptions.return_value = []
    lock = MagicMock(refresh=MagicMock(side_effect=[True, False]))
    service = InformationSubscriptionReconcileService(client, AsyncMock())

    result = await service.reconcile(
        DesiredSubscriptionSnapshot(ids=frozenset({"A"}), complete=True),
        AsyncMock(),
        lock_guard=lock,
    )

    assert result["result"] == "lock_lost"
    client.list_all_subscriptions.assert_awaited_once()
    client.subscribe_one.assert_not_awaited()
