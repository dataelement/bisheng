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
from typing import Optional

from bisheng.common.errcode.tenant_sharing import TenantContextMissingError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.domain.models.llm_call_log import LLMCallLog, LLMCallLogDao
from bisheng.utils.async_utils import run_async_safe

logger = logging.getLogger(__name__)


class ModelCallLogger:
    """Record per-call audit rows attributed to the caller's leaf tenant."""

    STATUS_SUCCESS = 'success'
    STATUS_ERROR = 'error'

    @classmethod
    async def log(
        cls,
        user_id: int,
        status: str,
        *,
        model_id: Optional[int] = None,
        server_id: Optional[int] = None,
        endpoint: Optional[str] = None,
        latency_ms: Optional[int] = None,
        error_msg: Optional[str] = None,
    ) -> LLMCallLog:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise TenantContextMissingError()

        # Defensive truncation of the error string — the column is 512 chars;
        # LLM provider errors can carry multi-kilobyte stack traces.
        trimmed_error: Optional[str] = None
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
    def log_sync(cls, user_id: int, status: str, **kwargs) -> Optional[LLMCallLog]:
        try:
            return run_async_safe(cls.log(user_id, status, **kwargs))
        except TenantContextMissingError:
            raise
        except Exception as e:  # pragma: no cover
            logger.warning('[F017] ModelCallLogger.log_sync failed: %s', e)
            return None
