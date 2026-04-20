"""F017 LLMTokenTracker — INV-T13 compliant token usage recorder.

Contract:
  - ``record_usage`` writes one ``llm_token_log`` row stamped with
    ``tenant_id = get_current_tenant_id()`` (the user's leaf tenant, NOT
    the model's tenant). This is the write half of AC-09: Child's token
    consumption against a Root-shared model accrues to the Child's monthly
    quota, leaving Root's quota unaffected.
  - Refuses to persist a row when the tenant context is missing (AC-11).
    A missing context means an HTTP / WS / Celery middleware failed to set
    the ContextVar, which is a system bug — silent attribution to a wrong
    tenant (or NULL) pollutes F016's quota accounting.

Call sites:
  - ``LLMUsageCallbackHandler.on_llm_end`` (T18) — every LangChain
    invocation.
  - Direct sync callers (non-LangChain paths) may reach for
    ``record_usage_sync`` which performs the coroutine-safe wrap.
"""

from __future__ import annotations

import logging
from typing import Optional

from bisheng.common.errcode.tenant_sharing import TenantContextMissingError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.domain.models.llm_token_log import LLMTokenLog, LLMTokenLogDao
from bisheng.utils.async_utils import run_async_safe

logger = logging.getLogger(__name__)


class LLMTokenTracker:
    """Record token usage attributed to the caller's leaf tenant."""

    @classmethod
    async def record_usage(
        cls,
        user_id: int,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        model_id: Optional[int] = None,
        server_id: Optional[int] = None,
        session_id: Optional[str] = None,
        total_tokens: Optional[int] = None,
    ) -> LLMTokenLog:
        """Persist one row. Raises ``TenantContextMissingError`` on
        missing ContextVar.
        """
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise TenantContextMissingError()

        resolved_total = (
            total_tokens
            if total_tokens is not None
            else (int(prompt_tokens or 0) + int(completion_tokens or 0))
        )
        log = LLMTokenLog(
            tenant_id=tenant_id,
            user_id=user_id,
            model_id=model_id,
            server_id=server_id,
            session_id=session_id,
            prompt_tokens=int(prompt_tokens or 0),
            completion_tokens=int(completion_tokens or 0),
            total_tokens=resolved_total,
        )
        return await LLMTokenLogDao.acreate(log)

    @classmethod
    def record_usage_sync(
        cls,
        user_id: int,
        prompt_tokens: int,
        completion_tokens: int,
        **kwargs,
    ) -> Optional[LLMTokenLog]:
        """Sync wrapper for non-async call-sites.

        On FGA/DB hiccup logs a warning and returns None — token accounting
        must not break a successful user-facing LLM call. AC-11 violations
        (missing tenant context) still raise, because that is a real bug
        worth surfacing.
        """
        try:
            return run_async_safe(
                cls.record_usage(user_id, prompt_tokens, completion_tokens, **kwargs)
            )
        except TenantContextMissingError:
            raise
        except Exception as e:  # pragma: no cover
            logger.warning('[F017] LLMTokenTracker.record_usage_sync failed: %s', e)
            return None
