"""MemoryLLM over the platform model service (design decision 18).

Consolidation runs as the memory owner (``user_id``) with application type
``memory``; token usage is recorded by the platform model wrapper under that
type. The personal-credit gate only covers ``daily_chat`` and ``linsight``
(``dsh/domain/services/chat_credits.py``), so these calls never draw on a user's
personal allowance. Any refusal surfaces as ``MemoryLLMCallError``.
"""

from __future__ import annotations

import asyncio

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.llm.domain.services.llm import LLMService
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.services.consolidation_model import resolve_memory_model_id
from bisheng.memory.domain.services.index import default_embedding_loader


CONSOLIDATE_TIMEOUT_SECONDS = 300


class MemoryLLMCallError(Exception):
    """The consolidation model call failed or was refused."""


class PlatformMemoryLLM:
    async def consolidate(self, ctx: MemoryContext, prompt: str) -> str:
        model_id = await resolve_memory_model_id()
        llm = await LLMService.get_bisheng_llm(
            model_id=model_id,
            app_id=ApplicationTypeEnum.MEMORY.value,
            app_name=ApplicationTypeEnum.MEMORY.value,
            app_type=ApplicationTypeEnum.MEMORY,
            user_id=ctx.user_id,
        )
        try:
            # Bounded below the consolidation lock TTL so a hung call cannot outlive the lock.
            response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=CONSOLIDATE_TIMEOUT_SECONDS)
        except Exception as exc:
            raise MemoryLLMCallError(str(exc)) from exc
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        return str(content)

    async def embed(self, ctx: MemoryContext, texts: list[str]) -> list[list[float]]:
        model_id, embedding = await default_embedding_loader(ctx)
        if not model_id:
            return []
        return await embedding.aembed_documents(texts)
