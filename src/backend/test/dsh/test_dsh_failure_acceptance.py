"""T113 bounded local subprocess acceptance; timings are observations, never SLA assertions."""

import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import pytest
from minio import Minio
from sqlmodel import Session, create_engine, select

from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.domain.services.projection import DshProjectionService
from bisheng.dsh.infrastructure.quota_activation import MinioQuotaApprovalStore, QuotaApproval
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from bisheng.dsh.operations_runtime import OperationsRuntime
from test.dsh.test_minio_integration import object_store as object_store
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_usage_repository import usage_db as usage_db


def _report(value, *, exit_code=0):
    print(json.dumps({"pid": os.getpid(), **value}), flush=True)
    if exit_code:
        os._exit(exit_code)


async def _child(data):
    config = json.loads(Path(os.environ["DSH_TEST_MINIO_CONFIG"]).read_text())
    client = Minio(config["endpoint"], access_key=config["access_key"], secret_key=config["secret_key"], secure=False)
    settings = DshSettings(
        installation_id="failure-acceptance",
        quota_evidence_bucket=data["bucket"],
        quota_approval_object=data.get("object"),
        quota_approval_sha256=data.get("sha256"),
    )
    runtime = OperationsRuntime(settings, client)
    runtime.quota.prefix = data["prefix"]
    engine = None
    try:
        if data["mode"] == "unapproved":
            with pytest.raises((QuotaRejected, ValueError, RuntimeError)):
                await runtime.activate()
            assert not runtime.quota.topology.ready
            _report({"denied": True})
            return
        await runtime.activate()
        quota = runtime.quota
        if data["mode"] == "disconnect":
            await quota.redis.connection_pool.disconnect()
            with pytest.raises(QuotaRejected):
                await quota.read_usage(2, 20, "2026-09")
            with pytest.raises(QuotaRejected, match="controlled_approval_required"):
                await runtime.activate()
            assert not quota.topology.ready
            _report({"physical_disconnect_denied": True, "old_approval_reuse_denied": True})
            return
        if data["mode"] in {"settle_and_exit", "settle_replay"}:
            latencies = []
            for value in data["events"]:
                event = UsageEvent.model_validate_json(json.dumps(value))
                terminal = event.model_copy(
                    update={
                        "status": "SUCCEEDED",
                        "event_version": 2,
                        "input_tokens": 3,
                        "output_tokens": 4,
                        "total_tokens": 7,
                        "usage_source": "PROVIDER",
                    }
                )
                await quota.record_usage(terminal, 1)
                committed_ns = time.perf_counter_ns()
                snapshot = await runtime.usage.read_usage(2, 20, "2026-09")
                latencies.append((time.perf_counter_ns() - committed_ns) / 1_000_000)
                assert snapshot["used"] >= 7
            _report(
                {
                    "settlement_count": len(latencies),
                    "live_visibility_ms": latencies,
                    "last_settled_monotonic_ns": committed_ns,
                    "used": snapshot["used"],
                },
                exit_code=23 if data["mode"] == "settle_and_exit" else 0,
            )
            return
        engine = create_engine(os.environ["DSH_TEST_DATABASE_URL"])

        @contextmanager
        def repository_scope():
            with Session(engine) as session, session.begin():
                yield DshUsageRepository(session)

        projection = DshProjectionService(quota, repository_scope, consumer=f"process-{os.getpid()}", claim_idle_ms=1)
        if data["mode"] == "project_and_exit_before_ack":

            async def lost_ack(*_args, **_kwargs):
                _report({"sql_commit_observed_monotonic_ns": time.perf_counter_ns(), "ack_sent": False}, exit_code=24)

            quota.redis.xack = lost_ack
        with profile_scope(2):
            count = await projection.project_batch(2, 20)
        pending = await quota.redis.xpending(f"{quota.prefix}:{{2:20}}:events", projection.group)
        _report({"projected_events": count, "pending": pending["pending"]})
    finally:
        await runtime.close()
        if engine is not None:
            engine.dispose()


async def _run_child(data, expected_exit=0):
    def execute():
        result = subprocess.run(
            [sys.executable, "-m", "test.dsh.test_dsh_failure_acceptance"],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=60,
            env=os.environ.copy(),
        )
        assert result.returncode == expected_exit, result.stderr[-5000:]
        return json.loads(result.stdout.strip().splitlines()[-1])

    return await asyncio.to_thread(execute)


