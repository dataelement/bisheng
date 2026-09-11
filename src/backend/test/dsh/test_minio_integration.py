"""F062 real MinIO versioned evidence and operator approval adapter checks.

Requires an explicitly isolated MinIO credential file and Redis test database.
This validates storage adapters and activation, not production fencing or TLS.
"""

import hashlib
import io
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from minio import Minio
from minio.deleteobjects import DeleteObject
from minio.versioningconfig import ENABLED, VersioningConfig

from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.domain.services.reconciliation import DshReconciliationService, ReconciliationInput
from bisheng.dsh.infrastructure.evidence_store import MinioEvidenceStore
from bisheng.dsh.infrastructure.quota_activation import (
    MinioQuotaApprovalStore,
    QuotaApproval,
    activate_from_approval,
)
from bisheng.dsh.infrastructure.quota_topology import QuotaTopology, create_quota_redis


@pytest.fixture
def object_store():
    location = os.environ.get("DSH_TEST_MINIO_CONFIG")
    if os.environ.get("DSH_TEST_MINIO_ISOLATED") != "1" or not location:
        pytest.skip("Dedicated real MinIO is not configured")
    path = Path(location)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("Test credentials must have mode 0600")
    config = json.loads(path.read_text())
    if not config["endpoint"].startswith("127.0.0.1:") or config.get("secure") is not False:
        raise ValueError("Integration fixture accepts only the isolated loopback test server")
    client = Minio(config["endpoint"], access_key=config["access_key"], secret_key=config["secret_key"], secure=False)
    buckets = []

    def create(versioned=True):
        bucket = "dsh-f062-test-" + uuid4().hex
        client.make_bucket(bucket)
        buckets.append(bucket)
        if versioned:
            client.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
            assert client.get_bucket_versioning(bucket).status == ENABLED
        return bucket

    yield client, create
    for bucket in buckets:
        objects = client.list_objects(bucket, recursive=True, include_version=True)
        failures = list(
            client.remove_objects(bucket, (DeleteObject(row.object_name, version_id=row.version_id) for row in objects))
        )
        assert failures == []
        client.remove_bucket(bucket)


@pytest.fixture
async def approved_topology():
    url = os.environ.get("DSH_TEST_REDIS_URL", "")
    if os.environ.get("DSH_TEST_REDIS_ISOLATED") != "1" or not url.endswith("/11"):
        pytest.skip("Dedicated Redis DB11 is required for this storage integration")
    redis = create_quota_redis(url)
    topology = QuotaTopology(redis)
    info = await redis.info("server")
    # This fixture attests only its isolated test instance, never a production primary.
    await topology.approve(info["run_id"], 1, old_primary_isolated=True, ledger_proven=True)
    yield topology
    topology.close()
    await redis.aclose()


def put(client, bucket, key, content):
    result = client.put_object(bucket, key, io.BytesIO(content), len(content), content_type="application/json")
    return key + "@" + (result.version_id or "null")


def approval_for(topology):
    return QuotaApproval(
        run_id=topology.run_id,
        epoch=1,
        recovery_evidence_object="dsh/reconciliation/2/recovery.json@fixture",
        recovery_evidence_sha256="a" * 64,
        isolation_attestation="isolated-local-test-only",
        approved_by=7,
        approved_at=datetime.now(UTC),
    )


async def test_real_version_pins_evidence_and_rejects_cross_tenant_or_unbounded_reads(object_store):
    client, create = object_store
    bucket = create()
    store = MinioEvidenceStore(client, bucket=bucket, max_bytes=64)
    original = b'{"measurement":12}'
    reference = put(client, bucket, "dsh/reconciliation/2/evidence.json", original)
    replacement = put(client, bucket, "dsh/reconciliation/2/evidence.json", b'{"measurement":900}')
    assert replacement != reference and not reference.endswith("@null")
    assert await store.read(reference, 2) == original
    assert await store.read(replacement, 2) == b'{"measurement":900}'
    for candidate, tenant in [
        (reference, 3),
        (reference.split("@")[0], 2),
        (reference.split("@")[0] + "@null", 2),
        ("https://elsewhere/object@v1", 2),
        ("dsh/reconciliation/2/../3/object@v1", 2),
    ]:
        with pytest.raises(ValueError):
            await store.read(candidate, tenant)
    oversized = put(client, bucket, "dsh/reconciliation/2/large.json", b"x" * 65)
    with pytest.raises(ValueError, match="size"):
        await store.read(oversized, 2)


