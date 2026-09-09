"""Complete audited inventories cross the legacy 10k boundary without unbounded Lua batches."""

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig
from bisheng.dsh.domain.services.quota_operations import DshQuotaOperationsService
from bisheng.dsh.domain.services.quota_recovery import DshQuotaRecoveryService, RecoveryManifest, RecoveryShard
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_usage_repository import usage_db as usage_db


def sharded_manifest(quota, count=10001):
    events = [
        running().model_copy(
            update={
                "request_id": f"{index:036d}",
                "status": "SUCCEEDED",
                "input_tokens": 1,
                "output_tokens": 0,
                "total_tokens": 1,
                "usage_source": "PROVIDER",
            }
        )
        for index in range(count)
    ]
    objects = {}
    shards = []
    digest = hashlib.sha256()
    for event in events:
        digest.update((event.model_dump_json() + "\n").encode())
    for offset in range(0, count, 500):
        key = f"shard-{offset // 500}@v1"
        page = events[offset : offset + 500]
        content = json.dumps([event.model_dump(mode="json") for event in page]).encode()
        objects[key] = content
        shards.append(
            RecoveryShard(
                index=len(shards), object=key, sha256=hashlib.sha256(content).hexdigest(), request_count=len(page)
            )
        )
    index = {
        "request_count": count,
        "inventory_sha256": digest.hexdigest(),
        "shards": [shard.model_dump() for shard in shards],
    }
    objects["audit@v1"] = json.dumps(index).encode()
    manifest = RecoveryManifest(
        run_id=quota.topology.run_id,
        epoch=2,
        previous_epoch=1,
        evidence_object="audit@v1",
        evidence_sha256=hashlib.sha256(objects["audit@v1"]).hexdigest(),
        old_primary_isolated=True,
        confirmed_tail_complete=True,
        tenant_id=2,
        user_id=20,
        policy_version=1,
        model_configs=[DshModelQuotaConfig(model_id=4, monthly_token_limit=20000)],
        current_month="2026-09",
        request_count=count,
        shards=shards,
        inventory_sha256=digest.hexdigest(),
    )
    return manifest, objects, events


async def test_over_ten_thousand_complete_sql_and_redis_restore(quota, usage_db):
    manifest, objects, events = sharded_manifest(quota)
    with Session(usage_db) as session, session.begin():
        policy = session.get(DshUserPolicy, 1)
        policy.version, policy.model_configs = 1, [DshModelQuotaConfig(model_id=4, monthly_token_limit=20000)]
    for offset in range(0, len(events), 500):
        with Session(usage_db) as session, session.begin():
            DshUsageRepository(session).project_batch(events[offset : offset + 500])

    @contextmanager
    def repository_scope():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)

    body = manifest.model_dump_json().encode()
    objects["manifest@v1"] = body

    class Evidence:
        async def read(self, reference, tenant_id):
            assert tenant_id == 2
            return objects[reference]

    class Approvals:
        async def publish(self, approval, *, topology):
            await topology.check()
            return {"epoch": approval.epoch}

    async def authorize(actor, user):
        return actor == 7 and user == 20

    service = DshQuotaOperationsService(
        recovery=DshQuotaRecoveryService(quota),
        repository_scope=repository_scope,
        manifest_store=Evidence(),
        evidence_store=Evidence(),
        approval_store=Approvals(),
        authorize=authorize,
        installation_id="test",
        billing_timezone="UTC",
        now=lambda: datetime.now(UTC),
    )
    assert (
        await service.recover_quota(
            command="recover",
            manifest_object="manifest@v1",
            manifest_sha256=hashlib.sha256(body).hexdigest(),
            isolation_attestation="isolated",
            actor_user_id=7,
        )
    )["epoch"] == 2
    with repository_scope() as repository:
        retained, policy = repository.recovery_snapshot(20, billing_timezone="UTC")
        assert len(retained) == 10001
        assert policy["quota_epoch"] == 2
    assert (await quota.read_usage(2, 20, "2026-09"))["used"] == 10001
    assert await quota.redis.xlen(quota.keys(running())[5]) == 10001
    assert (await quota.get_request(events[-1])).total_tokens == 1


@pytest.mark.parametrize("problem", ["missing", "hash", "duplicate", "wrong_total"])
async def test_missing_corrupt_or_duplicate_shards_refuse_recovery(quota, problem):
    manifest, objects, _ = sharded_manifest(quota, count=501)
    second = manifest.shards[1]
    if problem == "missing":
        del objects[second.object]
    elif problem == "hash":
        objects[second.object] += b" "
    elif problem == "wrong_total":
        manifest = manifest.model_copy(update={"inventory_sha256": "a" * 64})
    else:
        values = json.loads(objects[second.object])
        values[0] = json.loads(objects[manifest.shards[0].object])[0]
        objects[second.object] = json.dumps(values).encode()
        changed = second.model_copy(update={"sha256": hashlib.sha256(objects[second.object]).hexdigest()})
        manifest = manifest.model_copy(update={"shards": [manifest.shards[0], changed]})
    if problem in {"duplicate", "wrong_total"}:
        objects[manifest.evidence_object] = json.dumps(
            {
                "request_count": manifest.request_count,
                "inventory_sha256": manifest.inventory_sha256,
                "shards": [shard.model_dump() for shard in manifest.shards],
            }
        ).encode()
        manifest = manifest.model_copy(
            update={"evidence_sha256": hashlib.sha256(objects[manifest.evidence_object]).hexdigest()}
        )

    async def read(reference):
        return objects[reference]

    with pytest.raises((ValueError, KeyError)):
        await DshQuotaRecoveryService(quota).recover(manifest, read_evidence=read, sql_events=[])
    assert not quota.topology.ready
    assert await quota.redis.hget(quota.keys(running())[1], "used") == "900"


@pytest.mark.parametrize("lost_phase", ["events", "finish"])
async def test_partial_or_completed_write_response_loss_can_resume_same_audit(quota, monkeypatch, lost_phase):
    manifest, objects, _ = sharded_manifest(quota, count=501)
    evaluate = quota.redis.eval
    lost = False

    async def lose_response(script, number_of_keys, *args):
        nonlocal lost
        result = await evaluate(script, number_of_keys, *args)
        if "recovery_owner" in script and args[number_of_keys] == lost_phase and not lost:
            lost = True
            raise TimeoutError("Recovery write response lost after Redis applied it")
        return result

    async def read(reference):
        return objects[reference]

    monkeypatch.setattr(quota.redis, "eval", lose_response)
    service = DshQuotaRecoveryService(quota)
    with pytest.raises(TimeoutError):
        await service.recover(manifest, read_evidence=read, sql_events=[])
    assert not quota.topology.ready
    assert lost
    if lost_phase == "events":
        assert await quota.redis.hget(quota.keys(running())[0], "state") == "FROZEN"
    await service.recover(manifest, read_evidence=read, sql_events=[])
    assert (await quota.read_usage(2, 20, "2026-09"))["used"] == 501
    assert quota.topology.ready


async def test_omitted_shard_index_is_not_a_complete_manifest(quota):
    manifest, _, _ = sharded_manifest(quota, count=501)
    data = manifest.model_dump(mode="json")
    data["shards"][1]["index"] = 2
    with pytest.raises(ValueError, match="complete ordered audit index"):
        RecoveryManifest.model_validate_json(json.dumps(data))
