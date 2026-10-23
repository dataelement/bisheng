"""文件组织归属: 只在首次登记与指定发布成功事务内重算。"""

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_organization_repository_impl import (
    KnowledgeFileOrganizationRepositoryImpl,
)


class KnowledgeFileOrganizationService:
    def __init__(self, session: AsyncSession):
        self.repository = KnowledgeFileOrganizationRepositoryImpl(session)

    async def for_uploader(self, user_id: int, *, tenant_id: int) -> int | None:
        return await self.repository.primary_organization(user_id, tenant_id)

    @staticmethod
    def uploader_organization_sync(user_id: int, *, tenant_id: int) -> int | None:
        with get_sync_db_session() as session:
            return KnowledgeFileOrganizationRepositoryImpl(session).primary_organization_sync(user_id, tenant_id)

    @staticmethod
    async def uploader_organization(user_id: int, *, tenant_id: int) -> int | None:
        async with get_async_db_session() as session:
            return await KnowledgeFileOrganizationService(session).for_uploader(user_id, tenant_id=tenant_id)

    async def apply_publish(
        self, *, document_id: int, source_space_id: int, target_space_id: int, tenant_id: int
    ) -> None:
        source, target, department, group = await self.repository.publish_organization_context(
            source_space_id, target_space_id
        )
        if source is None or target is None or source.level != "personal":
            return
        if source.tenant_id != tenant_id or target.tenant_id != tenant_id:
            raise ValueError("publication organization scope tenant mismatch")
        organization_id = None
        if target.level in {"team", "team_ks"} and (
            target.level == "team_ks" or target.owner_type == "department" or department is not None
        ):
            if (
                department is not None
                and department.tenant_id == tenant_id
                and department.status == "active"
                and not department.is_deleted
            ):
                organization_id = int(department.id)
        elif target.level == "team" and target.owner_type in {"user_group", "user"}:
            if group is not None and group.tenant_id == tenant_id and group.create_user is not None:
                organization_id = await self.for_uploader(int(group.create_user), tenant_id=tenant_id)
        else:
            return
        await self.repository.set_document_organization(document_id, tenant_id, organization_id)
