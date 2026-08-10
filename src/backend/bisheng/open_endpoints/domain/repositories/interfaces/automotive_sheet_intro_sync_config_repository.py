"""Tenant-keyed automotive sheet intro sync configuration repository contract."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

AUTOMOTIVE_SHEET_INTRO_SYNC_CONFIG_KEY = "automotive_sheet_intro_sync"


def automotive_sheet_intro_sync_physical_key(tenant_id: int) -> str:
    tenant_id = int(tenant_id)
    if tenant_id <= 0:
        raise ValueError("tenant_id must be positive")
    if tenant_id == 1:
        return AUTOMOTIVE_SHEET_INTRO_SYNC_CONFIG_KEY
    return f"{AUTOMOTIVE_SHEET_INTRO_SYNC_CONFIG_KEY}:t:{tenant_id}"


@dataclass(frozen=True)
class AutomotiveSheetIntroSyncConfigRecord:
    key: str
    value: str
    comment: str | None = None


class AutomotiveSheetIntroSyncConfigRepository(ABC):
    @abstractmethod
    async def get(self, tenant_id: int) -> AutomotiveSheetIntroSyncConfigRecord | None:
        """Read the tenant config without locking."""

    @abstractmethod
    async def write_value(self, tenant_id: int, value: str) -> None:
        """Insert/update and flush the tenant config without commit."""
