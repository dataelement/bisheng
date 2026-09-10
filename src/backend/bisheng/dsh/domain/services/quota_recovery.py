"""Controlled recovery from an immutable, externally audited complete request manifest."""

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC
from typing import Literal

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig, validate_model_configs
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis


class RecoveryShard(DshContract):
    index: int = Field(ge=0)
    object: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_count: int = Field(gt=0, le=500)


class RecoveryManifest(DshContract):
    run_id: str = Field(min_length=1)
    epoch: int = Field(gt=0)
    previous_epoch: int = Field(ge=0)
    evidence_object: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    old_primary_isolated: Literal[True]
    confirmed_tail_complete: Literal[True]
    tenant_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    policy_version: int = Field(ge=0)
    model_configs: list[DshModelQuotaConfig]
    model_versions: dict[int, int] = Field(default_factory=dict)
    current_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    # This manifest must cover all retained months, including unsettled requests.
    request_count: int = Field(ge=0)
    events: list[UsageEvent] = Field(default_factory=list, max_length=10000)
    shards: list[RecoveryShard] = Field(default_factory=list)
    inventory_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @property
    def model_ids(self) -> list[int]:
        return [item.model_id for item in self.model_configs]

    @property
    def monthly_limit(self) -> int:
        return sum(item.monthly_token_limit for item in self.model_configs)

    @model_validator(mode="after")
    def check_manifest(self):
        if self.epoch <= self.previous_epoch:
            raise ValueError("Recovery requires a new epoch")
        if self.shards:
            if (
                self.events
                or self.inventory_sha256 is None
                or [s.index for s in self.shards] != list(range(len(self.shards)))
            ):
                raise ValueError("Sharded recovery requires a complete ordered audit index")
            if sum(s.request_count for s in self.shards) != self.request_count or len(
                {s.object for s in self.shards}
            ) != len(self.shards):
                raise ValueError("Shard references and counts must cover the entire inventory")
        elif len(self.events) != self.request_count or self.inventory_sha256 is not None:
            raise ValueError("Legacy recovery requires a complete bounded event array")
        if len({e.request_id for e in self.events}) != len(self.events) or any(
            e.tenant_id != self.tenant_id or e.user_id != self.user_id for e in self.events
        ):
            raise ValueError("Recovery events must uniquely belong to the approved user")
        self.model_configs = validate_model_configs(self.model_configs)
        if any(k <= 0 or v < 0 for k, v in self.model_versions.items()):
            raise ValueError("Invalid model policy version")
        if self.model_versions and (
            sum(self.model_versions.values()) != self.policy_version
            or not set(self.model_ids) <= self.model_versions.keys()
        ):
            raise ValueError("Recovery model versions must cover every policy row")
        return self


class DshQuotaRecoveryService:
    def __init__(self, quota: QuotaRedis):
        self.quota = quota

    async def recover(
        self,
        manifest: RecoveryManifest,
        *,
        read_evidence: Callable[[str], Awaitable[bytes]],
        sql_events: list[UsageEvent],
    ):
        """Evidence is an immutable MinIO version containing the independently audited event array.

        The caller must authorize operations access and verify the fencing attestation.
        SQL and the surviving Stream must be subsets of this externally proven inventory.
        Neither SQL alone nor an automatically copied READY flag is a recovery proof.
        """
        self.quota.topology.close()
        evidence = await read_evidence(manifest.evidence_object)
        if hashlib.sha256(evidence).hexdigest() != manifest.evidence_sha256:
            raise ValueError("Recovery evidence digest mismatch")
        import json

        if manifest.shards:
            expected_index = {
                "request_count": manifest.request_count,
                "inventory_sha256": manifest.inventory_sha256,
                "shards": [shard.model_dump() for shard in manifest.shards],
            }
            if json.loads(evidence) != expected_index:
                raise ValueError("Manifest does not match the immutable audit index")
            inventory = {}
            digest = hashlib.sha256()
            previous_id = ""
            for shard in manifest.shards:
                content = await read_evidence(shard.object)
                if len(content) > 4 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != shard.sha256:
                    raise ValueError("Recovery shard size or digest mismatch")
                values = json.loads(content)
                if not isinstance(values, list) or len(values) != shard.request_count:
                    raise ValueError("Recovery shard count mismatch")
                for value in values:
                    item = UsageEvent.model_validate_json(json.dumps(value))
                    if item.request_id <= previous_id or (item.tenant_id, item.user_id) != (
                        manifest.tenant_id,
                        manifest.user_id,
                    ):
                        raise ValueError("Recovery shards contain duplicate, unordered or foreign requests")
                    previous_id = item.request_id
                    inventory[item.request_id] = item
                    digest.update((item.model_dump_json() + "\n").encode())
            if len(inventory) != manifest.request_count or digest.hexdigest() != manifest.inventory_sha256:
                raise ValueError("Recovery inventory is incomplete or has an incorrect complete digest")
        else:
            audited = [UsageEvent.model_validate_json(json.dumps(value)) for value in json.loads(evidence)]
            if audited != manifest.events:
                raise ValueError("Manifest does not match the independently retained evidence")
            inventory = {e.request_id: e for e in manifest.events}
        covered_inventory = inventory
        if manifest.shards:
            from bisheng.dsh.infrastructure.quota_restore import recovered_inventory

            covered_inventory = recovered_inventory(inventory)
        for event in sql_events:
            self._covered(event, covered_inventory)
        return await self.quota.restore_manifest(manifest, inventory, self._covered)

    @staticmethod
    def _covered(event: UsageEvent, inventory: dict[str, UsageEvent]):
        verified = inventory.get(event.request_id)
        if (
            verified is None
            or event.event_version > verified.event_version
            or QuotaRedis._identity(event) != QuotaRedis._identity(verified)
        ):
            raise ValueError("Recovery inventory omits or contradicts a surviving event")
        if event.event_version == verified.event_version:
            left, right = event.model_dump(), verified.model_dump()
            for key in ["started_at", "ended_at", "settled_at"]:
                for values in [left, right]:
                    value = values[key]
                    if value is not None:
                        if value.tzinfo is None:
                            value = value.replace(tzinfo=UTC)
                        values[key] = value.astimezone(UTC)
            # SQL does not retain transport lease generations; durable business state still must match.
            for key in ["operation_generation", "payload_hash"]:
                if left[key] is None:
                    left.pop(key)
                    right.pop(key)
            if left != right:
                raise ValueError("Same-version recovery payload conflict")
        if event.total_tokens is not None and (event.total_tokens, event.input_tokens, event.output_tokens) != (
            verified.total_tokens,
            verified.input_tokens,
            verified.output_tokens,
        ):
            raise ValueError("Recovery may not overwrite a reliable settlement")
