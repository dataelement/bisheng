"""Rebuild missing Redis ledgers from committed SQL and surviving request snapshots."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from loguru import logger

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected


class AutomaticQuotaRecovery:
    def __init__(self, quota, repository_scope, *, billing_timezone: str):
        self.quota, self.repository_scope = quota, repository_scope
        self.billing_timezone = billing_timezone
        self.script = (Path(__file__).parents[2] / "infrastructure/lua/automatic_recovery.lua").read_text()

    async def healthy(self, base: str, month: str | None) -> bool:
        redis = self.quota.redis
        gate = await redis.hgetall(base + ":gate")
        if gate and "redis_generation" not in gate:
            await redis.hsetnx(base + ":gate", "redis_generation", self.quota.topology.run_id)
        if gate.get("redis_generation", self.quota.topology.run_id) != self.quota.topology.run_id:
            return False
        if (
            gate.get("state") != "READY"
            or gate.get("write_in_progress") == "1"
            or gate.get("running_index") != "1"
            or int(gate.get("running_count", -1)) != await redis.zcard(base + ":running")
        ):
            return False
        if any(value.startswith("STORAGE_UNCERTAIN:") for value in await redis.smembers(base + ":blocks")):
            return False
        months = {key[6:] for key in gate if key.startswith("month:")}
        if month:
            months.add(month)
        for value in months:
            totals, models = await asyncio.gather(
                redis.hgetall(base + ":month:" + value), redis.hgetall(base + ":models:" + value)
            )
            if not totals or not models or totals.get("epoch") != gate.get("epoch"):
                return False
            if sum(int(v) for k, v in models.items() if k != "_initialized") != int(totals.get("used", -1)):
                return False
            if any(key[6:] not in models for key in gate if key.startswith("model:")):
                return False
        return True

    async def ensure(self, tenant_id: int, user_id: int, month: str | None = None):
        if tenant_id != get_current_tenant_id() or min(tenant_id, user_id) < 1:
            raise ValueError("Recovery requires the trusted tenant/user scope")
        redis = self.quota.redis
        base = f"{self.quota.prefix}:{{{tenant_id}:{user_id}}}"
        async with self.quota.topology.lock:
            await self.quota.topology.check()
        if await self.healthy(base, month):
            return
        owner = uuid4().hex
        lease = base + ":automatic_recovery"
        if not await redis.set(lease, owner, nx=True, px=30000):
            raise QuotaRejected("recovery_in_progress")

        async def apply(command, keys=(), arguments=()):
            result = await redis.eval(
                self.script, len(keys) + 2, lease, base + ":gate", *keys, owner, command, *arguments
            )
            if result[0] != "OK":
                raise QuotaRejected(result[1])

        try:
            # Another process may have completed recovery before this lease was acquired.
            if await self.healthy(base, month):
                return
            await apply("begin")
            snapshot = await asyncio.to_thread(self._snapshot, user_id)
            await apply("renew")
            events, policy, operations = snapshot
            inventory = {event.request_id: event for event in events}
            surviving = set()

            def merge(raw):
                event = UsageEvent.model_validate_json(raw)
                if (event.tenant_id, event.user_id) != (tenant_id, user_id):
                    raise ValueError("Foreign request in Redis recovery partition")
                surviving.add(event.request_id)
                previous = inventory.get(event.request_id)
                if previous is not None:
                    if self.quota._identity(previous) != self.quota._identity(event):
                        raise ValueError("Conflicting request identity during recovery")
                    if previous.event_version > event.event_version:
                        return
                    if previous.event_version == event.event_version:
                        fields = (
                            "status",
                            "input_tokens",
                            "output_tokens",
                            "total_tokens",
                            "cache_read_tokens",
                            "cache_creation_tokens",
                        )
                        if any(getattr(previous, field) != getattr(event, field) for field in fields):
                            raise ValueError("Conflicting request version during recovery")
                inventory[event.request_id] = event

            cursor = "-"
            while True:
                page = await redis.xrange(base + ":events", min=cursor, max="+", count=500)
                if not page:
                    break
                for _, fields in page:
                    merge(fields["event"])
                cursor = "(" + page[-1][0]
                await apply("renew")
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=base + ":request:*", count=100)
                for key in keys:
                    raw = await redis.hget(key, "event")
                    if raw:
                        merge(raw)
                await apply("renew")
                if not cursor:
                    break
            # A SQL-only RUNNING row lost its live request. Preserve its identity, never invent usage.
            for request_id, event in list(inventory.items()):
                if event.status == "RUNNING" and request_id not in surviving:
                    inventory[request_id] = event.model_copy(
                        update={
                            "status": "USAGE_UNKNOWN",
                            "event_version": event.event_version + 1,
                            "error_code": "redis_ledger_lost",
                        }
                    )
            current_month = month or datetime.now(UTC).astimezone(ZoneInfo(self.billing_timezone)).strftime("%Y-%m")
            months = {current_month: {}}
            for event in inventory.values():
                totals = months.setdefault(event.usage_month, {})
                key = str(event.model_id)
                totals[key] = totals.get(key, 0) + (event.total_tokens or 0)
            # Keep intact counters even if their individual Redis request has already been removed.
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=base + ":models:*", count=100)
                for key in keys:
                    totals = months.setdefault(key.rsplit(":", 1)[1], {})
                    for model, value in (await redis.hgetall(key)).items():
                        if model != "_initialized":
                            totals[model] = max(totals.get(model, 0), int(value))
                await apply("renew")
                if not cursor:
                    break
            epoch = policy["quota_epoch"]
            gate = {
                "redis_generation": self.quota.topology.run_id,
                "epoch": str(epoch),
                "version": str(policy["version"]),
                "limit": "0",
                "running_index": "1",
                "running_count": "0",
            }
            blocks = []
            for row in policy["rows"]:
                model = str(row["model_id"])
                gate["version:" + model] = str(row["version"])
                if row["enabled"]:
                    gate["model:" + model] = "1"
                    gate["limit:" + model] = str(row["monthly_token_limit"])
                    gate["limit"] = str(int(gate["limit"]) + row["monthly_token_limit"])
                operation_id = row.get("pending_operation_id")
                if operation_id:
                    operation = operations[operation_id]
                    gate["operation_id:" + model] = operation_id
                    gate["generation:" + model] = str(operation["lease_generation"])
                    gate["installed_version:" + model] = str(row["version"])
                    gate["policy_payload:" + model] = json.dumps(
                        [
                            row["version"],
                            {"model_id": row["model_id"], "monthly_token_limit": row["monthly_token_limit"]},
                            bool(row["enabled"]),
                        ],
                        separators=(",", ":"),
                    )
                    blocks.append("POLICY_SYNC:" + model + ":" + operation_id)
            await apply(
                "reset",
                [base + ":running", base + ":unknown_usage", base + ":blocks"],
                [json.dumps(gate), json.dumps(blocks)],
            )
            for value, totals in months.items():
                for row in policy["rows"]:
                    totals.setdefault(str(row["model_id"]), 0)
                total = sum(totals.values())
                if total > 9223372036854775807 or any(used < 0 for used in totals.values()):
                    raise ValueError("Invalid recovered token counter")
                await apply(
                    "month",
                    [base + ":month:" + value, base + ":models:" + value],
                    [value, str(epoch), str(total), json.dumps({k: str(v) for k, v in totals.items()})],
                )
            items = list(inventory.values())
            for offset in range(0, len(items), 100):
                batch = items[offset : offset + 100]
                await apply(
                    "events",
                    [
                        base + ":events",
                        base + ":running",
                        base + ":unknown_usage",
                        *[base + ":request:" + event.request_id for event in batch],
                    ],
                    [
                        json.dumps(
                            [
                                {
                                    "id": event.request_id,
                                    "event": event.model_dump_json(),
                                    "version": str(event.event_version),
                                    "status": event.status,
                                    "month": event.usage_month,
                                    "model": str(event.model_id),
                                    "epoch": str(event.quota_epoch),
                                    "identity": self.quota._identity(event),
                                    "started": str(int(event.started_at.timestamp() * 1000)),
                                }
                                for event in batch
                            ]
                        )
                    ],
                )
            counts, cursor = {}, "-"
            while True:
                page = await redis.xrange(base + ":events", min=cursor, max="+", count=500)
                if not page:
                    break
                for _, fields in page:
                    event = UsageEvent.model_validate_json(fields["event"])
                    counts[event.request_id] = counts.get(event.request_id, 0) + 1
                cursor = "(" + page[-1][0]
                await apply("renew")
            values = list(counts.items())
            for offset in range(0, len(values), 100):
                batch = values[offset : offset + 100]
                await apply(
                    "counts", [base + ":request:" + key for key, _ in batch], [str(count) for _, count in batch]
                )
            await asyncio.to_thread(self._complete, user_id, policy, epoch)
            await apply("finish")
            logger.bind(tenant_id=tenant_id, user_id=user_id, recovered_requests=len(items)).warning(
                "DSH Redis ledger recovered from SQL and surviving Redis records; unpersisted lost usage cannot be reconstructed"
            )
        finally:
            await redis.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                1,
                lease,
                owner,
            )

    def _snapshot(self, user_id):
        with self.repository_scope() as repository:
            return repository.automatic_recovery_snapshot(user_id, billing_timezone=self.billing_timezone)

    def _complete(self, user_id, policy, epoch):
        with self.repository_scope() as repository:
            repository.complete_recovery(user_id, expected_policy=policy, epoch=epoch)
