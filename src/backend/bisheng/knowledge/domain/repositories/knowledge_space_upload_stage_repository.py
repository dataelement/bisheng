from __future__ import annotations

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_space_upload_stage import (
    KnowledgeSpaceUploadStage,
    KnowledgeSpaceUploadStageState,
)


class KnowledgeSpaceUploadStageRepository:
    """Session-bound persistence for tenant-scoped upload stages."""

    _RESERVED_STATES = (
        KnowledgeSpaceUploadStageState.UPLOADED,
        KnowledgeSpaceUploadStageState.ATTACHING,
        KnowledgeSpaceUploadStageState.ATTACHED,
    )

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def build_upload_id_statement(
        *,
        tenant_id: int,
        upload_id: str,
        for_update: bool = False,
    ):
        statement = select(KnowledgeSpaceUploadStage).where(
            KnowledgeSpaceUploadStage.tenant_id == int(tenant_id),
            KnowledgeSpaceUploadStage.upload_id == str(upload_id),
        )
        return statement.with_for_update() if for_update else statement

    async def get_by_upload_id(
        self,
        *,
        tenant_id: int,
        upload_id: str,
        for_update: bool = False,
    ) -> KnowledgeSpaceUploadStage | None:
        statement = self.build_upload_id_statement(
            tenant_id=tenant_id,
            upload_id=upload_id,
            for_update=for_update,
        )
        return (await self.session.exec(statement)).first()

    @classmethod
    def build_reserved_bytes_statement(
        cls,
        *,
        tenant_id: int,
        uploader_user_id: int | None = None,
    ):
        statement = select(func.coalesce(func.sum(KnowledgeSpaceUploadStage.file_size), 0)).where(
            KnowledgeSpaceUploadStage.tenant_id == int(tenant_id),
            KnowledgeSpaceUploadStage.state.in_(cls._RESERVED_STATES),
        )
        if uploader_user_id is not None:
            statement = statement.where(KnowledgeSpaceUploadStage.uploader_user_id == int(uploader_user_id))
        return statement

    async def get_reserved_bytes(
        self,
        *,
        tenant_id: int,
        uploader_user_id: int | None = None,
    ) -> int:
        statement = self.build_reserved_bytes_statement(
            tenant_id=tenant_id,
            uploader_user_id=uploader_user_id,
        )
        return int((await self.session.exec(statement)).one() or 0)

    async def add(self, stage: KnowledgeSpaceUploadStage) -> KnowledgeSpaceUploadStage:
        self.session.add(stage)
        await self.session.flush()
        # `create_time` is filled by the column's server default, so the INSERT leaves it
        # unloaded on the instance. Callers read the stage after the session closed, where
        # a lazy load raises DetachedInstanceError — load it while the session is still open.
        await self.session.refresh(stage)
        return stage

    async def save(self, stage: KnowledgeSpaceUploadStage) -> KnowledgeSpaceUploadStage:
        self.session.add(stage)
        await self.session.flush()
        return stage
