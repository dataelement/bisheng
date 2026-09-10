"""Authorized recovery command assembly with shared SQL/MinIO evidence and approval publication."""

import hashlib
from zoneinfo import ZoneInfo

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.schemas.model_policy import model_configs_payload
from bisheng.dsh.domain.services.quota_recovery import RecoveryManifest
from bisheng.dsh.infrastructure.quota_activation import QuotaApproval


class DshQuotaOperationsService:
    def __init__(
        self,
        *,
        recovery,
        repository_scope,
        manifest_store,
        evidence_store,
        approval_store,
        authorize,
        installation_id: str,
        billing_timezone: str,
        now,
    ):
        self.recovery, self.repository_scope, self.manifest_store, self.evidence_store = (
            recovery,
            repository_scope,
            manifest_store,
            evidence_store,
        )
        self.approval_store, self.authorize = approval_store, authorize
        self.installation_id, self.billing_timezone, self.now = installation_id, billing_timezone, now

    async def recover_quota(
        self,
        *,
        command: str,
        manifest_object: str,
        manifest_sha256: str,
        isolation_attestation: str,
        actor_user_id: int,
    ):
        tenant = get_current_tenant_id()
        if tenant is None or command not in {"initialize", "recover"}:
            raise ValueError("Scoped recovery command required")
        content = await self.manifest_store.read(manifest_object, tenant)
        if hashlib.sha256(content).hexdigest() != manifest_sha256:
            raise ValueError("Manifest digest mismatch")
        manifest = RecoveryManifest.model_validate_json(content)
        if manifest.tenant_id != tenant or not await self.authorize(actor_user_id, manifest.user_id):
            raise PermissionError("Recovery requires current super administrator scope")
        with self.repository_scope() as repository:
            events, policy = repository.recovery_snapshot(manifest.user_id, billing_timezone=self.billing_timezone)
        if (manifest.policy_version, model_configs_payload(manifest.model_configs)) != (
            policy["version"],
            model_configs_payload(policy["model_configs"]),
        ):
            raise ValueError("Recovery policy must match the current committed SQL policy")
        if manifest.model_versions != {row["model_id"]: row["version"] for row in policy["rows"]}:
            raise ValueError("Recovery must include the committed version of every model row")
        if command == "initialize":
            current_month = self.now().astimezone(ZoneInfo(self.billing_timezone)).strftime("%Y-%m")
            if (
                events
                or manifest.request_count
                or manifest.previous_epoch != 0
                or manifest.current_month != current_month
            ):
                raise ValueError("Initialization requires a proven empty current-month history")

        async def read(reference):
            return await self.evidence_store.read(reference, tenant)

        receipt = await self.recovery.recover(manifest, read_evidence=read, sql_events=events)
        try:
            with self.repository_scope() as repository:
                repository.complete_recovery(manifest.user_id, expected_policy=policy, epoch=manifest.epoch)
        except Exception:
            # Redis is still FROZEN; never overwrite a newer owner's gate on a failed SQL CAS.
            self.recovery.quota.topology.close()
            raise
        await self.recovery.quota.finish_recovery(manifest, receipt)
        approval = QuotaApproval(
            installation_id=self.installation_id,
            run_id=manifest.run_id,
            epoch=manifest.epoch,
            recovery_evidence_object=manifest_object,
            recovery_evidence_sha256=manifest_sha256,
            isolation_attestation=isolation_attestation,
            approved_by=actor_user_id,
            approved_at=self.now(),
        )
        return await self.approval_store.publish(approval, topology=self.recovery.quota.topology)
