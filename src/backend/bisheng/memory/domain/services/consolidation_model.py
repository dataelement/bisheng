"""Which model consolidates memory for the current tenant (design decisions 17, 18; AC-106)."""

from __future__ import annotations

from bisheng.common.errcode.memory import MemoryNoModelError
from bisheng.llm.domain.services.llm import LLMService


async def resolve_memory_model_id() -> int:
    """The memory consolidation model, else the first daily-chat model, else MemoryNoModelError.

    Both live in the workbench section of the system model settings
    (``WorkbenchModelConfig.memory_llm`` / ``.models``). Reading through
    ``LLMService.get_workbench_llm`` keeps the existing inheritance: a child
    tenant without its own row uses the root tenant's value.
    """
    config = await LLMService.get_workbench_llm()
    memory_llm = getattr(config, "memory_llm", None) if config is not None else None
    if memory_llm is not None and getattr(memory_llm, "id", None) not in (None, ""):
        return int(memory_llm.id)
    for model in (getattr(config, "models", None) or []) if config is not None else []:
        model_id = getattr(model, "id", None)
        if model_id not in (None, ""):
            return int(model_id)
    raise MemoryNoModelError()
