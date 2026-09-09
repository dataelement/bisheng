"""One settlement path for successful, failed, cancelled, and interrupted calls."""

from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis


class DshUsageService:
    def __init__(self, quota: QuotaRedis):
        self.quota = quota

    async def check_and_start(self, event: UsageEvent) -> UsageEvent:
        return await self.quota.check_and_start(event)

    async def record_usage(self, event: UsageEvent, expected_version: int) -> UsageEvent:
        # Transport failures propagate; callers query the original request, never resend upstream.
        return await self.quota.record_usage(event, expected_version)

    async def reconcile_unknown(self, event: UsageEvent, expected_version: int) -> UsageEvent:
        if event.usage_source != "RECONCILED" or not event.operation_id or not event.payload_hash:
            raise ValueError("Reconciliation requires a persisted operation and verified evidence digest")
        current = await self.quota.get_request(event)
        if current is None or (current.status != "USAGE_UNKNOWN" and current.operation_id != event.operation_id):
            raise ValueError("Only unresolved unknown usage can be reconciled")
        return await self.quota.record_usage(event, expected_version)

    async def get_request(self, event: UsageEvent) -> UsageEvent | None:
        return await self.quota.get_request(event)

    async def claim_reconciliation(self, event: UsageEvent, *, operation_id: str, payload_hash: str, generation: int):
        return await self.quota.claim_reconciliation(
            event, operation_id=operation_id, payload_hash=payload_hash, generation=generation
        )

    async def read_usage(self, tenant_id: int, user_id: int, usage_month: str) -> dict:
        return await self.quota.read_usage(tenant_id, user_id, usage_month)
