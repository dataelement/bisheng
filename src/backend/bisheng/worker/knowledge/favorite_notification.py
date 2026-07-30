from __future__ import annotations

import logging

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.favorite_notification_schema import (
    FavoriteChangeEvent,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessStatus,
    DepartmentFileViewAccessService,
)
from bisheng.knowledge.domain.services.favorite_notify import (
    FavoriteNotificationService,
)
from bisheng.message.api.dependencies import get_message_service
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    time_limit=300,
    soft_time_limit=240,
    name="bisheng.worker.knowledge.favorite_notification.send_favorite_change_notifications",
)
def send_favorite_change_notifications(payloads: list[dict]) -> int:
    """消费一批收藏源文件变化事件。"""
    return run_async_task(lambda: _consume_async(payloads))


async def _consume_async(payloads: list[dict]) -> int:
    events: list[FavoriteChangeEvent] = []
    for payload in payloads or []:
        try:
            events.append(FavoriteChangeEvent.model_validate(payload))
        except Exception:
            logger.exception("favorite notification payload validation failed")
    if not events:
        return 0
    tenant_ids = {int(event.tenant_id) for event in events}
    if len(tenant_ids) != 1:
        logger.error(
            "favorite notification batch contains multiple tenants: %s",
            sorted(tenant_ids),
        )
        return 0

    tenant_id = next(iter(tenant_ids))
    token = set_current_tenant_id(tenant_id)
    try:
        async with get_async_db_session() as session:
            file_repository = KnowledgeFileRepositoryImpl(session)
            grant_repository = DepartmentFileViewGrantRepositoryImpl(session)
            access_service = DepartmentFileViewAccessService(
                session=session,
                grant_repository=grant_repository,
                persist_stale_grant_revalidation=True,
            )
            message_service = await get_message_service(session)

            async def can_view_file(user_id: int, file) -> bool:
                user = await UserDao.aget_user(int(user_id))
                if user is None or int(getattr(user, "delete", 0) or 0) != 0:
                    return False
                roles = await UserRoleDao.aget_user_roles(int(user_id))
                role_ids = [int(role.role_id) for role in roles]
                login_user = UserPayload(
                    user_id=int(user_id),
                    user_name=str(getattr(user, "user_name", "") or ""),
                    user_role=role_ids or [-1],
                    tenant_id=tenant_id,
                )
                decision = await access_service.evaluate_file(
                    login_user=login_user,
                    file=file,
                )
                if decision.status == DepartmentFileAccessStatus.ALLOWED:
                    return True
                if decision.status != DepartmentFileAccessStatus.NOT_APPLICABLE:
                    return False
                return await PermissionService.check(
                    user_id=int(user_id),
                    relation="can_read",
                    object_type="knowledge_file",
                    object_id=str(file.id),
                    login_user=login_user,
                )

            service = FavoriteNotificationService(
                file_repository=file_repository,
                message_service=message_service,
                can_view_file=can_view_file,
            )
            return await service.consume(events)
    finally:
        current_tenant_id.reset(token)
