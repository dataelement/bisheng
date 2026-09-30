from abc import ABC, abstractmethod
from datetime import datetime

from bisheng.knowledge.domain.models.knowledge_background_job import KnowledgeBackgroundJob


class KnowledgeBackgroundRepository(ABC):
    @abstractmethod
    def request(
        self, *, tenant_id: int, kind: str, identity: str, payload: dict, parent_id: str | None = None
    ) -> str: ...

    @abstractmethod
    def claim(self, job_id: str, owner: str, now: datetime) -> KnowledgeBackgroundJob | None: ...

    @abstractmethod
    def settle(self, job_id: str, owner: str, *, status: str, payload: dict, error: str | None = None) -> bool: ...
