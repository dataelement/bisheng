from abc import ABC, abstractmethod
from dataclasses import dataclass

API_RATE_LIMIT_CONFIG_KEY = "api_rate_limit_config"


@dataclass(frozen=True)
class ApiRateLimitConfigRecord:
    key: str
    value: str
    comment: str | None = None


class ApiRateLimitConfigRepository(ABC):
    @abstractmethod
    async def get(self) -> ApiRateLimitConfigRecord | None:
        """Read the persisted configuration."""

    @abstractmethod
    async def get_for_update(self) -> ApiRateLimitConfigRecord | None:
        """Read and lock the persisted configuration row."""

    @abstractmethod
    async def write_value(self, value: str) -> None:
        """Insert or update the configuration without committing."""
