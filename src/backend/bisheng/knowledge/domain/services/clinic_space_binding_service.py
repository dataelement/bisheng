"""科室库编辑与默认组织授权的事务协调。"""

import logging

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.interfaces.department_space_binding_repository import (
    DepartmentSpaceBindingRepository,
)
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRevokeItem
from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService
from bisheng.permission.domain.services.permission_service import PermissionService

logger = logging.getLogger(__name__)


async def update_clinic_space_binding(
    *,
    repository: DepartmentSpaceBindingRepository,
    space: Knowledge,
    old_department_id: int,
    department_id: int,
    portal_discovery_enabled: bool | None = None,
) -> None:
    """保存时补齐查看者; 改绑仅撤销默认授权, 失败恢复本次改动的元组。"""
    space_id = int(space.id)
    await repository.prepare_clinic_update(
        space=space,
        department_id=department_id,
        expected_department_id=old_department_id,
        portal_discovery_enabled=portal_discovery_enabled,
    )
    grant_ids: set[int] = set()
    revoke_ids: set[int] = set()
    permissions_started = False

    async def authorize(*, reverse: bool = False) -> None:
        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id=str(space_id),
            grants=[
                AuthorizeGrantItem(subject_type="department", subject_id=did, relation="viewer", include_children=False)
                for did in sorted(revoke_ids if reverse else grant_ids)
            ],
            revokes=[
                AuthorizeRevokeItem(
                    subject_type="department", subject_id=did, relation="viewer", include_children=False
                )
                for did in sorted(grant_ids if reverse else revoke_ids)
            ],
            enforce_fga_success=True,
            # 正向失败由当前事务回滚; 只重试补偿, 防止失败队列重新应用已撤销的改绑。
            record_failures=reverse,
        )

    try:
        fga = await PermissionService._aget_fga()
        if fga is None:
            raise RuntimeError("FGAClient unavailable while updating clinic binding")
        existing = {
            item["user"] for item in await fga.read_tuples(object=f"knowledge_space:{space_id}", relation="viewer")
        }
        new_users = set(await PermissionService._expand_subject("department", department_id, True))
        old_users = (
            set(await PermissionService._expand_subject("department", old_department_id, True))
            if old_department_id != department_id
            else set()
        )
        candidates = (old_users - new_users) & existing
        protected = (
            await FineGrainedPermissionService.get_explicitly_bound_tuple_users(
                object_type="knowledge_space",
                object_id=space_id,
                relation="viewer",
                tuple_users=candidates,
            )
            if candidates
            else set()
        )
        grant_ids = {int(user.split(":", 1)[1].split("#", 1)[0]) for user in new_users - existing}
        revoke_ids = {int(user.split(":", 1)[1].split("#", 1)[0]) for user in candidates - protected}
        if grant_ids or revoke_ids:
            permissions_started = True
            await authorize()
        await repository.commit_prepared_rebind()
    except Exception:
        try:
            if permissions_started:
                await authorize(reverse=True)
        except Exception:
            logger.exception("科室库授权补偿失败: space_id=%s", space_id)
            raise
        finally:
            await repository.rollback_prepared_rebind()
        raise
