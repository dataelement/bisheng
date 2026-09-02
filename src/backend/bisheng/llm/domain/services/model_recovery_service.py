from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from bisheng.common.errcode.workstation import ModelRecoveryRejectedError
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.llm.domain.services.call_logger import ModelRateLimitDiagnostics
from bisheng.llm.domain.services.model_rate_limit import (
    ClaimedAttempt,
    RecoveryAction,
    RecoveryCommand,
    RecoveryPort,
    RecoverySubject,
)

_RECOVERY_LOCK_TTL_SECONDS = 5
_RELEASE_RECOVERY_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class RecoveryNotAllowedError(ModelRecoveryRejectedError):
    """The original business record cannot be safely resumed."""


def _recovery_lock_key(*, tenant_id: int, user_id: int, entry: str, subject_id: str) -> str:
    return f"model-recovery-lock:{tenant_id}:{user_id}:{entry}:{subject_id}"


def build_recovery_rejected_sse(attempt: ClaimedAttempt | RecoveryCommand) -> str:
    """Return a recovery rejection without classifying it as model throttling."""
    model_id = getattr(attempt, "model_id", None)
    if model_id is None:
        model_id = getattr(attempt, "target_model_id", None)
    return ModelRecoveryRejectedError(
        execution_id=attempt.execution_id,
        attempt_id=attempt.attempt_id,
        error_type="recovery_rejected",
        recovery_subject_id=attempt.subject_id,
        model_id=model_id,
    ).to_sse_event_instance_str()


class ModelRecoveryService:
    """Authorize one recovery from its business record and briefly deduplicate clicks.

    The Redis key is deliberately short-lived and is not an execution state
    machine. It protects near-simultaneous clicks only; the conversation message
    or task version remains the sole source of recovery content and progress.
    """

    def __init__(self, *, redis_factory=get_redis_client, diagnostics: Any = ModelRateLimitDiagnostics) -> None:
        self._redis_factory = redis_factory
        self._diagnostics = diagnostics

    async def claim_recovery(
        self,
        command: RecoveryCommand,
        *,
        tenant_id: int,
        user_id: int,
        entry: str,
        subject_type: str,
        resume_mode: str,
        port: RecoveryPort,
    ) -> ClaimedAttempt:
        subject = RecoverySubject(
            execution_id=command.execution_id,
            subject_type=subject_type,
            subject_id=command.subject_id,
        )
        await port.ensure_subject_access(subject)
        if subject.active_model_id <= 0:
            raise RecoveryNotAllowedError("recovery source model is unavailable")

        if command.action == RecoveryAction.MANUAL_RETRY:
            # The active choice is page-local after a user switches models. Let
            # the client state which model Retry should use; legacy clients that
            # omit it still fall back to the model stored with the original
            # business request.
            target_model_id = command.target_model_id or subject.active_model_id
        elif command.action == RecoveryAction.SWITCH_MODEL:
            if command.target_model_id is None:
                raise RecoveryNotAllowedError("switch model requires a target model")
            target_model_id = command.target_model_id
        else:
            raise RecoveryNotAllowedError("unsupported recovery action")

        await port.ensure_target_model(
            subject,
            target_model_id,
            allow_busy=command.action == RecoveryAction.MANUAL_RETRY,
        )
        should_execute = await self._acquire_short_lock(
            tenant_id=tenant_id,
            user_id=user_id,
            entry=entry,
            subject_id=command.subject_id,
            attempt_id=command.attempt_id,
        )
        return ClaimedAttempt(
            execution_id=command.execution_id,
            attempt_id=command.attempt_id,
            subject_id=command.subject_id,
            entry=entry,
            model_id=target_model_id,
            resume_mode=resume_mode,
            action=command.action,
            should_execute=should_execute,
        )

    async def _acquire_short_lock(
        self,
        *,
        tenant_id: int,
        user_id: int,
        entry: str,
        subject_id: str,
        attempt_id: str,
    ) -> bool:
        key = _recovery_lock_key(
            tenant_id=tenant_id,
            user_id=user_id,
            entry=entry,
            subject_id=subject_id,
        )
        try:
            redis = await self._redis_factory()
            return bool(
                await redis.async_connection.set(
                    key,
                    attempt_id,
                    nx=True,
                    ex=_RECOVERY_LOCK_TTL_SECONDS,
                )
            )
        except Exception as exc:
            # Recovery content is still protected by entry authorization. A cache
            # outage only removes the best-effort duplicate-click guard.
            self._diagnostics.state_write_failed(
                tenant_id=tenant_id,
                user_id=user_id,
                entry=entry,
                operation="recovery_short_lock",
                error_type=type(exc).__name__,
            )
            return True

    async def release_recovery_lock(
        self,
        attempt: ClaimedAttempt,
        *,
        tenant_id: int,
        user_id: int,
    ) -> None:
        """Release only the short lock owned by this completed attempt."""
        key = _recovery_lock_key(
            tenant_id=tenant_id,
            user_id=user_id,
            entry=attempt.entry,
            subject_id=attempt.subject_id,
        )
        try:
            redis = await self._redis_factory()
            await redis.async_connection.eval(
                _RELEASE_RECOVERY_LOCK_SCRIPT,
                1,
                key,
                attempt.attempt_id,
            )
        except Exception as exc:
            # A failed best-effort cleanup remains bounded by the short lock TTL.
            self._diagnostics.state_write_failed(
                tenant_id=tenant_id,
                user_id=user_id,
                entry=attempt.entry,
                operation="recovery_short_unlock",
                error_type=type(exc).__name__,
            )

    async def release_lock_after_stream(
        self,
        stream: AsyncIterable[Any],
        attempt: ClaimedAttempt,
        *,
        tenant_id: int,
        user_id: int,
    ) -> AsyncIterator[Any]:
        """Keep duplicate protection while streaming and release it on exit."""
        try:
            async for item in stream:
                yield item
        finally:
            await self.release_recovery_lock(
                attempt,
                tenant_id=tenant_id,
                user_id=user_id,
            )
