from __future__ import annotations

import logging

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
    DepartmentFileViewAccessService,
)
from bisheng.knowledge.domain.services.favorite_notify import (
    FavoriteNotificationService,
    can_user_view_favorite_source,
)
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
        from bisheng.message.api.dependencies import get_message_service

        async with get_async_db_session() as session:
            file_repository = KnowledgeFileRepositoryImpl(session)
            grant_repository = DepartmentFileViewGrantRepositoryImpl(session)
            access_service = DepartmentFileViewAccessService(
                session=session,
                grant_repository=grant_repository,
                persist_stale_grant_revalidation=True,
            )
            message_service = await get_message_service(session)
            public_space_cache: dict[int, bool] = {}

            async def can_view_file(user_id: int, file) -> bool:
                return await can_user_view_favorite_source(
                    user_id=int(user_id),
                    tenant_id=tenant_id,
                    source_file=file,
                    department_access_service=access_service,
                    public_space_cache=public_space_cache,
                )

            service = FavoriteNotificationService(
                file_repository=file_repository,
                message_service=message_service,
                can_view_file=can_view_file,
            )
            return await service.consume(events)
    finally:
        current_tenant_id.reset(token)
