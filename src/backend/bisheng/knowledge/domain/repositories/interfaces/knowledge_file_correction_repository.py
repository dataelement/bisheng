"""文档纠错仓储接口."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file_correction import (
    KnowledgeFileCorrection,
    KnowledgeFileCorrectionAward,
)


class KnowledgeFileCorrectionRepository(BaseRepository[KnowledgeFileCorrection, int], ABC):
    """纠错单, 待处理占位和积分名额的读写."""

    @abstractmethod
    async def lock_file(self, file_id: int):
        """锁定知识库文件行, 供提交和删除串行."""

    @abstractmethod
    async def get_by_id(self, correction_id: int) -> KnowledgeFileCorrection | None:
        """按主键读取纠错单."""

    @abstractmethod
    async def lock_by_id(self, correction_id: int) -> KnowledgeFileCorrection | None:
        """锁定纠错单, 供通过, 拒绝和撤回."""

    @abstractmethod
    async def list_pending_for_files(self, file_ids: list[int]) -> list[KnowledgeFileCorrection]:
        """列出这些文档上仍待处理的纠错."""

    @abstractmethod
    async def get_award(
        self,
        *,
        tenant_id: int,
        file_id: int,
        applicant_user_id: int,
    ) -> KnowledgeFileCorrectionAward | None:
        """读取同一人同一文档的积分名额."""
