import asyncio
import json
from datetime import UTC, datetime, timedelta

from bisheng.llm.domain.services.model_rate_limit_state import (
    ModelRateLimitState,
    ModelRateLimitStateService,
)


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class InMemoryLuaRedis:
    """Emulates the four Lua operations while preserving raw Redis JSON shape."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.eval_calls: list[str] = []

    async def eval(self, script: str, numkeys: int, key: str, *args):
        assert numkeys == 1
        self.eval_calls.append(script)
        current = json.loads(self.values[key]) if key in self.values else None

        if "operation:mark_busy" in script:
            now_epoch, ttl = int(args[0]), int(args[1])
            version = int(args[2])
            new_probe_token = str(args[3])
            previous_probe_state = current.get("probe_state") if current else None
            preserve_scheduled = bool(
                previous_probe_state == "scheduled" and current.get("probe_token") and current.get("probe_attempt")
            )
            should_schedule = not preserve_scheduled
            current = {
                "state": "recovering",
                "version": version,
                "limited_at": now_epoch,
                "busy_until": now_epoch + ttl,
                "probe_state": "scheduled",
                "probe_attempt": current["probe_attempt"] if preserve_scheduled else 1,
                "probe_token": current["probe_token"] if preserve_scheduled else new_probe_token,
                "last_probe_at": current.get("last_probe_at") if current else None,
            }
            self.values[key] = json.dumps(current)
            self.ttls[key] = ttl
            return [json.dumps(current), int(should_schedule)]

        if "operation:begin_probe" in script:
            if (
                current is None
                or current.get("probe_state") != "scheduled"
                or current.get("probe_token") != str(args[1])
                or int(current.get("probe_attempt", 0)) != int(args[2])
            ):
                return [0, 0]
            current["probe_state"] = "running"
            current["last_probe_at"] = int(args[0])
            self.values[key] = json.dumps(current)
            return [1, int(current["version"])]

        if "operation:record_probe_limit" in script:
            expected_version, probe_attempt, exhausted = int(args[0]), int(args[1]), bool(int(args[2]))
            next_probe_token = str(args[3])
            if (
                current is None
                or int(current["version"]) != expected_version
                or current.get("probe_state") != "running"
                or int(current["probe_attempt"]) != probe_attempt
            ):
                return 0
            current["probe_state"] = "exhausted" if exhausted else "scheduled"
            current["state"] = "busy" if exhausted else "recovering"
            if not exhausted:
                current["probe_attempt"] = probe_attempt + 1
                current["probe_token"] = next_probe_token
            self.values[key] = json.dumps(current)
            return 1

        if "operation:clear_version" in script:
            if current is None or int(current["version"]) != int(args[0]):
                return 0
            self.values.pop(key, None)
            self.ttls.pop(key, None)
            return 1

        raise AssertionError("unknown Lua operation")

    async def get(self, key: str):
        return self.values.get(key)

    async def mget(self, keys: list[str]):
        return [self.values.get(key) for key in keys]

    async def delete(self, key: str):
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)

    async def ttl(self, key: str):
        return self.ttls.get(key, -2)


def service(*, ttl_seconds: int = 300, versions: list[int] | None = None):
    redis = InMemoryLuaRedis()
    clock = MutableClock()
    version_values = iter(versions) if versions is not None else None
    version_factory = (lambda: next(version_values)) if version_values is not None else None
    return (
        ModelRateLimitStateService(
            redis=redis,
            ttl_seconds=ttl_seconds,
            clock=clock,
            version_factory=version_factory,
        ),
        redis,
        clock,
    )


async def test_first_limit_marks_recovering_and_schedules_probe() -> None:
    svc, redis, clock = service(versions=[101])

    result = await svc.mark_busy(tenant_id=2, model_id=17)

    assert result.should_schedule is True
    assert result.probe_token
    assert result.view.rate_limit_state == ModelRateLimitState.RECOVERING
    assert result.view.status_version == 101
    assert result.view.busy_until == clock.now + timedelta(seconds=300)
    assert redis.ttls["model_rate_limit:2:17"] == 300


async def test_queued_probe_adopts_latest_version_without_duplicate_schedule() -> None:
    svc, _, _ = service(versions=[101, 102])
    first = await svc.mark_busy(tenant_id=2, model_id=17)
    second = await svc.mark_busy(tenant_id=2, model_id=17)

    claimed_version = await svc.begin_probe(
        tenant_id=2,
        model_id=17,
        probe_token=first.probe_token,
        probe_attempt=1,
    )

    assert first.should_schedule is True
    assert second.should_schedule is False
    assert second.probe_token == first.probe_token
    assert second.view.status_version == 102
    assert claimed_version == 102


async def test_probe_from_deleted_key_cannot_claim_recreated_state() -> None:
    svc, redis, _ = service(versions=[101, 202])
    first = await svc.mark_busy(tenant_id=2, model_id=17)
    await redis.delete("model_rate_limit:2:17")
    recreated = await svc.mark_busy(tenant_id=2, model_id=17)

    assert recreated.probe_token != first.probe_token
    assert (
        await svc.begin_probe(
            tenant_id=2,
            model_id=17,
            probe_token=first.probe_token,
            probe_attempt=1,
        )
        is None
    )


async def test_new_limit_during_running_probe_invalidates_old_result_and_schedules_successor() -> None:
    svc, _, _ = service(versions=[101, 102, 103])
    first = await svc.mark_busy(tenant_id=2, model_id=17)
    running_version = await svc.begin_probe(
        tenant_id=2,
        model_id=17,
        probe_token=first.probe_token,
        probe_attempt=1,
    )

    newer = await svc.mark_busy(tenant_id=2, model_id=17)

    assert newer.should_schedule is True
    assert await svc.clear_if_version(tenant_id=2, model_id=17, observed_version=running_version) is False
    successor_version = await svc.begin_probe(
        tenant_id=2,
        model_id=17,
        probe_token=newer.probe_token,
        probe_attempt=1,
    )
    assert successor_version == newer.view.status_version
    assert await svc.clear_if_version(tenant_id=2, model_id=17, observed_version=successor_version) is True


async def test_probe_exhaustion_moves_projection_to_busy() -> None:
    svc, _, _ = service()
    marked = await svc.mark_busy(tenant_id=2, model_id=17)
    version = await svc.begin_probe(
        tenant_id=2,
        model_id=17,
        probe_token=marked.probe_token,
        probe_attempt=1,
    )

    changed = await svc.record_probe_rate_limited(
        tenant_id=2,
        model_id=17,
        observed_version=version,
        probe_attempt=1,
        exhausted=True,
    )
    view = await svc.get_state(tenant_id=2, model_id=17)

    assert changed.changed is True
    assert view.rate_limit_state == ModelRateLimitState.BUSY


async def test_non_exhausted_probe_can_be_claimed_for_next_attempt() -> None:
    svc, _, _ = service()
    marked = await svc.mark_busy(tenant_id=2, model_id=17)
    version = await svc.begin_probe(
        tenant_id=2,
        model_id=17,
        probe_token=marked.probe_token,
        probe_attempt=1,
    )
    transition = await svc.record_probe_rate_limited(
        tenant_id=2,
        model_id=17,
        observed_version=version,
        probe_attempt=1,
        exhausted=False,
    )
    assert transition.changed
    assert transition.next_probe_token

    assert (
        await svc.begin_probe(
            tenant_id=2,
            model_id=17,
            probe_token=transition.next_probe_token,
            probe_attempt=2,
        )
        == version
    )


async def test_delayed_result_from_previous_attempt_cannot_overwrite_running_attempt() -> None:
    svc, _, _ = service()
    marked = await svc.mark_busy(tenant_id=2, model_id=17)
    version = await svc.begin_probe(
        tenant_id=2,
        model_id=17,
        probe_token=marked.probe_token,
        probe_attempt=1,
    )
    transition = await svc.record_probe_rate_limited(
        tenant_id=2,
        model_id=17,
        observed_version=version,
        probe_attempt=1,
        exhausted=False,
    )
    assert transition.changed
    assert transition.next_probe_token
    assert await svc.begin_probe(
        tenant_id=2,
        model_id=17,
        probe_token=transition.next_probe_token,
        probe_attempt=2,
    )

    delayed = await svc.record_probe_rate_limited(
        tenant_id=2,
        model_id=17,
        observed_version=version,
        probe_attempt=1,
        exhausted=True,
    )
    assert delayed.changed is False


async def test_list_states_uses_cross_slot_safe_cluster_read() -> None:
    svc, redis, _ = service()
    await svc.mark_busy(tenant_id=2, model_id=17)
    redis.mget_nonatomic = redis.mget

    async def reject_cross_slot_mget(keys: list[str]):
        raise AssertionError(f"plain MGET must not be used for cluster keys: {keys}")

    redis.mget = reject_cross_slot_mget

    states = await svc.list_states(tenant_id=2, model_ids=[17, 18])

    assert states[17].rate_limit_state == ModelRateLimitState.RECOVERING
    assert states[18].rate_limit_state == ModelRateLimitState.NORMAL


async def test_repeated_limit_refreshes_ttl_and_busy_until() -> None:
    svc, redis, clock = service(ttl_seconds=60)
    first = await svc.mark_busy(tenant_id=2, model_id=17)
    clock.advance(30)
    second = await svc.mark_busy(tenant_id=2, model_id=17)

    assert second.view.busy_until == first.view.busy_until + timedelta(seconds=30)
    assert redis.ttls["model_rate_limit:2:17"] == 60


async def test_list_states_preserves_tenant_and_model_isolation() -> None:
    svc, _, _ = service(versions=[101, 102, 103])
    await svc.mark_busy(tenant_id=2, model_id=17)
    await svc.mark_busy(tenant_id=2, model_id=18)
    await svc.mark_busy(tenant_id=3, model_id=17)

    tenant_two = await svc.list_states(tenant_id=2, model_ids=[17, 18, 19])
    tenant_three = await svc.list_states(tenant_id=3, model_ids=[17, 18])

    assert tenant_two[17].status_version == 101
    assert tenant_two[18].status_version == 102
    assert tenant_two[19].rate_limit_state == ModelRateLimitState.NORMAL
    assert tenant_three[17].status_version == 103
    assert tenant_three[18].rate_limit_state == ModelRateLimitState.NORMAL


async def test_concurrent_limits_have_one_queued_probe_and_unique_generations() -> None:
    svc, _, _ = service()

    results = await asyncio.gather(*(svc.mark_busy(tenant_id=2, model_id=17) for _ in range(20)))

    assert sum(result.should_schedule for result in results) == 1
    assert len({result.view.status_version for result in results}) == 20


async def test_old_success_cannot_clear_recreated_busy_generation() -> None:
    svc, _, _ = service(versions=[101, 202])
    first = await svc.mark_busy(tenant_id=2, model_id=17)
    assert await svc.clear_if_version(tenant_id=2, model_id=17, observed_version=first.view.status_version)

    recreated = await svc.mark_busy(tenant_id=2, model_id=17)

    assert (
        await svc.clear_if_version(
            tenant_id=2,
            model_id=17,
            observed_version=first.view.status_version,
        )
        is False
    )
    assert (await svc.get_state(tenant_id=2, model_id=17)).status_version == recreated.view.status_version


async def test_expired_or_deleted_key_reads_as_normal() -> None:
    svc, redis, _ = service()
    await svc.mark_busy(tenant_id=2, model_id=17)
    await redis.delete("model_rate_limit:2:17")

    view = await svc.get_state(tenant_id=2, model_id=17)

    assert view.rate_limit_state == ModelRateLimitState.NORMAL
    assert view.status_version == 0
    assert view.busy_until is None
