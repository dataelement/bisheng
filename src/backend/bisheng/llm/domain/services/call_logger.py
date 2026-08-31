"""F017 ModelCallLogger — tenant-attributed LLM call audit.

Pairs with ``LLMTokenTracker``. Where the token tracker feeds F016's
monthly token quota, the call logger feeds latency analytics / error
rate dashboards / future per-call cost accounting. Same INV-T13 rule:
``tenant_id = caller's leaf tenant``; refuse to persist when missing
(AC-11).

The logger is separate from the token tracker because:
  - failed calls produce no token usage but should still be audited;
  - latency is interesting per call, not per token;
  - tenant ops reads two different dashboards.
"""

from __future__ import annotations

import logging
from typing import Any

from loguru import logger as structured_logger

from bisheng.common.errcode.tenant_sharing import TenantContextMissingError
from bisheng.common.services.metric_log import emit_metric
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.domain.models.llm_call_log import LLMCallLog, LLMCallLogDao
from bisheng.utils.async_utils import run_async_safe

logger = logging.getLogger(__name__)


class ModelRateLimitDiagnostics:
    """Emit F051 diagnostics without exposing provider detail to API DTOs."""

    @classmethod
    def rate_limit_detected(cls, **fields: Any) -> None:
        structured_logger.bind(**fields).warning("F051 aliyun transient rate limit detected")
        emit_metric("aliyun_rate_limit_detected_total", **fields)

    @classmethod
    def rate_limit_recovered(cls, **fields: Any) -> None:
        structured_logger.bind(**fields).info("F051 aliyun model rate limit recovered")
        emit_metric("aliyun_rate_limit_recovered_total", **fields)

    @classmethod
    def state_write_failed(cls, **fields: Any) -> None:
        structured_logger.bind(**fields).warning("F051 model rate-limit state operation failed")
        emit_metric("model_rate_limit_state_failed_total", **fields)


class ModelCallLogger:
    """Record per-call audit rows attributed to the caller's leaf tenant."""

    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"

    @classmethod
    async def log(
        cls,
        user_id: int,
        status: str,
        *,
        model_id: int | None = None,
        server_id: int | None = None,
        endpoint: str | None = None,
        latency_ms: int | None = None,
        error_msg: str | None = None,
    ) -> LLMCallLog:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise TenantContextMissingError()

        # Defensive truncation of the error string — the column is 512 chars;
        # LLM provider errors can carry multi-kilobyte stack traces.
        trimmed_error: str | None = None
        if error_msg is not None:
            trimmed_error = str(error_msg)[:500]

        row = LLMCallLog(
            tenant_id=tenant_id,
            user_id=user_id,
            model_id=model_id,
            server_id=server_id,
            endpoint=endpoint,
            status=status,
            latency_ms=latency_ms,
            error_msg=trimmed_error,
        )
        return await LLMCallLogDao.acreate(row)

    @classmethod
    async def log_success(cls, user_id: int, **kwargs) -> LLMCallLog:
        return await cls.log(user_id, cls.STATUS_SUCCESS, **kwargs)

    @classmethod
    async def log_error(cls, user_id: int, error_msg: str, **kwargs) -> LLMCallLog:
        return await cls.log(user_id, cls.STATUS_ERROR, error_msg=error_msg, **kwargs)

    @classmethod
    def log_sync(cls, user_id: int, status: str, **kwargs) -> LLMCallLog | None:
        try:
            return run_async_safe(cls.log(user_id, status, **kwargs))
        except TenantContextMissingError:
            raise
        except Exception as e:  # pragma: no cover
            logger.warning("[F017] ModelCallLogger.log_sync failed: %s", e)
            return None
