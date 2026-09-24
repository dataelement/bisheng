from abc import ABC, abstractmethod


class BackgroundTaskMaintenanceRepository(ABC):
    @abstractmethod
    def inspect_or_restore(self, kind: str, ids: list[str], *, restore: bool = False) -> list[dict]: ...
