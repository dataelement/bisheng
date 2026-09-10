"""Owned Redis restart/promotion: real AOF, replica, MySQL, and immutable MinIO approval.

Process termination fences the owned localhost primary; this is not production network fencing.
"""

import asyncio
import hashlib
import json
import os
import socket
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlmodel import Session, select

from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig
from bisheng.dsh.domain.services.projection import DshProjectionService
from bisheng.dsh.domain.services.quota_operations import DshQuotaOperationsService
from bisheng.dsh.domain.services.quota_recovery import DshQuotaRecoveryService, RecoveryManifest
from bisheng.dsh.infrastructure.evidence_store import MinioEvidenceStore
from bisheng.dsh.infrastructure.quota_activation import MinioQuotaApprovalStore, activate_from_approval
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis, QuotaRejected
from bisheng.dsh.infrastructure.quota_topology import QuotaTopology, create_quota_redis
from test.dsh.test_minio_integration import object_store as object_store
from test.dsh.test_minio_integration import put
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal
from test.dsh.test_usage_repository import usage_db as usage_db


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def owned_redis(tmp_path):
    binary = os.environ.get("DSH_TEST_REDIS_SERVER")
    if not binary:
        pytest.skip("An explicitly provided Redis binary is required for owned process failure tests")
    processes, clients = [], []

    async def start(port=None, directory=None, primary_port=None):
        port = port or free_port()
        directory = directory or tmp_path / str(port)
        directory.mkdir(exist_ok=True)
        args = [
            binary,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--dir",
            str(directory),
            "--appendonly",
            "yes",
            "--appendfsync",
            "always",
            "--maxmemory-policy",
            "noeviction",
            "--save",
            "",
            "--logfile",
            str(directory / "redis.log"),
        ]
        if primary_port:
            args += ["--replicaof", "127.0.0.1", str(primary_port)]
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(process)
        client = Redis.from_url(f"redis://127.0.0.1:{port}/0", decode_responses=True)
        clients.append(client)
        for _ in range(100):
            try:
                if await client.ping():
                    return process, client, port, directory
            except Exception:
                if process.poll() is not None:
                    raise RuntimeError("Owned Redis failed to start") from None
            await asyncio.sleep(0.05)
        raise RuntimeError("Owned Redis startup timed out")

    yield start
    for process in processes:
        if process.poll() is None:
            process.terminate()
            await asyncio.to_thread(process.wait, timeout=10)
    for client in clients:
        await client.aclose()


@pytest.mark.parametrize("mode", ["restart", "promotion"])
async def test_actual_primary_change_rejects_old_approval_until_evidence_recovery(
    mode, owned_redis, usage_db, object_store
):
    client, create = object_store
    bucket = create()
    process, control, port, directory = await owned_redis()
    stores = []

    def store(endpoint):
        redis = create_quota_redis(f"redis://127.0.0.1:{endpoint}/0")
        quota = QuotaRedis(redis, QuotaTopology(redis))
        stores.append(quota)
        return quota

    @contextmanager
    def repository():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)

    with Session(usage_db) as session, session.begin():
        policy = session.scalar(select(DshUserPolicy).where(DshUserPolicy.user_id == 20))
        policy.version, policy.monthly_token_limit = 1, 1000
    evidence = MinioEvidenceStore(client, bucket=bucket)
    approvals = MinioQuotaApprovalStore(client, bucket=bucket, installation_id="primary-failure-test")

    async def authorize(*_):
        return True

    async def recover(quota, run_id, previous_epoch, events):
        body = json.dumps([event.model_dump(mode="json") for event in events]).encode()
        reference = put(client, bucket, f"dsh/reconciliation/2/evidence-{previous_epoch}.json", body)
        manifest = RecoveryManifest(
            run_id=run_id,
            previous_epoch=previous_epoch,
            epoch=previous_epoch + 1,
            evidence_object=reference,
            evidence_sha256=hashlib.sha256(body).hexdigest(),
            old_primary_isolated=True,
            confirmed_tail_complete=True,
            tenant_id=2,
            user_id=20,
            policy_version=1,
            model_configs=[DshModelQuotaConfig(model_id=4, monthly_token_limit=1000)],
            model_versions={4: 1},
            current_month="2026-09",
            request_count=len(events),
            events=events,
        )
        body = manifest.model_dump_json().encode()
        reference = put(client, bucket, f"dsh/reconciliation/2/manifest-{previous_epoch}.json", body)
        service = DshQuotaOperationsService(
            recovery=DshQuotaRecoveryService(quota),
            repository_scope=repository,
            manifest_store=evidence,
            evidence_store=evidence,
            approval_store=approvals,
            authorize=authorize,
            installation_id="primary-failure-test",
            billing_timezone="Asia/Shanghai",
            now=lambda: datetime.now(UTC),
        )
        return await service.recover_quota(
            command="recover",
            manifest_object=reference,
            manifest_sha256=hashlib.sha256(body).hexdigest(),
            actor_user_id=7,
            isolation_attestation="Owned primary PID stopped; no production network fencing claim",
        )

    try:
        original = store(port)
        old_run = (await control.info("server"))["run_id"]
        old_approval = await recover(original, old_run, 0, [])
        event = running()
        await original.check_and_start(event)
        settled = terminal(event)
        await original.record_usage(settled, 1)
        assert await DshProjectionService(original, repository, consumer="before").project_batch(2, 20) == 2
        if mode == "promotion":
            _, replica, destination_port, _ = await owned_redis(primary_port=port)
            for _ in range(200):
                if (await replica.info("replication"))["master_link_status"] == "up":
                    break
                await asyncio.sleep(0.05)
            await control.set("owned-test-replication-barrier", "1")
            assert await control.wait(1, 5000) == 1
        process.terminate()
        await asyncio.to_thread(process.wait, timeout=10)
        assert process.poll() == 0
        if mode == "restart":
            _, destination, destination_port, _ = await owned_redis(port=port, directory=directory)
        else:
            await replica.execute_command("REPLICAOF", "NO", "ONE")
            destination = replica
        assert (await destination.info("replication"))["role"] == "master"
        new_run = (await destination.info("server"))["run_id"]
        assert new_run != old_run
        # AOF/replication retained READY, proving the denial is independent of the copied flag.
        assert await destination.hget(original.keys(event)[0], "state") == "READY"
        with pytest.raises(QuotaRejected):
            await original.check_and_start(running())
        assert not original.topology.ready
        fresh = store(destination_port)
        with pytest.raises(RuntimeError, match="Unapproved primary"):
            await activate_from_approval(
                fresh.topology, approvals, reference=old_approval["object"], sha256=old_approval["sha256"]
            )
        new_approval = await recover(fresh, new_run, 1, [settled])
        restored = store(destination_port)
        await activate_from_approval(
            restored.topology, approvals, reference=new_approval["object"], sha256=new_approval["sha256"]
        )
        assert await DshProjectionService(restored, repository, consumer="after").project_batch(2, 20) == 1
        assert (await restored.read_usage(2, 20, "2026-09"))["used"] == 300
        admitted = await restored.check_and_start(running().model_copy(update={"quota_epoch": 2}))
        assert admitted.quota_epoch == 2
        with repository() as repo:
            assert repo.recovery_snapshot(20, billing_timezone="Asia/Shanghai")[1]["quota_epoch"] == 2
    finally:
        for quota in stores:
            await quota.redis.aclose()
