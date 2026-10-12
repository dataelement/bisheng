"""Read existing business data without writing robot or conversation state."""

from fastapi import HTTPException

from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.common.permission_identity import check_tenant_admin
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.tenant import UserTenantDao
from bisheng.eplus.domain.repositories.eplus_repository import EPlusConfigRepository
from bisheng.eplus.domain.schemas.debug import DebugContext
from bisheng.eplus.infrastructure.config_adapters import SqlSpaceReader
from bisheng.user.domain.models.user import UserDao


class PlatformDebugAuthorization:
    async def require_login(self, operator):
        if not operator.user_id or int(operator.user_id) <= 0:
            raise HTTPException(401, "login required")
        tenant_id = get_current_tenant_id()
        if tenant_id is None or int(tenant_id) != int(operator.tenant_id):
            raise HTTPException(403, "debug tenant mismatch")

    async def can_switch_user(self, operator):
        await self.require_login(operator)
        return bool(operator.is_global_super or await check_tenant_admin(operator.user_id, int(operator.tenant_id)))


class PlatformDebugReader:
    def __init__(self, session):
        self.session = session

    async def load_context(self, assistant_id, test_user_id, operator_id):
        tenant_id = int(get_current_tenant_id() or 0)
        assistant = await AssistantDao.aget_one_assistant(assistant_id)
        config = await EPlusConfigRepository(self.session).get_by_assistant_id(
            tenant_id=tenant_id, assistant_id=assistant_id
        )
        if assistant is None or config is None or config.is_deleted:
            return None
        user = await UserDao.aget_user(test_user_id)
        membership = await UserTenantDao.aget_active_user_tenant(test_user_id)
        if user is None or user.delete or membership is None or int(membership.tenant_id) != tenant_id:
            raise HTTPException(403, "test user is not active in this tenant")
        if getattr(membership, "status", "active") != "active":
            raise HTTPException(403, "test user membership unavailable")
        ids = tuple(
            await EPlusConfigRepository(self.session).list_space_ids(tenant_id=tenant_id, bot_config_id=config.id)
        )
        spaces = await SqlSpaceReader(self.session).list_valid_spaces(tenant_id=tenant_id)
        return DebugContext(
            tenant_id=tenant_id,
            operator_id=operator_id,
            test_user_id=test_user_id,
            test_user_name=user.user_name,
            external_user_id=user.external_id or "",
            assistant=assistant,
            robot_scope=AssistantRobotScope(config.id, ids, config.scope_version),
            bot_id=config.bot_id,
            spaces=tuple({"id": s.id, "name": s.name} for s in spaces if s.id in ids),
        )