async def test_cross_process_settlement_projection_replay_and_visibility(quota, usage_db, object_store):
    client, create = object_store
    bucket = create()
    # This isolated fixture's baseline is empty and independently recorded in versioned MinIO.
    await quota.redis.hset(quota.keys(running())[1], "used", "0")
    await quota.redis.hset(quota.keys(running())[2], mapping={"4": "0", "5": "0"})
    with Session(usage_db) as session, session.begin():
        policy = session.scalar(select(DshUserPolicy).where(DshUserPolicy.user_id == 20))
        policy.version, policy.model_configs = 1, [DshModelQuotaConfig(model_id=4, monthly_token_limit=1000)]
    await quota.redis.hdel(quota.keys(running())[0], "model:5", "limit:5")
    await quota.redis.hset(quota.keys(running())[0], "limit", "1000")
    body = b"[]"
    key = "dsh/reconciliation/2/controlled-empty-test-ledger.json"
    version = client.put_object(bucket, key, io.BytesIO(body), len(body)).version_id
    store = MinioQuotaApprovalStore(client, bucket=bucket, installation_id="failure-acceptance")
    approval = await store.publish(
        QuotaApproval(
            installation_id="failure-acceptance",
            run_id=quota.topology.run_id,
            epoch=1,
            recovery_evidence_object=key + "@" + version,
            recovery_evidence_sha256=hashlib.sha256(body).hexdigest(),
            isolation_attestation="dedicated-local-test-fixture-only",
            approved_by=7,
            approved_at=datetime.now(UTC),
        ),
        topology=quota.topology,
    )
    common = {"bucket": bucket, "prefix": quota.prefix, **approval}
    denied = await _run_child({**common, "mode": "unapproved", "object": None, "sha256": None})
    tampered = await _run_child({**common, "mode": "unapproved", "sha256": "0" * 64})
    disconnected = await _run_child({**common, "mode": "disconnect"})
    events = [running() for _ in range(12)]
    for item in events:
        await quota.check_and_start(item)
    payload = {**common, "events": [item.model_dump(mode="json") for item in events]}
    settlement = await _run_child({**payload, "mode": "settle_and_exit"}, expected_exit=23)
    assert settlement["used"] == 84
    replay = await _run_child({**payload, "mode": "settle_replay"})
    assert replay["used"] == 84
    assert await quota.redis.xlen(quota.keys(events[0])[5]) == 24
    committed = await _run_child({**common, "mode": "project_and_exit_before_ack"}, expected_exit=24)
    with Session(usage_db) as session:
        row = session.scalar(select(DshMonthlyUsage).where(DshMonthlyUsage.user_id == 20))
        assert row.used_tokens == 84
        sql_visible_ns = time.perf_counter_ns()
    resumed = await _run_child({**common, "mode": "project_replay"})
    assert resumed["projected_events"] == 24 and resumed["pending"] == 0
    with Session(usage_db) as session:
        assert session.scalar(select(DshMonthlyUsage).where(DshMonthlyUsage.user_id == 20)).used_tokens == 84
    pids = [item["pid"] for item in [denied, tampered, disconnected, settlement, replay, committed, resumed]]
    assert len(set(pids)) == 7 and os.getpid() not in pids
    samples = sorted(settlement["live_visibility_ms"])
    report = {
        "requests": 12,
        "settlement_replays": 12,
        "stream_events": 24,
        "projected_replayed_events": 24,
        "total_tokens": 84,
        "independent_child_processes": len(pids),
        "child_pids": pids,
        "live_visibility_ms": samples,
        "live_median_ms": median(samples),
        "live_nearest_rank_p95_ms": samples[-1],
        "live_max_ms": max(samples),
        "last_settlement_to_sql_observed_ms": (sql_visible_ns - settlement["last_settled_monotonic_ns"]) / 1_000_000,
        "sql_commit_to_parent_observed_ms": (sql_visible_ns - committed["sql_commit_observed_monotonic_ns"])
        / 1_000_000,
        "old_connection_reactivation_denied": disconnected["old_approval_reuse_denied"],
        "missing_or_tampered_approval_denied": denied["denied"] and tampered["denied"],
    }
    destination = os.environ.get("DSH_ACCEPTANCE_RESULTS")
    if destination:
        Path(destination).write_text(json.dumps(report, indent=2))
    print("DSH_FAILURE_ACCEPTANCE " + json.dumps(report))


if __name__ == "__main__":
    asyncio.run(_child(json.load(sys.stdin)))
