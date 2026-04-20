"""F017 LLMUsageCallbackHandler — tenant-attributed LangChain callback.

Wires ``on_llm_end`` → ``LLMTokenTracker.record_usage`` and
``on_llm_start`` / ``on_llm_end`` / ``on_llm_error`` → ``ModelCallLogger``
so every LangChain invocation produces one ``llm_token_log`` row (on
success) plus one ``llm_call_log`` row (success or error), both stamped
with the caller's leaf tenant (INV-T13).

The handler is invocation-local (built per-call with the known user /
model / server / session ids) because LangChain runs can be reentrant and
we want the right tenant read *at the time* ``on_llm_end`` fires — the
ContextVar is already in place thanks to F012's Worker ``task_prerun``
setup.

Registration surface (optional, caller-owned):

  from bisheng.workflow.callback.llm_usage_callback import LLMUsageCallbackHandler

  handler = LLMUsageCallbackHandler(
      user_id=login_user.user_id,
      model_id=model.id,
      server_id=model.server_id,
      endpoint='https://api.example.com/v1/chat/completions',
  )
  response = await llm.ainvoke(prompt, config={'callbacks': [handler]})

Failures inside the handler (DB hiccup, missing context) are swallowed
into a warning log so token/usage accounting never breaks a user-facing
call — the exception to that is ``TenantContextMissingError``, which
signals a framework bug (middleware not installed) and bubbles as a
warning rather than silencing it.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.outputs import LLMResult
from loguru import logger

from bisheng.common.errcode.tenant_sharing import TenantContextMissingError
from bisheng.llm.domain.services.call_logger import ModelCallLogger
from bisheng.llm.domain.services.token_tracker import LLMTokenTracker


class LLMUsageCallbackHandler(AsyncCallbackHandler):
    """Async LangChain callback that feeds llm_token_log + llm_call_log."""

    def __init__(
        self,
        user_id: int,
        *,
        model_id: Optional[int] = None,
        server_id: Optional[int] = None,
        session_id: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> None:
        self.user_id = user_id
        self.model_id = model_id
        self.server_id = server_id
        self.session_id = session_id
        self.endpoint = endpoint
        self._start_ts: Optional[float] = None

    async def on_llm_start(self, *args: Any, **kwargs: Any) -> None:
        self._start_ts = time.time()

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        latency_ms = self._elapsed_ms()

        # llm_token_log + llm_call_log target two different tables with no
        # ordering dependency; issue both INSERTs concurrently to halve the
        # hot-path latency tail on the per-LLM-call path.
        tasks: list = []
        usage = _extract_token_usage(response)
        if usage is not None:
            prompt_tokens, completion_tokens, total_tokens = usage
            tasks.append(('token', LLMTokenTracker.record_usage(
                user_id=self.user_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                model_id=self.model_id,
                server_id=self.server_id,
                session_id=self.session_id,
            )))
        tasks.append(('call', ModelCallLogger.log_success(
            user_id=self.user_id,
            model_id=self.model_id,
            server_id=self.server_id,
            endpoint=self.endpoint,
            latency_ms=latency_ms,
        )))

        results = await asyncio.gather(
            *(t[1] for t in tasks), return_exceptions=True,
        )
        for (label, _), result in zip(tasks, results):
            if isinstance(result, TenantContextMissingError):
                logger.warning(
                    '[F017] LLMUsageCallbackHandler: tenant context missing on_llm_end '
                    '(user_id=%s model_id=%s) — %s row NOT written',
                    self.user_id, self.model_id, label,
                )
            elif isinstance(result, Exception):  # pragma: no cover
                logger.warning(
                    '[F017] on_llm_end %s write failed: %s', label, result,
                )

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        latency_ms = self._elapsed_ms()
        try:
            await ModelCallLogger.log_error(
                user_id=self.user_id,
                error_msg=str(error),
                model_id=self.model_id,
                server_id=self.server_id,
                endpoint=self.endpoint,
                latency_ms=latency_ms,
            )
        except TenantContextMissingError:
            logger.warning(
                '[F017] LLMUsageCallbackHandler: tenant context missing on_llm_error '
                '(user_id=%s model_id=%s) — error row NOT written',
                self.user_id, self.model_id,
            )
        except Exception as e:  # pragma: no cover
            logger.warning('[F017] ModelCallLogger.log_error failed: %s', e)

    def _elapsed_ms(self) -> Optional[int]:
        if self._start_ts is None:
            return None
        return int((time.time() - self._start_ts) * 1000)


def _extract_token_usage(response: LLMResult) -> Optional[tuple[int, int, int]]:
    """Pull ``(prompt, completion, total)`` from a LangChain ``LLMResult``.

    Providers vary on field names and on where they stuff the usage dict;
    we try the common shapes and bail (returning None) on unfamiliar
    payloads. A None return means we skip the token row for this call
    rather than writing zeroes, because zero-token rows would distort
    F016's monthly quota sum.
    """
    output = getattr(response, 'llm_output', None) or {}
    usage = output.get('token_usage') if isinstance(output, dict) else None
    if not isinstance(usage, dict):
        usage = output.get('usage') if isinstance(output, dict) else None
    if not isinstance(usage, dict):
        return None

    prompt = usage.get('prompt_tokens') or usage.get('input_tokens') or 0
    completion = usage.get('completion_tokens') or usage.get('output_tokens') or 0
    total = usage.get('total_tokens')
    try:
        prompt_int = int(prompt)
        completion_int = int(completion)
    except (TypeError, ValueError):
        return None
    if total is None:
        total_int = prompt_int + completion_int
    else:
        try:
            total_int = int(total)
        except (TypeError, ValueError):
            total_int = prompt_int + completion_int
    if prompt_int == 0 and completion_int == 0 and total_int == 0:
        return None
    return prompt_int, completion_int, total_int
