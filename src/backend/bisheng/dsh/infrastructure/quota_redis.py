"""Dedicated Redis ledger; no ordinary cache, TTL, reservation, or automatic replay."""

import hashlib
import json
from datetime import UTC
from pathlib import Path
from uuid import uuid4

from loguru import logger
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig, validate_model_configs
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.infrastructure.quota_topology import QuotaTopology


class QuotaRejected(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class QuotaRedis:
    def __init__(
        self,
        redis: Redis,
        topology: QuotaTopology,
        *,
        prefix: str = "dsh_quota",
        memory_budget_bytes: int = 536870912,
        memory_headroom_bytes: int = 67108864,
        backlog_high_watermark: int = 10000,
        backlog_stop_seconds: int = 30,
    ):
        if any(c in prefix for c in "{}"):
            raise ValueError("Prefix may not override the user hash tag")
        if (
            not 0 <= memory_headroom_bytes < memory_budget_bytes
            or min(backlog_high_watermark, backlog_stop_seconds) < 1
        ):
            raise ValueError("Quota storage requires finite positive capacity and backlog bounds")
        self.redis, self.topology, self.prefix = redis, topology, prefix
        self.memory_budget_bytes, self.memory_headroom_bytes = memory_budget_bytes, memory_headroom_bytes
        self.backlog_high_watermark, self.backlog_stop_seconds = backlog_high_watermark, backlog_stop_seconds

    def pressure_args(self):
        return list(
            map(
                str,
                (
                    0 if getattr(self.topology, "shared", False) is True else self.memory_budget_bytes,
                    self.memory_headroom_bytes,
                    self.backlog_high_watermark,
                    self.backlog_stop_seconds * 1000,
                ),
            )
        )

    def script(self, name):
        folder = Path(__file__).parent / "lua"
        common = (folder / "pressure.lua").read_text() if name in {"admit.lua", "read_usage.lua"} else ""
        return common + (folder / name).read_text()

    def keys(self, event: UsageEvent):
        base = f"{self.prefix}:{{{event.tenant_id}:{event.user_id}}}"
        return [
            f"{base}:gate",
            f"{base}:month:{event.usage_month}",
            f"{base}:models:{event.usage_month}",
            f"{base}:blocks",
            f"{base}:request:{event.request_id}",
            f"{base}:events",
        ]

    async def _execute(self, script: str, event: UsageEvent, args: list[str]):
        async with self.topology.lock:
            try:
                await self.topology.check()
                if script == "admit.lua" and event.quota_epoch != self.topology.epoch:
                    raise QuotaRejected("event_epoch_mismatch")
                source = self.script(script)
                keys = self.keys(event)
                keys.append(keys[0].removesuffix(":gate") + ":running")
                keys.append(keys[0].removesuffix(":gate") + ":unknown_usage")
                result = await self.redis.eval(source, len(keys), *keys, *args)
            except QuotaRejected:
                raise
            except (RedisError, RuntimeError) as exc:
                self.topology.close()
                raise QuotaRejected("quota_unavailable") from exc
        if result[0] == "DENY":
            if script == "admit.lua" and result[1] in {
                "capacity_backpressure",
                "capacity_unknown",
                "projection_backpressure",
            }:
                logger.bind(
                    event="dsh_quota_backpressure", reason=result[1], tenant_id=event.tenant_id, user_id=event.user_id
                ).warning("DSH quota admission paused")
            raise QuotaRejected(result[1])
        if script == "admit.lua" and result[0] == "EXISTS":
            raise QuotaRejected("request_already_started")
        return UsageEvent.model_validate_json(result[1])

    async def check_and_start(self, event: UsageEvent) -> UsageEvent:
        event = UsageEvent.model_validate(event.model_dump())
        if event.status != "RUNNING" or event.event_version != 1:
            raise ValueError("Admission requires a new server-owned running event")
        return await self._execute(
            "admit.lua",
            event,
            [
                str(event.quota_epoch),
                str(event.policy_version),
                str(event.model_id),
                event.model_dump_json(),
                event.usage_month,
                self._identity(event),
                *self.pressure_args(),
                event.request_id,
                str(int(event.started_at.replace(tzinfo=UTC).timestamp() * 1000)),
            ],
        )

    async def get_request(self, event: UsageEvent) -> UsageEvent | None:
        async with self.topology.lock:
            await self.topology.check()
            value = await self.redis.hget(self.keys(event)[4], "event")
            return UsageEvent.model_validate_json(value) if value else None

    async def record_usage(self, event: UsageEvent, expected_version: int) -> UsageEvent:
        event = UsageEvent.model_validate(event.model_dump())
        if event.event_version != expected_version + 1 or event.status == "RUNNING":
            raise ValueError("Settlement requires the next event version and a terminal or unknown state")
        try:
            return await self._execute(
                "settle.lua",
                event,
                [
                    str(self.topology.epoch),
                    str(expected_version),
                    str(event.event_version),
                    str(event.model_id),
                    event.usage_month,
                    event.status,
                    "" if event.total_tokens is None else str(event.total_tokens),
                    event.request_id,
                    event.model_dump_json(),
                    event.operation_id or "",
                    event.payload_hash or "",
                    str(event.quota_epoch),
                    self._identity(event),
                    str(event.operation_generation or 0),
                ],
            )
        except QuotaRejected as error:
            # Definite validation/CAS denials did not write; only uncertain storage needs quarantine.
            if error.reason not in {"quota_unavailable", "ledger_write_incomplete"}:
                raise
            try:
                if await self.quarantine_uncertain(event) == "CONFIRMED":
                    return event
            except Exception:
                logger.error("DSH settlement quarantine unavailable request={}", event.request_id)
            raise

    async def quarantine_uncertain(self, terminal: UsageEvent) -> str:
        """A separate connection can only confirm this primary's exact event or close admission."""
        unknown = terminal.model_copy(
            update={
                "status": "USAGE_UNKNOWN",
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "usage_source": None,
                "settled_at": None,
                "error_code": "settlement_unconfirmed",
            }
        )
        pool = ConnectionPool(
            connection_class=self.redis.connection_pool.connection_class, **self.redis.connection_pool.connection_kwargs
        )
        control = Redis(connection_pool=pool, single_connection_client=True)
        keys = self.keys(terminal)
        try:
            result = await control.eval(
                (Path(__file__).parent / "lua" / "quarantine.lua").read_text(),
                5,
                keys[0],
                keys[3],
                keys[4],
                keys[5],
                keys[0].removesuffix(":gate") + ":running",
                self.topology.run_id or "",
                terminal.model_dump_json(),
                self._identity(terminal),
                terminal.request_id,
                unknown.model_dump_json(),
                str(terminal.event_version - 1),
                str(terminal.event_version),
            )
            return result[0]
        finally:
            await control.aclose()
            await pool.disconnect()

    async def _policy(self, tenant_id: int, user_id: int, args: list[str]):
        if min(tenant_id, user_id) < 1:
            raise ValueError("Policy identity must be positive")
        base = f"{self.prefix}:{{{tenant_id}:{user_id}}}"
        async with self.topology.lock:
            try:
                await self.topology.check()
                keys = [base + ":gate", base + ":blocks"]
                if args[0] == "install":
                    months = [key async for key in self.redis.scan_iter(base + ":month:*")]
                    if len(months) > 1000:
                        raise QuotaRejected("policy_month_inventory_too_large")
                    for key in sorted(months):
                        keys.extend([key, key.replace(":month:", ":models:")])
                result = await self.redis.eval(
                    (Path(__file__).parent / "lua" / "policy.lua").read_text(),
                    len(keys),
                    *keys,
                    *args,
                )
            except (RedisError, RuntimeError) as exc:
                self.topology.close()
                raise QuotaRejected("quota_unavailable") from exc
        if result[0] == "DENY":
            raise QuotaRejected(result[1])

    async def block_policy(
        self,
        tenant_id: int,
        user_id: int,
        *,
        model_id: int,
        operation_id: str,
        lease_generation: int,
        epoch: int,
        expected_version: int,
    ):
        self._policy_arguments(operation_id, lease_generation, epoch, expected_version)
        await self._policy(
            tenant_id,
            user_id,
            ["block", operation_id, str(lease_generation), str(epoch), str(expected_version), str(model_id)],
        )

    async def install_policy(
        self,
        tenant_id: int,
        user_id: int,
        *,
        model_id: int,
        operation_id: str,
        lease_generation: int,
        epoch: int,
        expected_version: int,
        version: int,
        monthly_token_limit: int,
        enabled: bool,
    ):
        import json

        self._policy_arguments(operation_id, lease_generation, epoch, expected_version)
        config = DshModelQuotaConfig(model_id=model_id, monthly_token_limit=monthly_token_limit)
        if version != expected_version + 1 or type(enabled) is not bool:
            raise ValueError("Invalid model policy transition")
        payload = json.dumps([version, config.model_dump(), enabled], separators=(",", ":"))
        await self._policy(
            tenant_id,
            user_id,
            [
                "install",
                operation_id,
                str(lease_generation),
                str(epoch),
                str(expected_version),
                str(model_id),
                str(version),
                str(monthly_token_limit),
                payload,
                "1" if enabled else "0",
            ],
        )

    async def finish_policy(
        self,
        tenant_id: int,
        user_id: int,
        *,
        model_id: int,
        operation_id: str,
        lease_generation: int,
        epoch: int,
        expected_policy_version: int,
    ):
        self._policy_arguments(operation_id, lease_generation, epoch, expected_policy_version)
        await self._policy(
            tenant_id,
            user_id,
            ["finish", operation_id, str(lease_generation), str(epoch), str(expected_policy_version), str(model_id)],
        )

    @staticmethod
    def _policy_arguments(operation_id: str, generation: int, epoch: int, version: int):
        if (
            not operation_id
            or len(operation_id) > 36
            or any(type(n) is not int for n in [generation, epoch, version])
            or generation < 1
            or epoch < 1
            or version < 0
        ):
            raise ValueError("Invalid policy ownership fencing arguments")

    @staticmethod
    def _identity(event: UsageEvent) -> str:
        fields = (
            "request_id",
            "tenant_id",
            "user_id",
            "seat_id",
            "session_id",
            "grant_version",
            "model_id",
            "usage_month",
            "billing_timezone",
            "policy_version",
            "quota_epoch",
            "started_at",
        )
        data = event.model_dump(mode="json", include=set(fields))
        started = event.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        data["started_at"] = started.astimezone(UTC).isoformat()
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def restore_manifest(self, manifest, inventory: dict[str, UsageEvent], verify_covered):
        """Atomically restore one user after an external complete-tail audit and primary fencing."""
        if manifest.shards:
            from bisheng.dsh.infrastructure.quota_restore import restore_sharded

            return await restore_sharded(self, manifest, inventory, verify_covered)
        base = f"{self.prefix}:{{{manifest.tenant_id}:{manifest.user_id}}}"
        owner = uuid4().hex
        digest = hashlib.sha256(manifest.model_dump_json().encode()).hexdigest()
        async with self.topology.lock:
            self.topology.close()
            # Close the shared gate before any reconstruction. Failure leaves it closed.
            await self.redis.hset(base + ":gate", "state", "FROZEN")
            try:
                await self.topology.approve(
                    manifest.run_id,
                    manifest.epoch,
                    old_primary_isolated=manifest.old_primary_isolated,
                    ledger_proven=manifest.confirmed_tail_complete,
                )
                # Surviving Stream must also be covered by the audited event inventory.
                cursor = "-"
                while True:
                    batch = await self.redis.xrange(base + ":events", min=cursor, max="+", count=500)
                    if not batch:
                        break
                    for _, fields in batch:
                        verify_covered(UsageEvent.model_validate_json(fields["event"]), inventory)
                    cursor = "(" + batch[-1][0]
                cursor = 0
                while True:
                    cursor, surviving = await self.redis.scan(cursor, match=base + ":request:*", count=100)
                    for key in surviving:
                        value = await self.redis.hget(key, "event")
                        if value is None:
                            raise QuotaRejected("missing_request_ledger")
                        verify_covered(UsageEvent.model_validate_json(value), inventory)
                    if cursor == 0:
                        break
                months = {manifest.current_month: {str(m): 0 for m in manifest.model_ids}}
                events = []
                for original in inventory.values():
                    event = original
                    if event.status == "RUNNING":
                        event = event.model_copy(
                            update={
                                "status": "USAGE_UNKNOWN",
                                "event_version": event.event_version + 1,
                                "error_code": "interrupted_unknown",
                            }
                        )
                    totals = months.setdefault(event.usage_month, {})
                    totals[str(event.model_id)] = totals.get(str(event.model_id), 0) + (event.total_tokens or 0)
                    events.append(event)
                for totals in months.values():
                    for model in manifest.model_ids:
                        totals.setdefault(str(model), 0)
                    if sum(totals.values()) > 9223372036854775807:
                        raise ValueError("Recovered counter exceeds int64")
                keys = [base + ":gate", base + ":unknown_usage", base + ":events"]
                args = [
                    str(manifest.previous_epoch),
                    str(manifest.epoch),
                    str(manifest.policy_version),
                    str(manifest.monthly_limit),
                    str(len(manifest.model_ids)),
                    *[
                        value
                        for item in manifest.model_configs
                        for value in (str(item.model_id), str(item.monthly_token_limit))
                    ],
                    str(len(manifest.model_versions)),
                    *[
                        value
                        for model, version in sorted(manifest.model_versions.items())
                        for value in (str(model), str(version))
                    ],
                    str(len(months)),
                ]
                for month, totals in sorted(months.items()):
                    keys.extend([base + ":month:" + month, base + ":models:" + month])
                    args.extend([str(sum(totals.values())), str(len(totals))])
                    for model, total in sorted(totals.items()):
                        args.extend([model, str(total)])
                args.append(str(len(events)))
                for event in events:
                    keys.append(base + ":request:" + event.request_id)
                    args.extend(
                        [
                            event.model_dump_json(),
                            str(event.event_version),
                            event.status,
                            event.usage_month,
                            str(event.model_id),
                            str(event.quota_epoch),
                            self._identity(event),
                            event.request_id,
                        ]
                    )
                args.extend([digest, owner])
                result = await self.redis.eval(
                    (Path(__file__).parent / "lua" / "recover.lua").read_text(), len(keys), *keys, *args
                )
                if result[0] != "OK":
                    raise QuotaRejected(result[1])
                from bisheng.dsh.infrastructure.quota_restore import rebuild_retained_counts

                await rebuild_retained_counts(self, base, owner)
                await self.redis.delete(base + ":running")
                return {"owner": owner, "digest": digest}
            except Exception:
                self.topology.close()
                raise

    async def finish_recovery(self, manifest, receipt: dict):
        digest = hashlib.sha256(manifest.model_dump_json().encode()).hexdigest()
        if receipt.get("digest") != digest or not receipt.get("owner"):
            raise QuotaRejected("invalid_recovery_receipt")
        async with self.topology.lock:
            await self.topology.check()
            result = await self.redis.eval(
                (Path(__file__).parent / "lua" / "finish_recovery.lua").read_text(),
                2,
                f"{self.prefix}:{{{manifest.tenant_id}:{manifest.user_id}}}:gate",
                f"{self.prefix}:{{{manifest.tenant_id}:{manifest.user_id}}}:blocks",
                receipt["owner"],
                digest,
                str(manifest.epoch),
                str(manifest.policy_version),
            )
            if result[0] != "OK":
                raise QuotaRejected(result[1])

    async def claim_reconciliation(self, event: UsageEvent, *, operation_id: str, payload_hash: str, generation: int):
        self._policy_arguments(operation_id, generation, self.topology.epoch, event.event_version)
        if len(payload_hash) != 64:
            raise ValueError("Invalid reconciliation payload digest")
        async with self.topology.lock:
            await self.topology.check()
            keys = self.keys(event)
            result = await self.redis.eval(
                (Path(__file__).parent / "lua" / "claim_reconcile.lua").read_text(),
                2,
                keys[4],
                keys[0],
                operation_id,
                payload_hash,
                str(generation),
                str(self.topology.epoch),
            )
            if result[0] != "OK":
                raise QuotaRejected(result[1])

    async def read_usage(self, tenant_id: int, user_id: int, usage_month: str) -> dict:
        import re
        from datetime import UTC, datetime

        if min(tenant_id, user_id) < 1 or re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", usage_month) is None:
            raise ValueError("Invalid usage dimension")
        base = f"{self.prefix}:{{{tenant_id}:{user_id}}}"
        async with self.topology.lock:
            try:
                await self.topology.check()
                result = await self.redis.eval(
                    self.script("read_usage.lua"),
                    7,
                    base + ":gate",
                    base + ":month:" + usage_month,
                    base + ":models:" + usage_month,
                    base + ":blocks",
                    base + ":events",
                    base + ":running",
                    base + ":unknown_usage",
                    str(self.topology.epoch),
                    *self.pressure_args(),
                )
            except (RedisError, RuntimeError) as exc:
                self.topology.close()
                raise QuotaRejected("quota_unavailable") from exc
        if result[0] != "OK":
            raise QuotaRejected(result[1])
        used, limit = int(result[1]), int(result[2])
        model_values = result[6]
        models = {
            model_values[i]: int(model_values[i + 1])
            for i in range(0, len(model_values), 2)
            if model_values[i] != "_initialized"
        }
        limit_values = result[8]
        model_limits = {limit_values[i]: int(limit_values[i + 1]) for i in range(0, len(limit_values), 2)}
        return {
            "used": used,
            "limit": limit,
            "remaining": sum(max(allowed - models.get(model, 0), 0) for model, allowed in model_limits.items()),
            "model_limits": model_limits,
            "source": "live",
            "as_of": datetime.fromtimestamp(int(result[4]) + int(result[5]) / 1000000, UTC),
            "quota_state": result[3],
            "unknown_pending": int(result[7]),
            "models": {
                model_values[i]: int(model_values[i + 1])
                for i in range(0, len(model_values), 2)
                if model_values[i] != "_initialized"
            },
        }

    async def ensure_new_user(
        self, tenant_id: int, user_id: int, *, operation_id: str, lease_generation: int, epoch: int, proof: dict
    ):
        """Only the transaction-owned initial policy operation may provide this repository proof."""
        expected = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "operation_id": operation_id,
            "lease_generation": lease_generation,
            "policy_version": 0,
            "history_empty": True,
        }
        if proof != expected or proof.get("history_empty") is not True or type(proof.get("policy_version")) is not int:
            raise ValueError("Initial user ledger requires a trusted version-zero repository proof")
        self._policy_arguments(operation_id, lease_generation, epoch, 0)
        base = f"{self.prefix}:{{{tenant_id}:{user_id}}}"
        async with self.topology.lock:
            await self.topology.check()
            if epoch != self.topology.epoch:
                raise QuotaRejected("epoch_conflict")
            if not await self.redis.exists(base + ":gate"):
                async for _key in self.redis.scan_iter(base + ":request:*"):
                    raise QuotaRejected("unexpected_user_history")
            result = await self.redis.eval(
                (Path(__file__).parent / "lua" / "initialize_user.lua").read_text(),
                3,
                base + ":gate",
                base + ":blocks",
                base + ":events",
                str(epoch),
                operation_id,
            )
            if result[0] != "OK":
                raise QuotaRejected(result[1])

    async def ensure_month(self, tenant_id: int, user_id: int, usage_month: str, *, proof: dict):
        """Controlled month creation: SQL absence plus the approved user's permanent month inventory."""
        if (
            proof.get("tenant_id") != tenant_id
            or proof.get("user_id") != user_id
            or proof.get("usage_month") != usage_month
            or proof.get("history_empty") is not True
        ):
            raise ValueError("Month initialization requires a scoped SQL history proof")
        base = f"{self.prefix}:{{{tenant_id}:{user_id}}}"
        async with self.topology.lock:
            await self.topology.check()
            if await self.redis.hexists(base + ":gate", "month:" + usage_month):
                if await self.redis.exists(base + ":month:" + usage_month, base + ":models:" + usage_month) != 2:
                    raise QuotaRejected("lost_month_ledger")
                return
            async for key in self.redis.scan_iter(base + ":request:*"):
                value = await self.redis.hget(key, "event")
                if value is None:
                    raise QuotaRejected("missing_request_ledger")
                if UsageEvent.model_validate_json(value).usage_month == usage_month:
                    raise QuotaRejected("unexpected_month_history")
            cursor = "-"
            while True:
                batch = await self.redis.xrange(base + ":events", min=cursor, max="+", count=500)
                if not batch:
                    break
                for _, fields in batch:
                    if UsageEvent.model_validate_json(fields["event"]).usage_month == usage_month:
                        raise QuotaRejected("unexpected_month_history")
                cursor = "(" + batch[-1][0]
            result = await self.redis.eval(
                (Path(__file__).parent / "lua" / "initialize_month.lua").read_text(),
                3,
                base + ":gate",
                base + ":month:" + usage_month,
                base + ":models:" + usage_month,
                str(self.topology.epoch),
                str(proof["policy_version"]),
                usage_month,
                *[
                    value
                    for item in validate_model_configs(proof["model_configs"])
                    for value in (str(item.model_id), str(item.monthly_token_limit))
                ],
            )
            if result[0] != "OK":
                raise QuotaRejected(result[1])
