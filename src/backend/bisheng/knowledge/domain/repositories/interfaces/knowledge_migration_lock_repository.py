from abc import ABC, abstractmethod


class KnowledgeMigrationLockRepository(ABC):
    @abstractmethod
    async def acquire(self, token: str, *, ttl_seconds: int) -> bool: ...

    @abstractmethod
    async def renew(self, token: str, *, ttl_seconds: int) -> bool: ...

    @abstractmethod
    async def release(self, token: str) -> bool: ...
