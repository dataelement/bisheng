from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.role_access import AccessType


class KnowledgePermissionService:
    """Centralized permission checks for knowledge domain services."""

    async def ensure_access_async(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
            access_type: AccessType,
    ) -> None:
        if not await login_user.async_access_check(owner_user_id, str(knowledge_id), access_type):
            raise UnAuthorizedError()

    async def ensure_knowledge_write_async(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
    ) -> None:
        await self.ensure_access_async(login_user, owner_user_id, knowledge_id, AccessType.KNOWLEDGE_WRITE)

    async def ensure_knowledge_read_async(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
    ) -> None:
        await self.ensure_access_async(login_user, owner_user_id, knowledge_id, AccessType.KNOWLEDGE)
