"""Recoverable policy orchestration; every SQL scope is a short transaction."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Protocol

from fastapi import HTTPException
from loguru import logger

from bisheng.common.errcode.dsh import DshModelNotAllowedError, DshOperationConflictError, DshOperationInProgressError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig, validate_model_configs


class PolicyQuota(Protocol):
    async def ensure_new_user(
        self, tenant_id: int, user_id: int, *, operation_id: str, lease_generation: int, epoch: int, proof: dict
    ) -> None: ...

    async def block_policy(
        self,
        tenant_id: int,
        user_id: int,
        *,
        operation_id: str,
        lease_generation: int,
        epoch: int,
        expected_version: int,
    ) -> None: ...

    async def install_policy(
        self,
        tenant_id: int,
        user_id: int,
        *,
        operation_id: str,
        lease_generation: int,
        epoch: int,
        expected_version: int,
        version: int,
        model_configs: list[DshModelQuotaConfig],
    ) -> None: ...

    async def finish_policy(
        self,
        tenant_id: int,
        user_id: int,
        *,
        operation_id: str,
        lease_generation: int,
        epoch: int,
        expected_policy_version: int,
    ) -> None: ...


class DshAdminService:
    """Inject current management/model authorization, never client-provided grants.

    repository_scope must commit on normal exit and rollback on exceptions.
    authorize(actor_user_id, user_id) checks the current administrative action and
    target tenant/status; validate_models(actor_user_id, user_id, model_ids) uses
    the existing model accessibility service, including legitimate root sharing.
    Worker calls resume with a restored strict tenant context.
    """

    def __init__(
        self,
        *,
        repository_scope: Callable[[], AbstractContextManager[DshPolicyRepository]],
        quota: PolicyQuota,
        authorize: Callable[[int, int], Awaitable[bool]],
        validate_models: Callable[[int, int, list[int]], Awaitable[bool]],
        now: Callable[[], datetime],
        lease_seconds: int = 30,
    ):
        self.repository_scope = repository_scope
        self.quota = quota
        self.authorize = authorize
        self.validate_models = validate_models
        self.now = now
        self.lease_seconds = lease_seconds

    async def update_policy(self, *, user_id: int, actor_user_id: int, request: DshUserPolicyInput) -> dict:
        if not await self.authorize(actor_user_id, user_id):
            raise DshOperationConflictError()
        with self.repository_scope() as repository:
            operation = repository.register_update(
                operation_id=request.operation_id,
                user_id=user_id,
                actor_user_id=actor_user_id,
                expected_version=request.expected_version,
                model_configs=request.models,
            )
            result = operation.model_dump()
        if result["status"] in {"SUCCEEDED", "FAILED"}:
            return result
        return await self.resume(request.operation_id)

    def _read(self, operation_id: str) -> dict:
        with self.repository_scope() as repository:
            operation = repository.operations.get(operation_id)
            if operation is None or operation.action != "UPDATE_POLICY":
                raise DshOperationConflictError()
            return operation.model_dump()

    async def resume(self, operation_id: str) -> dict:
        current = self._read(operation_id)
        if current["status"] in {"SUCCEEDED", "FAILED"}:
            return current
        try:
            with self.repository_scope() as repository:
                operation = repository.operations.claim(operation_id, now=self.now(), lease_seconds=self.lease_seconds)
                current = operation.model_dump()
                policy = repository.get(operation.user_id)
                if policy is None:
                    raise DshOperationConflictError()
                epoch = policy.quota_epoch
        except DshOperationInProgressError:
            return self._read(operation_id)
        generation = current["lease_generation"]
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise DshOperationConflictError()
        subject = (tenant_id, current["user_id"])
        ownership = {"operation_id": operation_id, "lease_generation": generation, "epoch": epoch}
        expected = current["expected_policy_version"]
        try:
            if expected == 0 and current["committed_at"] is None:
                with self.repository_scope() as repository:
                    proof = repository.new_user_proof(operation_id, generation, now=self.now())
                await self.quota.ensure_new_user(*subject, **ownership, proof=proof)
            # Reclaim the Redis owner even after response loss or SQL READY rollback.
            await self.quota.block_policy(*subject, **ownership, expected_version=expected)
            if current["committed_at"] is None:
                permitted, models_allowed = True, False
                try:
                    permitted = await self.authorize(current["actor_user_id"], current["user_id"])
                    models_allowed = permitted and await self.validate_models(
                        current["actor_user_id"],
                        current["user_id"],
                        [item.model_id for item in validate_model_configs(current["payload"]["model_configs"])],
                    )
                except DshModelNotAllowedError:
                    models_allowed = False
                except HTTPException as denied:
                    if denied.status_code != 403:
                        raise
                    permitted = False
                if not models_allowed:
                    await self.quota.finish_policy(*subject, **ownership, expected_policy_version=expected)
                    with self.repository_scope() as repository:
                        operation = repository.fail_uncommitted(
                            operation_id,
                            generation,
                            code="permission_revoked" if not permitted else "model_not_allowed",
                            now=self.now(),
                        )
                    return self._read(operation_id)
                with self.repository_scope() as repository:
                    operation = repository.commit_update(operation_id, generation, now=self.now())
                    current = operation.model_dump()
            after = current["after_values"]
            await self.quota.install_policy(
                *subject,
                **ownership,
                expected_version=expected,
                version=after["version"],
                model_configs=validate_model_configs(after["model_configs"]),
            )
            with self.repository_scope() as repository:
                repository.mark_ready(operation_id, generation, now=self.now())
            await self.quota.finish_policy(*subject, **ownership, expected_policy_version=after["version"])
            with self.repository_scope() as repository:
                operation = repository.complete_update(operation_id, generation, now=self.now())
            return self._read(operation_id)
        except Exception:
            # Durable PROCESSING is the explicit recovery path for uncertain effects.
            # Log the traceback but persist only a bounded public code, never payloads.
            logger.exception("DSH policy operation {} requires recovery", operation_id)
            try:
                with self.repository_scope() as repository:
                    repository.operations.retry(
                        operation_id,
                        generation,
                        code="policy_sync_pending",
                        now=self.now(),
                        retry_at=self.now() + timedelta(seconds=5),
                    )
            except Exception:
                logger.exception("Could not schedule DSH policy operation {} retry", operation_id)
            return self._read(operation_id)
