from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.role_access import AccessType
from bisheng.permission.domain.services.owner_service import _run_async_safe
from bisheng.permission.domain.services.permission_service import PermissionService


_KNOWLEDGE_ACCESS_RELATION = {
    AccessType.KNOWLEDGE: 'can_read',
    AccessType.KNOWLEDGE_WRITE: 'can_edit',
}


class KnowledgePermissionService:
    """Centralized permission checks for knowledge domain services."""

    @staticmethod
    def _get_relation(access_type: AccessType) -> str | None:
        return _KNOWLEDGE_ACCESS_RELATION.get(access_type)

    def check_access_sync(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
            access_type: AccessType,
    ) -> bool:
        relation = self._get_relation(access_type)
        if relation is None:
            return login_user.access_check(owner_user_id, str(knowledge_id), access_type)
        return _run_async_safe(PermissionService.check(
            user_id=login_user.user_id,
            relation=relation,
            object_type='knowledge_library',
            object_id=str(knowledge_id),
            login_user=login_user,
        ))

    async def ensure_access_async(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
            access_type: AccessType,
    ) -> None:
        relation = self._get_relation(access_type)
        if relation is None:
            allowed = await login_user.async_access_check(owner_user_id, str(knowledge_id), access_type)
        else:
            allowed = await PermissionService.check(
                user_id=login_user.user_id,
                relation=relation,
                object_type='knowledge_library',
                object_id=str(knowledge_id),
                login_user=login_user,
            )
        if not allowed:
            raise UnAuthorizedError()

    def ensure_access_sync(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
            access_type: AccessType,
    ) -> None:
        if not self.check_access_sync(login_user, owner_user_id, knowledge_id, access_type):
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

    def ensure_knowledge_write_sync(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
    ) -> None:
        self.ensure_access_sync(login_user, owner_user_id, knowledge_id, AccessType.KNOWLEDGE_WRITE)

    def ensure_knowledge_read_sync(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
    ) -> None:
        self.ensure_access_sync(login_user, owner_user_id, knowledge_id, AccessType.KNOWLEDGE)
