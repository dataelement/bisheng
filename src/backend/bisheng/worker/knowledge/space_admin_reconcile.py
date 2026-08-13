"""Celery task — 6h reconcile of the F045 single-space-admin materialization.

``department_knowledge_space.admin_user_id`` is the source of truth; the ADMIN
member row and the OpenFGA ``knowledge_space#manager`` tuple are materialized
copies written on a best-effort basis (DB and FGA are not transactional). This
task is the catch-all safety net for:

  - an FGA write that failed during create/replace (tuple missing, admin has
    "the name but not the power");
  - an admin invalidation entry point that was missed (account disabled or
    removed without flipping the space to pending);
  - member-row drift (row deleted/demoted out-of-band).

The scheduled entry is registered by ``CeleryConf.validate`` in
``bisheng.core.config.settings``.
"""

import logging

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(acks_late=True, time_limit=1800, soft_time_limit=1500)
def reconcile_department_space_admins():
    run_async_task(_reconcile_async)


async def _reconcile_async() -> None:
    from sqlmodel import select

    from bisheng.common.models.space_channel_member import (
        MembershipStatusEnum,
        SpaceChannelMemberDao,
        UserRoleEnum,
    )
    from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.models.department_knowledge_space import (
        DepartmentKnowledgeSpace,
    )
    from bisheng.knowledge.domain.services.department_knowledge_space_service import (
        SPACE_ADMIN_MEMBERSHIP_SOURCE,
        DepartmentKnowledgeSpaceService,
    )
    from bisheng.user.domain.models.user import UserDao

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            result = await session.exec(select(DepartmentKnowledgeSpace))
            bindings = result.all()

    repaired = 0
    invalidated = 0
    for binding in bindings:
        if binding.admin_user_id is None:
            continue
        if binding.tenant_id:
            set_current_tenant_id(int(binding.tenant_id))
        admin_user_id = int(binding.admin_user_id)
        try:
            user = await UserDao.aget_user(admin_user_id)
            if user is None or user.delete:
                # Missed invalidation hook — flip the space to pending now.
                invalidated += await DepartmentKnowledgeSpaceService.handle_admin_invalidated(admin_user_id)
                continue
            member = await SpaceChannelMemberDao.async_find_member(int(binding.space_id), admin_user_id)
            drifted = (
                member is None
                or member.user_role != UserRoleEnum.ADMIN
                or member.status != MembershipStatusEnum.ACTIVE
                or member.membership_source != SPACE_ADMIN_MEMBERSHIP_SOURCE
            )
            # _materialize_space_admin is idempotent: it repairs the member row
            # and (re)writes the manager tuple, covering the failed-FGA case
            # even when the member row itself looks healthy.
            await DepartmentKnowledgeSpaceService._materialize_space_admin(
                space_id=int(binding.space_id),
                user_id=admin_user_id,
            )
            if drifted:
                repaired += 1
                logger.warning(
                    "F045 reconcile repaired space admin materialization: space=%s user=%s",
                    binding.space_id,
                    admin_user_id,
                )
        except Exception:
            logger.exception(
                "F045 reconcile failed for space=%s admin=%s",
                binding.space_id,
                binding.admin_user_id,
            )

    logger.info(
        "F045 space-admin reconcile done: bindings=%s repaired=%s invalidated=%s",
        len(bindings),
        repaired,
        invalidated,
    )
