"""Bounded Redis recovery writes after complete, cross-shard evidence validation."""

import hashlib
from pathlib import Path
from uuid import uuid4

from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected


def recovered_inventory(inventory):
    return {
        key: event.model_copy(
            update={
                "status": "USAGE_UNKNOWN",
                "event_version": event.event_version + 1,
                "error_code": "interrupted_unknown",
            }
        )
        if event.status == "RUNNING"
        else event
        for key, event in inventory.items()
    }


async def restore_sharded(quota, manifest, inventory, verify_covered):
    base = f"{quota.prefix}:{{{manifest.tenant_id}:{manifest.user_id}}}"
    gate, unknown_usage, stream = base + ":gate", base + ":unknown_usage", base + ":events"
    redis = quota.redis
    owner = uuid4().hex
    digest = hashlib.sha256(manifest.model_dump_json().encode()).hexdigest()
    script = (Path(__file__).parent / "lua" / "recover_shard.lua").read_text()
    inventory = recovered_inventory(inventory)

    async def apply(command, keys, arguments):
        result = await redis.eval(script, len(keys), *keys, command, owner, *arguments)
        if result[0] != "OK":
            raise QuotaRejected(result[1])

    async with quota.topology.lock:
        quota.topology.close()
        if redis.connection is not None:
            redis.connection.recovery_connect_allowed = True
        await redis.hset(gate, "state", "FROZEN")
        try:
            await quota.topology.approve(
                manifest.run_id,
                manifest.epoch,
                old_primary_isolated=manifest.old_primary_isolated,
                ledger_proven=manifest.confirmed_tail_complete,
            )
            await apply(
                "begin",
                [gate],
                [
                    str(manifest.previous_epoch),
                    str(manifest.request_count),
                    str(manifest.epoch),
                    digest,
                ],
            )
            # The gate blocks both new calls and late settlements while all survivors are inspected.
            cursor = "-"
            while True:
                page = await redis.xrange(stream, min=cursor, max="+", count=500)
                if not page:
                    break
                for _, fields in page:
                    verify_covered(UsageEvent.model_validate_json(fields["event"]), inventory)
                cursor = "(" + page[-1][0]
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=base + ":request:*", count=100)
                for key in keys:
                    value = await redis.hget(key, "event")
                    if value is None:
                        raise QuotaRejected("missing_request_ledger")
                    verify_covered(UsageEvent.model_validate_json(value), inventory)
                if cursor == 0:
                    break
            months = {manifest.current_month: {str(model): 0 for model in manifest.model_ids}}
            for event in inventory.values():
                totals = months.setdefault(event.usage_month, {})
                model = str(event.model_id)
                totals[model] = totals.get(model, 0) + (event.total_tokens or 0)
            for month, totals in months.items():
                for model in manifest.model_ids:
                    totals.setdefault(str(model), 0)
                if sum(totals.values()) > 9223372036854775807:
                    raise ValueError("Recovered counter exceeds int64")
                arguments = [str(manifest.epoch), str(sum(totals.values())), month]
                for model, used in sorted(totals.items()):
                    arguments.extend([model, str(used)])
                await apply("month", [gate, base + ":month:" + month, base + ":models:" + month], arguments)
            # Rebuild the diagnostic index; it is never an admission blocker.
            await redis.delete(unknown_usage)
            events = list(inventory.values())
            for offset in range(0, len(events), 500):
                keys, arguments = [gate, unknown_usage, stream], [str(offset)]
                for event in events[offset : offset + 500]:
                    keys.append(base + ":request:" + event.request_id)
                    arguments.extend(
                        [
                            event.model_dump_json(),
                            str(event.event_version),
                            event.status,
                            event.usage_month,
                            str(event.model_id),
                            str(event.quota_epoch),
                            quota._identity(event),
                            event.request_id,
                        ]
                    )
                await apply("events", keys, arguments)
            await redis.delete(base + ":running")
            await apply(
                "finish",
                [gate],
                [
                    str(manifest.epoch),
                    str(manifest.policy_version),
                    str(manifest.monthly_limit),
                    str(len(manifest.model_configs)),
                    *[
                        value
                        for item in manifest.model_configs
                        for value in (str(item.model_id), str(item.monthly_token_limit))
                    ],
                    *[
                        value
                        for model, version in sorted(manifest.model_versions.items())
                        for value in (str(model), str(version))
                    ],
                ],
            )
            await rebuild_retained_counts(quota, base, owner)
            return {"owner": owner, "digest": digest}
        except Exception:
            quota.topology.close()
            raise


async def rebuild_retained_counts(quota, base: str, owner: str):
    """Rebuild counts from every surviving/reconstructed event before READY, including legacy streams."""
    counts, cursor = {}, "-"
    while True:
        page = await quota.redis.xrange(base + ":events", min=cursor, max="+", count=500)
        if not page:
            break
        for _, fields in page:
            event = UsageEvent.model_validate_json(fields["event"])
            key = base + ":request:" + event.request_id
            counts[key] = counts.get(key, 0) + 1
        cursor = "(" + page[-1][0]
    items = list(counts.items())
    for offset in range(0, len(items), 500):
        batch = items[offset : offset + 500]
        result = await quota.redis.eval(
            "if redis.call('HGET',KEYS[1],'state')~='FROZEN' or redis.call('HGET',KEYS[1],'recovery_owner')~=ARGV[1] then return 0 end "
            "for i=2,#KEYS do if redis.call('TYPE',KEYS[i]).ok~='hash' then return 0 end end "
            "for i=2,#KEYS do redis.call('HSET',KEYS[i],'retained_stream_count',ARGV[i]) end return 1",
            len(batch) + 1,
            base + ":gate",
            *[key for key, _ in batch],
            owner,
            *[str(count) for _, count in batch],
        )
        if result != 1:
            raise QuotaRejected("recovery_fence_lost")
