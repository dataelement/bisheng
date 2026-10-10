from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.interfaces.channel_info_source_repository import (
    ChannelInfoSourceRepository,
)
from bisheng.common.services.metric_log import emit_metric
from bisheng.core.external.bisheng_information_client.client import BishengInformationClient
from bisheng.core.external.bisheng_information_client.response_schema import InformationSubscriptionItem


@dataclass(frozen=True)
class DesiredSubscriptionSnapshot:
    ids: frozenset[str]
    complete: bool
    failed_tenants: tuple[int, ...] = ()


class InformationSubscriptionReconcileService:
    def __init__(
        self,
        client: BishengInformationClient,
        metadata_repository: ChannelInfoSourceRepository,
    ) -> None:
        self.client = client
        self.metadata_repository = metadata_repository

    async def reconcile(
        self,
        desired_v1: DesiredSubscriptionSnapshot,
        reload_desired: Callable[[], Awaitable[DesiredSubscriptionSnapshot]],
        *,
        lock_guard: Any | None = None,
    ) -> dict:
        started_result = {
            "result": "unknown",
            "subscribed": 0,
            "unsubscribed": 0,
            "failed": [],
            "remaining_missing": None,
            "remaining_extra": None,
        }
        if not desired_v1.complete:
            started_result["result"] = "desired_incomplete"
            emit_metric(
                "information_subscription_reconcile",
                result="desired_incomplete",
                failed_tenant_count=len(desired_v1.failed_tenants),
            )
            return started_result

        if not self._refresh_lock(lock_guard, started_result):
            return started_result
        try:
            actual_before = await self.client.list_all_subscriptions()
        except Exception:
            logger.exception("information subscription actual snapshot failed")
            emit_metric("information_subscription_reconcile", result="actual_incomplete")
            started_result["result"] = "actual_incomplete"
            return started_result

        actual_ids = {item.id for item in actual_before}
        for source_id in sorted(desired_v1.ids - actual_ids):
            if not self._refresh_lock(lock_guard, started_result):
                return started_result
            try:
                await self.client.subscribe_one(source_id)
                started_result["subscribed"] += 1
            except Exception:
                logger.exception("information subscription reconcile subscribe failed source_id={}", source_id)
                started_result["failed"].append(f"subscribe:{source_id}")

        guard_result: str | None = None
        if self.client.conf.information_subscription_auto_unsubscribe_enabled:
            if not self._refresh_lock(lock_guard, started_result):
                return started_result
            try:
                desired_v2 = await reload_desired()
            except Exception:
                logger.exception("information subscription desired snapshot reload failed")
                desired_v2 = DesiredSubscriptionSnapshot(ids=frozenset(), complete=False)
            if not desired_v2.complete:
                guard_result = "desired_reload_incomplete"
            else:
                if not self._refresh_lock(lock_guard, started_result):
                    return started_result
                try:
                    actual_middle = await self.client.list_all_subscriptions()
                except Exception:
                    logger.exception("information subscription actual snapshot reload failed")
                    actual_middle = None
                    guard_result = "actual_reload_incomplete"
                if actual_middle is not None:
                    for source_id in sorted({item.id for item in actual_middle} - desired_v2.ids):
                        if not self._refresh_lock(lock_guard, started_result):
                            return started_result
                        try:
                            await self.client.unsubscribe_one(source_id)
                            started_result["unsubscribed"] += 1
                        except Exception:
                            logger.exception(
                                "information subscription reconcile unsubscribe failed source_id={}", source_id
                            )
                            started_result["failed"].append(f"unsubscribe:{source_id}")

        if not self._refresh_lock(lock_guard, started_result):
            return started_result
        try:
            final_items = await self.client.list_all_subscriptions()
        except Exception:
            logger.exception("information subscription final snapshot failed")
            emit_metric(
                "information_subscription_reconcile",
                result="unknown",
                subscribed=started_result["subscribed"],
                unsubscribed=started_result["unsubscribed"],
                failed_count=len(started_result["failed"]),
            )
            return started_result

        await self._upsert_metadata(final_items)
        final_ids = {item.id for item in final_items}
        remaining_missing = sorted(desired_v1.ids - final_ids)
        remaining_extra = sorted(final_ids - desired_v1.ids)
        started_result["remaining_missing"] = remaining_missing
        started_result["remaining_extra"] = remaining_extra
        if guard_result:
            started_result["result"] = guard_result
        elif not remaining_missing and not remaining_extra:
            started_result["result"] = "converged"
        else:
            started_result["result"] = "drift"
        emit_metric(
            "information_subscription_reconcile",
            result=started_result["result"],
            desired_count=len(desired_v1.ids),
            actual_count=len(final_ids),
            remaining_missing=len(remaining_missing),
            remaining_extra=len(remaining_extra),
            failed_count=len(started_result["failed"]),
            failed_sample=started_result["failed"][:10],
        )
        return started_result

    @staticmethod
    def _refresh_lock(lock_guard: Any | None, result: dict) -> bool:
        if lock_guard is None or lock_guard.refresh():
            return True
        result["result"] = "lock_lost"
        emit_metric(
            "information_subscription_reconcile",
            result="lock_lost",
            subscribed=result["subscribed"],
            unsubscribed=result["unsubscribed"],
            failed_count=len(result["failed"]),
        )
        return False

    async def _upsert_metadata(self, items: list[InformationSubscriptionItem]) -> None:
        rows = [
            ChannelInfoSource(
                id=item.id,
                source_name=item.name,
                source_icon=item.icon,
                source_type=item.business_type,
                description=item.description,
            )
            for item in sorted(items, key=lambda value: value.id)
        ]
        try:
            await self.metadata_repository.upsert_metadata(rows)
        except Exception:
            logger.exception("information subscription metadata upsert failed count={}", len(rows))