async def test_real_evidence_digest_and_original_request_binding(object_store):
    client, create = object_store
    bucket = create()
    content = json.dumps(
        {
            "request_id": "request-1",
            "provider_request_id": "provider-1",
            "model_id": 4,
            "started_at": "2026-09-09T00:00:00Z",
            "input_tokens": 4,
            "output_tokens": 3,
            "total_tokens": 7,
        }
    ).encode()
    reference = put(client, bucket, "dsh/reconciliation/2/request.json", content)
    request = ReconciliationInput(
        operation_id=str(uuid4()),
        request_id="request-1",
        expected_event_version=2,
        evidence_object=reference,
        evidence_sha256=hashlib.sha256(content).hexdigest(),
        reason="measured export",
        input_tokens=4,
        output_tokens=3,
        total_tokens=7,
    )
    service = DshReconciliationService(
        repository_scope=None, usage=None, evidence=MinioEvidenceStore(client, bucket=bucket), authorize=None, now=None
    )
    row = SimpleNamespace(
        request_id="request-1", provider_request_id="provider-1", model_id=4, started_at=datetime(2026, 9, 9)
    )
    with profile_scope(2):
        await service._verify(request, row)
        with pytest.raises(ValueError, match="digest"):
            await service._verify(request.model_copy(update={"evidence_sha256": "0" * 64}), row)
        with pytest.raises(ValueError, match="original provider"):
            await service._verify(request, SimpleNamespace(**{**vars(row), "provider_request_id": "other"}))


async def test_real_approval_publish_pins_version_and_activates_only_matching_primary(object_store, approved_topology):
    client, create = object_store
    bucket = create()
    store = MinioQuotaApprovalStore(client, bucket=bucket)
    approval = approval_for(approved_topology)
    published = await store.publish(approval, topology=approved_topology)
    key, version = published["object"].rsplit("@", 1)
    assert version != "null"
    replacement = approval.model_copy(update={"approved_by": 99})
    put(client, bucket, key, replacement.model_dump_json().encode())
    assert (await store.read(published["object"], sha256=published["sha256"])).approved_by == 7
    approved_topology.close()
    activated = await activate_from_approval(
        approved_topology, store, reference=published["object"], sha256=published["sha256"]
    )
    assert activated == approval and approved_topology.ready
    await approved_topology.check()
    with pytest.raises(ValueError, match="digest"):
        await activate_from_approval(approved_topology, store, reference=published["object"], sha256="0" * 64)
    assert not approved_topology.ready
    with pytest.raises(ValueError, match="immutable DSH"):
        await store.read(
            published["object"].replace("dsh/quota-approvals/", "unrelated/"),
            sha256=published["sha256"],
        )


async def test_real_approval_rejects_unversioned_publish_and_stale_primary(object_store, approved_topology):
    client, create = object_store
    plain = MinioQuotaApprovalStore(client, bucket=create(False))
    approval = approval_for(approved_topology)
    with pytest.raises(ValueError, match="versioning"):
        await plain.publish(approval, topology=approved_topology)
    versioned_bucket = create()
    store = MinioQuotaApprovalStore(client, bucket=versioned_bucket)
    stale = approval.model_copy(update={"run_id": "not-the-current-primary"})
    with pytest.raises(ValueError, match="verified recovered"):
        await store.publish(stale, topology=approved_topology)
    content = stale.model_dump_json().encode()
    reference = put(client, versioned_bucket, "dsh/quota-approvals/1/stale.json", content)
    with pytest.raises(RuntimeError, match="Unapproved primary"):
        await activate_from_approval(
            approved_topology, store, reference=reference, sha256=hashlib.sha256(content).hexdigest()
        )
    assert not approved_topology.ready
