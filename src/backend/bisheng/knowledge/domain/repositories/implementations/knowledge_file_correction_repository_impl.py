"""文档纠错仓储实现."""

from __future__ import annotations

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_correction import (
    CORRECTION_PENDING,
    KnowledgeFileCorrection,
    KnowledgeFileCorrectionAward,
    KnowledgeFileCorrectionOpen,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_correction_repository import (
    KnowledgeFileCorrectionRepository,
)


class KnowledgeFileCorrectionRepositoryImpl(
    BaseRepositoryImpl[KnowledgeFileCorrection, int],
    KnowledgeFileCorrectionRepository,
):
    """在调用方会话里读写纠错单."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFileCorrection)

    async def lock_file(self, file_id: int) -> KnowledgeFile | None:
        """锁定知识库文件行.

        Args:
            file_id: 知识库文件 ID.

        Returns:
            文件行. 当前租户看不到时返回 None.
        """
        result = await self.session.exec(
            select(KnowledgeFile).where(KnowledgeFile.id == int(file_id)).with_for_update()
        )
        return result.first()

    async def get_by_id(self, correction_id: int) -> KnowledgeFileCorrection | None:
        """按主键读取纠错单.

        Args:
            correction_id: 纠错单 ID.

        Returns:
            纠错单. 不存在时返回 None.
        """
        result = await self.session.exec(
            select(KnowledgeFileCorrection).where(KnowledgeFileCorrection.id == int(correction_id))
        )
        return result.first()

    async def lock_by_id(self, correction_id: int) -> KnowledgeFileCorrection | None:
        """锁定纠错单.

        Args:
            correction_id: 纠错单 ID.

        Returns:
            纠错单. 不存在时返回 None.
        """
        result = await self.session.exec(
            select(KnowledgeFileCorrection)
            .where(KnowledgeFileCorrection.id == int(correction_id))
            .with_for_update()
        )
        return result.first()

    async def list_for_file(self, file_id: int) -> list[KnowledgeFileCorrection]:
        """按创建时间倒序列出这个文件上的纠错.

        Args:
            file_id: 知识库文件 ID.

        Returns:
            纠错单列表. 没有记录时为空列表.
        """
        return await self.list_for_files([int(file_id)])

    async def list_for_files(self, file_ids: list[int]) -> list[KnowledgeFileCorrection]:
        """按创建时间倒序列出这些文件上的纠错.

        Args:
            file_ids: 同一篇文档各个版本的知识库文件 ID.

        Returns:
            纠错单列表. 没有记录时为空列表.
        """
        ids = sorted({int(item) for item in file_ids if int(item) > 0})
        if not ids:
            return []
        result = await self.session.exec(
            select(KnowledgeFileCorrection)
            .where(col(KnowledgeFileCorrection.file_id).in_(ids))
            .order_by(KnowledgeFileCorrection.id.desc())
        )
        return list(result.all())

    async def list_pending_for_files(self, file_ids: list[int]) -> list[KnowledgeFileCorrection]:
        """列出这些文档上仍待处理的纠错.

        Args:
            file_ids: 知识库文件 ID 列表.

        Returns:
            待处理纠错单.
        """
        ids = sorted({int(item) for item in file_ids if int(item) > 0})
        if not ids:
            return []
        result = await self.session.exec(
            select(KnowledgeFileCorrection)
            .where(
                col(KnowledgeFileCorrection.file_id).in_(ids),
                KnowledgeFileCorrection.status == CORRECTION_PENDING,
            )
            .with_for_update()
        )
        return list(result.all())

    async def get_award(
        self,
        *,
        tenant_id: int,
        file_id: int,
        applicant_user_id: int,
    ) -> KnowledgeFileCorrectionAward | None:
        """读取同一人同一文档的积分名额.

        Args:
            tenant_id: 租户 ID.
            file_id: 知识库文件 ID.
            applicant_user_id: 反馈人用户 ID.

        Returns:
            名额行. 还没有第一次通过时返回 None.
        """
        result = await self.session.exec(
            select(KnowledgeFileCorrectionAward).where(
                KnowledgeFileCorrectionAward.tenant_id == int(tenant_id),
                KnowledgeFileCorrectionAward.file_id == int(file_id),
                KnowledgeFileCorrectionAward.applicant_user_id == int(applicant_user_id),
            )
        )
        return result.first()

    async def lock_open_slot(
        self,
        *,
        tenant_id: int,
        file_id: int,
        applicant_user_id: int,
    ) -> KnowledgeFileCorrectionOpen | None:
        """锁定待处理占位.

        Args:
            tenant_id: 租户 ID.
            file_id: 知识库文件 ID.
            applicant_user_id: 反馈人用户 ID.

        Returns:
            占位行. 没有待处理时返回 None.
        """
        result = await self.session.exec(
            select(KnowledgeFileCorrectionOpen)
            .where(
                KnowledgeFileCorrectionOpen.tenant_id == int(tenant_id),
                KnowledgeFileCorrectionOpen.file_id == int(file_id),
                KnowledgeFileCorrectionOpen.applicant_user_id == int(applicant_user_id),
            )
            .with_for_update()
        )
        return result.first()
