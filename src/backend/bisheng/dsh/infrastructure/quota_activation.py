"""Shared immutable topology approval records; per-process pinning never invents proof."""

import asyncio
import hashlib
import io
from datetime import datetime
from uuid import uuid4

from pydantic import Field

from bisheng.dsh.domain.schemas.contracts import DshContract
from bisheng.dsh.infrastructure.quota_topology import QuotaTopology


class QuotaApproval(DshContract):
    run_id: str = Field(min_length=1, max_length=64)
    epoch: int = Field(gt=0)
    evicted_keys: int = Field(default=0, ge=0)
    recovery_evidence_object: str = Field(min_length=1, max_length=1024)
    recovery_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    isolation_attestation: str = Field(min_length=1, max_length=1024)
    approved_by: int = Field(gt=0)
    approved_at: datetime


class MinioQuotaApprovalStore:
    """Use read-only credentials in API/workers; only the controlled recovery role may publish."""

    def __init__(self, client, *, bucket: str):
        if not bucket:
            raise ValueError("Approval store requires a versioned bucket")
        self.client, self.bucket = client, bucket
        self.prefix = "dsh/quota-approvals/"

    async def read(self, reference: str, *, sha256: str) -> QuotaApproval:
        content = await asyncio.to_thread(self._read, reference)
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ValueError("Topology approval digest mismatch")
        approval = QuotaApproval.model_validate_json(content)
        return approval

    def _read(self, reference: str) -> bytes:
        key, separator, version = reference.rpartition("@")
        if (
            not separator
            or not version
            or version == "null"
            or not key.startswith(self.prefix)
            or ".." in key.split("/")
            or "://" in reference
        ):
            raise ValueError("Approval must name an immutable DSH object version")
        stat = self.client.stat_object(self.bucket, key, version_id=version)
        if stat.version_id != version or stat.size > 16384:
            raise ValueError("Approval object is not an immutable bounded version")
        response = self.client.get_object(self.bucket, key, version_id=version)
        try:
            data = response.read(16385)
            if len(data) > 16384:
                raise ValueError("Approval object too large")
            return data
        finally:
            response.close()
            response.release_conn()

    async def publish(self, approval: QuotaApproval, *, topology: QuotaTopology) -> dict[str, str]:
        # Publication follows a successful recovery and an explicit administrator decision.
        await topology.check()
        if (approval.run_id, approval.epoch) != (
            topology.run_id,
            topology.epoch,
        ):
            raise ValueError("Only the verified recovered topology can be published")
        content = approval.model_dump_json().encode()
        key = f"{self.prefix}{approval.epoch}/{uuid4()}.json"
        result = await asyncio.to_thread(
            self.client.put_object, self.bucket, key, io.BytesIO(content), len(content), content_type="application/json"
        )
        if not result.version_id or result.version_id == "null":
            raise ValueError("Approval bucket versioning is required; activation was not published")
        return {"object": key + "@" + result.version_id, "sha256": hashlib.sha256(content).hexdigest()}


async def activate_from_approval(
    topology: QuotaTopology, store: MinioQuotaApprovalStore, *, reference: str, sha256: str
):
    """Every API/worker startup reads the same operator-selected immutable approval record.

    A restarted Redis has a new run_id and cannot be activated by an old record.
    No process may auto-approve a reconnect or change its configured approval version.
    Per-user READY, epoch, UNKNOWN and partial-write gates still apply in every Lua call.
    """
    topology.close()
    approval = await store.read(reference, sha256=sha256)
    await topology.approve(
        approval.run_id,
        approval.epoch,
        old_primary_isolated=True,
        ledger_proven=True,
        evicted_keys=approval.evicted_keys,
    )
    return approval
