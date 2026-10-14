"""纠错提交使用的打开判定, 与阅读页预览放行对齐."""

from bisheng.common.models.space_channel_member import (
    SpaceChannelMemberDao,
    UserRoleEnum,
)
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileViewAccessService,
)
from bisheng.knowledge.domain.services.knowledge_file_correction_service import (
    _public_library_grants_view,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation,
)
from bisheng.permission.domain.services.permission_service import PermissionService

# 和知识库成员角色到关系的映射一致. 成员的查看权在成员表, 不在文件级 view_file.
_MEMBER_ROLE_RELATION = {
    UserRoleEnum.CREATOR: "owner",
    UserRoleEnum.ADMIN: "manager",
    UserRoleEnum.MEMBER: "viewer",
    UserRoleEnum.CREATOR.value: "owner",
    UserRoleEnum.ADMIN.value: "manager",
    UserRoleEnum.MEMBER.value: "viewer",
}


async def user_may_preview_file(login_user, file, knowledge, scope) -> bool:
    """当前用户能否打开并预览这份文件.

    Args:
        login_user: 当前登录用户.
        file: 知识库文件.
        knowledge: 文件所在知识库.
        scope: 知识库层级.

    Returns:
        阅读页会放行预览时为 True. 公共库, 文件 view_file, 库成员和部门/科室打开授权都算.
    """
    if _public_library_grants_view(knowledge, scope):
        return True
    file_id = getattr(file, "id", None)
    if file_id is None:
        return False
    if await _has_view_file(login_user, int(file_id)):
        return True
    space_id = getattr(file, "knowledge_id", None)
    if space_id is not None and await _space_membership_can_view(login_user, int(space_id)):
        return True
    return await _department_or_clinic_can_open(login_user, file)


async def _has_view_file(login_user, file_id: int) -> bool:
    return bool(
        await PermissionService.check(
            int(login_user.user_id),
            "view_file",
            "knowledge_file",
            str(int(file_id)),
            login_user,
        )
    )


async def _space_membership_can_view(login_user, space_id: int) -> bool:
    member = await SpaceChannelMemberDao.async_find_member(int(space_id), int(login_user.user_id))
    if member is None or not member.is_active:
        return False
    relation = _MEMBER_ROLE_RELATION.get(member.user_role)
    if relation is None:
        relation = _MEMBER_ROLE_RELATION.get(getattr(member.user_role, "value", None))
    if not relation:
        return False
    return "view_file" in default_permission_ids_for_relation(relation)


async def _department_or_clinic_can_open(login_user, file) -> bool:
    """部门库、科室库里, 阅读页额外放行的身份.

    文件级 view_file 已在前面查过. 这里只补所有者、部门审批人和查看授权,
    不再走权限模板, 避免纠错提交再去拉一套 OpenFGA 配置.

    Returns:
        这几种身份能打开文件时为 True. 不是部门库或科室库时为 False.
    """
    async with get_async_db_session() as session:
        service = DepartmentFileViewAccessService(
            session=session,
            grant_repository=DepartmentFileViewGrantRepositoryImpl(session),
            persist_stale_grant_revalidation=False,
        )
        resource = await service.load_resource(file)
        if not resource.applicable or not resource.valid or resource.department_id is None:
            return False
        user_id = int(login_user.user_id)
        if callable(getattr(login_user, "is_admin", None)) and login_user.is_admin():
            return True
        if user_id in {
            int(getattr(resource.space, "user_id", 0) or 0),
            int(getattr(file, "user_id", 0) or 0),
        }:
            return True
        approvers = await service.resolve_department_approvers(int(resource.department_id))
        if user_id in approvers:
            return True
        space_id = int(file.knowledge_id)
        file_id = int(file.id)
        grants = await service.grant_repository.list_active_by_user_and_files(
            tenant_id=int(getattr(login_user, "tenant_id", None) or 1),
            user_id=user_id,
            resources={(space_id, file_id): int(resource.department_id)},
        )
        return (space_id, file_id) in grants
