"""Admin operations for the portal home hot-search batch pipeline (F048)."""

from __future__ import annotations

from collections.abc import Callable

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    PortalHotSearchDisabledError,
    SpacePermissionDeniedError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    PortalHotSearchTriggerRebuildReq,
    PortalHotSearchTriggerRebuildResp,
)
from bisheng.utils.http_middleware import _check_is_global_super

KNOWLEDGE_QUEUE = "knowledge_celery"


class PortalHotSearchAdminService:
    """Dispatch manual hot-search rebuild Celery tasks (AC-34)."""

    @classmethod
    async def trigger_rebuild(
        cls,
        req: PortalHotSearchTriggerRebuildReq,
        *,
        login_user: UserPayload,
        dispatch_tenant_rebuild: Callable[[int], str] | None = None,
        dispatch_fanout_rebuild: Callable[[], str] | None = None,
    ) -> PortalHotSearchTriggerRebuildResp:
        if not settings.portal_hot_search.enabled:
            raise PortalHotSearchDisabledError()

        if req.fanout:
            if not await _check_is_global_super(login_user.user_id):
                raise SpacePermissionDeniedError()
            dispatch = dispatch_fanout_rebuild or cls._dispatch_fanout_rebuild
            task_id = dispatch()
            return PortalHotSearchTriggerRebuildResp(
                scope="all",
                task_id=task_id,
                task_name="bisheng.worker.knowledge.portal_hot_search.fanout_portal_hot_search_rebuild",
                message="Hot-search fanout rebuild dispatched for all active tenants",
            )

        tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
        dispatch = dispatch_tenant_rebuild or cls._dispatch_tenant_rebuild
        task_id = dispatch(tenant_id)
        return PortalHotSearchTriggerRebuildResp(
            scope="tenant",
            tenant_id=tenant_id,
            task_id=task_id,
            task_name="bisheng.worker.knowledge.portal_hot_search.trigger_portal_hot_search_rebuild",
            message="Hot-search rebuild dispatched for current tenant",
        )

    @staticmethod
    def _dispatch_tenant_rebuild(tenant_id: int) -> str:
        from bisheng.worker.knowledge.portal_hot_search import trigger_portal_hot_search_rebuild_celery

        async_result = trigger_portal_hot_search_rebuild_celery.apply_async(
            headers={"tenant_id": tenant_id},
            queue=KNOWLEDGE_QUEUE,
        )
        return str(async_result.id)

    @staticmethod
    def _dispatch_fanout_rebuild() -> str:
        from bisheng.worker.knowledge.portal_hot_search import fanout_portal_hot_search_rebuild

        async_result = fanout_portal_hot_search_rebuild.apply_async(queue=KNOWLEDGE_QUEUE)
        return str(async_result.id)
