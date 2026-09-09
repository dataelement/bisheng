"""Audited UNKNOWN settlement; proof and current authority precede ledger mutation."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from pydantic import Field, model_validator

from bisheng.common.errcode.dsh import DshOperationConflictError, DshOperationInProgressError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.repositories.reconciliation import DshReconciliationRepository
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.services.usage import DshUsageService
from bisheng.dsh.infrastructure.evidence_store import EvidenceStore


class ReconciliationInput(DshTokenUsage):
    request_id: str = Field(min_length=1, max_length=36)
    operation_id: str = Field(min_length=1, max_length=36)
    expected_event_version: int = Field(gt=0)
    evidence_object: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def reliable(self):
        if self.total_tokens is None:
            raise ValueError("Reconciliation requires reliable measured usage")
        return self


class UsageEvidence(DshTokenUsage):
    request_id: str
    provider_request_id: str | None
    model_id: int = Field(gt=0)
    started_at: datetime


class DshReconciliationService:
    def __init__(
        self,
        *,
        repository_scope: Callable[[], AbstractContextManager[DshReconciliationRepository]],
        usage: DshUsageService,
        evidence: EvidenceStore,
        authorize: Callable[[int, int], Awaitable[bool]],
        now: Callable[[], datetime],
    ):
        self.repository_scope, self.usage, self.evidence, self.authorize, self.now = (
            repository_scope,
            usage,
            evidence,
            authorize,
            now,
        )

    def _read(self, operation_id: str):
        with self.repository_scope() as repository:
            operation = repository.operations.get(operation_id)
            if operation is None or operation.action != "RECONCILE_USAGE":
                raise DshOperationConflictError()
            return operation.model_dump()

    async def status(self, operation_id: str, *, actor_user_id: int):
        operation = self._read(operation_id)
        if not await self.authorize(actor_user_id, operation["user_id"]):
            raise DshOperationConflictError()
        return operation

    async def _verify(self, request: ReconciliationInput, row):
        data = await self.evidence.read(request.evidence_object, get_current_tenant_id())
        if hashlib.sha256(data).hexdigest() != request.evidence_sha256:
            raise ValueError("Evidence digest mismatch")
        record = UsageEvidence.model_validate_json(data)
        recorded_at = record.started_at
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        stored_at = row.started_at
        if stored_at is not None and stored_at.tzinfo is None:
            stored_at = stored_at.replace(tzinfo=UTC)
        if (
            record.request_id != row.request_id
            or record.provider_request_id != row.provider_request_id
            or record.model_id != row.model_id
            or recorded_at.astimezone(UTC) != stored_at
        ):
            raise ValueError("Evidence does not identify the original provider request")
        if any(
            getattr(record, key) != getattr(request, key) for key in ["input_tokens", "output_tokens", "total_tokens"]
        ):
            raise ValueError("Evidence usage differs from the submitted measurement")

    async def submit(self, request: ReconciliationInput, *, actor_user_id: int):
        request = ReconciliationInput.model_validate(request.model_dump())
        with self.repository_scope() as repository:
            row = repository.get_request(request.request_id)
            if row is None:
                raise DshOperationInProgressError()
            target = row.user_id
            row = row.model_copy(deep=True)
        if not await self.authorize(actor_user_id, target):
            raise DshOperationConflictError()
        await self._verify(request, row)
        with self.repository_scope() as repository:
            operation = repository.register(request, actor_user_id=actor_user_id)
            result = operation.model_dump()
        if result["status"] in {"SUCCEEDED", "FAILED"}:
            return result
        return await self.resume(request.operation_id)

    async def resume(self, operation_id: str):
        operation = self._read(operation_id)
        if operation["status"] in {"SUCCEEDED", "FAILED"}:
            return operation
        try:
            with self.repository_scope() as repository:
                operation = repository.operations.claim(operation_id, now=self.now()).model_dump()
        except DshOperationInProgressError:
            return self._read(operation_id)
        generation = operation["lease_generation"]
        request = ReconciliationInput.model_validate(operation["payload"])
        with self.repository_scope() as repository:
            row = repository.get_request(request.request_id).model_copy(deep=True)
            if repository.complete_if_projected(operation_id, generation, now=self.now()):
                return repository.operations.get(operation_id).model_dump()
        # Redis provides original admitted ownership and billing month. SQL is not a balance fallback.
        from bisheng.dsh.domain.schemas.usage import UsageEvent

        probe = UsageEvent.model_validate_json(
            json.dumps(
                {
                    **{key: value for key, value in row.model_dump().items() if key in UsageEvent.model_fields},
                    "billing_timezone": "UTC",
                }
            )
        )
        current = await self.usage.get_request(probe)
        if current is None:
            raise DshOperationInProgressError()
        await self.usage.claim_reconciliation(
            current, operation_id=operation_id, payload_hash=operation["payload_hash"], generation=generation
        )
        if not await self.authorize(operation["actor_user_id"], operation["user_id"]):
            with self.repository_scope() as repository:
                return repository.operations.retry(
                    operation_id,
                    generation,
                    code="permission_revoked",
                    now=self.now(),
                    retry_at=self.now() + timedelta(minutes=5),
                ).model_dump()
        await self._verify(request, row)
        if current.status == "USAGE_UNKNOWN":
            if current.event_version != request.expected_event_version:
                raise DshOperationConflictError()
            settled = current.model_copy(
                update={
                    "event_version": current.event_version + 1,
                    "status": "CANCELLED" if current.error_code == "cancelled" else "FAILED",
                    "error_code": current.error_code or "interrupted_unknown",
                    "usage_source": "RECONCILED",
                    "input_tokens": request.input_tokens,
                    "output_tokens": request.output_tokens,
                    "total_tokens": request.total_tokens,
                    "operation_id": operation_id,
                    "operation_generation": generation,
                    "payload_hash": operation["payload_hash"],
                    "settled_at": self.now(),
                }
            )
            await self.usage.reconcile_unknown(settled, current.event_version)
        elif current.operation_id != operation_id or current.payload_hash != operation["payload_hash"]:
            raise DshOperationConflictError()
        with self.repository_scope() as repository:
            repository.operations.set_phase(operation_id, generation, "WAITING_PROJECTION", now=self.now())
            repository.operations.retry(
                operation_id,
                generation,
                code="projection_pending",
                now=self.now(),
                retry_at=self.now() + timedelta(seconds=5),
            )
        return self._read(operation_id)
