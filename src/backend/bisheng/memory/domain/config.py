"""Deployment-level memory parameters (design decision 19).

Read from the database runtime config key ``memory``; ``aget_from_db`` returns an
empty dict for a missing key, so every default lives here in code.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from loguru import logger


@dataclass(frozen=True)
class MemoryRuntimeConfig:
    resident_max_items: int = 60
    resident_max_chars: int = 6000
    experience_max_items: int = 20
    experience_max_chars: int = 2000
    quiet_minutes: int = 30
    scan_interval_minutes: int = 5
    lock_ttl_minutes: int = 10
    default_timezone: str = "Asia/Shanghai"
    auto_consolidation_enabled: bool = True

    @classmethod
    def from_mapping(cls, raw: dict | None) -> MemoryRuntimeConfig:
        raw = raw or {}
        values = {}
        for f in fields(cls):
            if f.name not in raw or raw[f.name] is None:
                continue
            try:
                values[f.name] = _cast(f.default, raw[f.name])
            except (TypeError, ValueError):
                logger.warning("memory config {}={!r} is invalid; using default {!r}", f.name, raw[f.name], f.default)
        return cls(**values)


def _cast(default, value):
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int):
        return int(value)
    return str(value)


async def aget_memory_config() -> MemoryRuntimeConfig:
    from bisheng.common.services.config_service import settings

    return MemoryRuntimeConfig.from_mapping(await settings.aget_from_db("memory"))


def get_memory_config() -> MemoryRuntimeConfig:
    from bisheng.common.services.config_service import settings

    return MemoryRuntimeConfig.from_mapping(settings.get_from_db("memory"))
