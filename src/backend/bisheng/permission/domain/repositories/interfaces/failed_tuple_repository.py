from abc import ABC, abstractmethod
from datetime import datetime

from bisheng.database.models.failed_tuple import FailedTuple


class FailedTupleRepository(ABC):
    @abstractmethod
    def claim(self, owner: str, now: datetime, limit: int = 100) -> list[FailedTuple]: ...

    @abstractmethod
    def renew(self, owner: str, now: datetime) -> None: ...

    @abstractmethod
    def settle(self, owner: str, outcomes: dict[int, str | None], now: datetime) -> int: ...
