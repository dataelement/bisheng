"""Which model consolidates memory for the current tenant (design decisions 17, 18; AC-106)."""

from __future__ import annotations

from bisheng.common.errcode.memory import MemoryNoModelError
from bisheng.workstation.domain.services.workstation_service import WorkStationService


async def resolve_memory_model_id() -> int:
    """The configured memory model, else the first workstation model, else MemoryNoModelError.

    Reads through ``WorkStationService.aget_config`` so a child tenant without its
    own config inherits the root tenant's value (existing workstation behaviour).
    """
    config = await WorkStationService.aget_config()
    if config is not None and config.memory_model_id:
        return int(config.memory_model_id)
    models = (config.models if config is not None else None) or []
    if isinstance(models, list):
        for model in models:
            model_id = getattr(model, "id", None)
            if model_id not in (None, ""):
                return int(model_id)
    raise MemoryNoModelError()
