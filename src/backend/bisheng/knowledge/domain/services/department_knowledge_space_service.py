from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.department import DepartmentNotFoundError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceExistsError,
    SpaceNotFoundError,
)
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    SpaceChannelMemberDao,
    UserRoleEnum,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.department.domain.services.department_service import DepartmentService
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    DepartmentKnowledgeSpaceBatchCreateReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    SPACE_ADMIN_REVOKED_MESSAGE,
    SPACE_MEMBER_REMOVED_MESSAGE,
    KnowledgeSpaceInfoResp,
    KnowledgeSpaceService,
)
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRevokeItem
from bisheng.permission.domain.services.permission_service import PermissionService

_logger = logging.getLogger(__name__)


class DepartmentKnowledgeSpaceService:
    DEFAULT_AUTH_TYPE = AuthTypeEnum.APPROVAL
    DEFAULT_IS_RELEASED = True

    @classmethod
    def _ensure_super_admin(cls, login_user: UserPayload) -> None:
        if not login_user.is_admin():
            raise UnAuthorizedError()

    @classmethod
    def _build_default_name(cls, department_name: str) -> str:
        return f"{department_name}的知识空间"

    @classmethod
    def _build_default_description(cls, department_name: str) -> str:
        return f"{department_name}的知识空间"

    @classmethod
    async def _load_departments(cls, department_ids: Sequence[int]):
        deduped = list(dict.fromkeys(int(i) for i in department_ids))
        rows = await DepartmentDao.aget_by_ids(deduped)
        dept_map = {row.id: row for row in rows if getattr(row, "status", "active") == "active"}
        if len(dept_map) != len(deduped):
            raise DepartmentNotFoundError(msg="One or more departments do not exist or are archived")
        return dept_map

    @classmethod
    async def _grant_default_department_admins(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        space_id: int,
        admin_user_ids: Iterable[int],
    ) -> None:
        for admin_user_id in sorted(set(int(uid) for uid in admin_user_ids if int(uid) != login_user.user_id)):
            existing = await SpaceChannelMemberDao.async_find_member(space_id, admin_user_id)
            if existing is not None:
                if existing.user_role == UserRoleEnum.CREATOR:
                    continue
                if existing.membership_source == "department_admin":
                    if existing.user_role != UserRoleEnum.ADMIN:
                        existing.user_role = UserRoleEnum.ADMIN
                        existing.status = MembershipStatusEnum.ACTIVE
                        await SpaceChannelMemberDao.update(existing)
                    await cls._grant_department_admin_manager(space_id=space_id, user_id=admin_user_id)
                    continue
                if existing.user_role == UserRoleEnum.ADMIN:
                    if existing.status != MembershipStatusEnum.ACTIVE:
                        existing.status = MembershipStatusEnum.ACTIVE
                        await SpaceChannelMemberDao.update(existing)
                    await cls._grant_department_admin_manager(space_id=space_id, user_id=admin_user_id)
                    continue
                existing.department_admin_promoted_from_role = existing.user_role.value
                existing.user_role = UserRoleEnum.ADMIN
                existing.status = MembershipStatusEnum.ACTIVE
                existing.membership_source = "department_admin"
                await SpaceChannelMemberDao.update(existing)
                await cls._grant_department_admin_manager(space_id=space_id, user_id=admin_user_id)
                continue

            member = SpaceChannelMember(
                business_id=str(space_id),
                business_type=BusinessTypeEnum.SPACE,
                user_id=admin_user_id,
                user_role=UserRoleEnum.ADMIN,
                status=MembershipStatusEnum.ACTIVE,
                membership_source="department_admin",
            )
            await SpaceChannelMemberDao.async_insert_member(member)
            await cls._grant_department_admin_manager(space_id=space_id, user_id=admin_user_id)

    @classmethod
    async def _grant_department_admin_manager(cls, *, space_id: int, user_id: int) -> None:
        try:
            await PermissionService.authorize(
                object_type="knowledge_space",
                object_id=str(space_id),
                grants=[
                    AuthorizeGrantItem(
                        subject_type="user",
                        subject_id=user_id,
                        relation="manager",
                        include_children=False,
                    ),
                ],
            )
        except Exception as e:
            _logger.warning(
                "Failed to write department admin manager tuple for space %s user %s: %s",
                space_id,
                user_id,
                e,
            )

    @classmethod
    async def _revoke_department_admin_manager(cls, *, space_id: int, user_id: int) -> None:
        try:
            await PermissionService.authorize(
                object_type="knowledge_space",
                object_id=str(space_id),
                revokes=[
                    AuthorizeRevokeItem(
                        subject_type="user",
                        subject_id=user_id,
                        relation="manager",
                        include_children=False,
                    ),
                ],
            )
        except Exception as e:
            _logger.warning(
                "Failed to delete department admin manager tuple for space %s user %s: %s",
                space_id,
                user_id,
                e,
            )

    @classmethod
    async def _grant_department_members_viewer(
        cls,
        *,
        space_id: int,
        department_id: int,
    ) -> None:
        try:
            await PermissionService.authorize(
                object_type="knowledge_space",
                object_id=str(space_id),
                grants=[
                    AuthorizeGrantItem(
                        subject_type="department",
                        subject_id=department_id,
                        relation="viewer",
                        include_children=True,
                    ),
                ],
            )
        except Exception as e:
            _logger.warning(
                "Failed to write department viewer tuple for space %s department %s: %s",
                space_id,
                department_id,
                e,
            )

    @classmethod
    async def _sync_added_admin(
        cls,
        *,
        space_service: KnowledgeSpaceService,
        space_id: int,
        login_user: UserPayload,
        user_id: int,
    ) -> None:
        if user_id == login_user.user_id:
            return
        existing = await SpaceChannelMemberDao.async_find_member(space_id, user_id)
        if existing is not None:
            if existing.user_role == UserRoleEnum.CREATOR:
                return
            if existing.membership_source == "department_admin":
                existing.user_role = UserRoleEnum.ADMIN
                existing.status = MembershipStatusEnum.ACTIVE
                await SpaceChannelMemberDao.update(existing)
                await cls._grant_department_admin_manager(space_id=space_id, user_id=user_id)
                return
            if existing.user_role == UserRoleEnum.ADMIN:
                if existing.status != MembershipStatusEnum.ACTIVE:
                    existing.status = MembershipStatusEnum.ACTIVE
                    await SpaceChannelMemberDao.update(existing)
                await cls._grant_department_admin_manager(space_id=space_id, user_id=user_id)
                return
            existing.department_admin_promoted_from_role = existing.user_role.value
            existing.user_role = UserRoleEnum.ADMIN
            existing.status = MembershipStatusEnum.ACTIVE
            existing.membership_source = "department_admin"
            await SpaceChannelMemberDao.update(existing)
            await cls._grant_department_admin_manager(space_id=space_id, user_id=user_id)
            return

        member = SpaceChannelMember(
            business_id=str(space_id),
            business_type=BusinessTypeEnum.SPACE,
            user_id=user_id,
            user_role=UserRoleEnum.ADMIN,
            status=MembershipStatusEnum.ACTIVE,
            membership_source="department_admin",
        )
        await SpaceChannelMemberDao.async_insert_member(member)
        await cls._grant_department_admin_manager(space_id=space_id, user_id=user_id)

    @classmethod
    async def _sync_removed_admin(
        cls,
        *,
        space_service: KnowledgeSpaceService,
        space_id: int,
        user_id: int,
    ) -> None:
        existing = await SpaceChannelMemberDao.async_find_member(space_id, user_id)
        if existing is None or existing.user_role == UserRoleEnum.CREATOR:
            return
        if existing.membership_source == "department_admin":
            previous_role = existing.department_admin_promoted_from_role
            if previous_role:
                existing.user_role = UserRoleEnum(previous_role)
                existing.membership_source = "manual"
                existing.department_admin_promoted_from_role = None
                existing.status = MembershipStatusEnum.ACTIVE
                await SpaceChannelMemberDao.update(existing)
                await cls._revoke_department_admin_manager(space_id=space_id, user_id=user_id)
                if not await space_service._user_can_manage_space(user_id, space_id):
                    await space_service._send_space_event_notification(
                        action_code=SPACE_ADMIN_REVOKED_MESSAGE,
                        receiver_user_ids=[user_id],
                        space_id=space_id,
                        navigable=True,
                    )
                return
            await SpaceChannelMemberDao.delete_space_member(space_id, user_id)
            await cls._revoke_department_admin_manager(space_id=space_id, user_id=user_id)
            if not await space_service._user_can_read_space(user_id, space_id):
                await space_service._send_space_event_notification(
                    action_code=SPACE_MEMBER_REMOVED_MESSAGE,
                    receiver_user_ids=[user_id],
                    space_id=space_id,
                    navigable=False,
                )
            return
        if existing.user_role == UserRoleEnum.ADMIN:
            return
        await cls._revoke_department_admin_manager(space_id=space_id, user_id=user_id)

    @classmethod
    async def batch_create_spaces(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        req: DepartmentKnowledgeSpaceBatchCreateReq,
    ) -> list[KnowledgeSpaceInfoResp]:
        cls._ensure_super_admin(login_user)
        if not req.items:
            return []
        dept_ids = [int(item.department_id) for item in req.items]

        dept_map = await cls._load_departments(dept_ids)

        space_service = KnowledgeSpaceService(request=request, login_user=login_user)
        created_spaces: list[KnowledgeSpaceInfoResp] = []
        for item in req.items:
            dept = dept_map[int(item.department_id)]
            space = await space_service.create_knowledge_space(
                name=item.name or cls._build_default_name(dept.name),
                description=item.description or cls._build_default_description(dept.name),
                icon=item.icon,
                auth_type=item.auth_type or cls.DEFAULT_AUTH_TYPE,
                is_released=cls.DEFAULT_IS_RELEASED if item.is_released is None else item.is_released,
                space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                department_id=dept.id,
                skip_user_limit=True,
            )
            await cls._grant_department_members_viewer(
                space_id=space.id,
                department_id=dept.id,
            )
            admin_rows = await DepartmentService.aget_admins(dept.dept_id, login_user)
            await cls._grant_default_department_admins(
                request=request,
                login_user=login_user,
                space_id=space.id,
                admin_user_ids=[row["user_id"] for row in admin_rows],
            )
            created_spaces.append(await space_service.get_space_info(space.id))
        return created_spaces

    @classmethod
    async def sync_department_admin_memberships(
        cls,
        *,
        request: Request | None,
        login_user: UserPayload,
        department_id: int,
        added_user_ids: Sequence[int],
        removed_user_ids: Sequence[int],
    ) -> None:
        bindings = await DepartmentKnowledgeSpaceDao.aget_by_department_ids([department_id])
        space_ids = sorted({int(binding.space_id) for binding in bindings})
        if not space_ids:
            return

        if request is None:
            request = Request(scope={"type": "http"})
        space_service = KnowledgeSpaceService(request=request, login_user=login_user)
        for space_id in space_ids:
            for user_id in sorted(set(int(uid) for uid in added_user_ids)):
                await cls._sync_added_admin(
                    space_service=space_service,
                    space_id=space_id,
                    login_user=login_user,
                    user_id=user_id,
                )

            for user_id in sorted(set(int(uid) for uid in removed_user_ids)):
                await cls._sync_removed_admin(
                    space_service=space_service,
                    space_id=space_id,
                    user_id=user_id,
                )

    @classmethod
    async def get_user_department_spaces(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        order_by: str = "update_time",
    ) -> list[KnowledgeSpaceInfoResp]:
        user_departments = await UserDepartmentDao.aget_user_departments(login_user.user_id)
        department_ids = [
            int(row.department_id) for row in user_departments if getattr(row, "department_id", None) is not None
        ]
        department_bindings = await DepartmentKnowledgeSpaceDao.aget_by_department_ids(department_ids)
        department_space_ids = {int(binding.space_id) for binding in department_bindings}

        members = await SpaceChannelMemberDao.async_get_user_space_members(login_user.user_id)
        member_space_ids = [int(member.business_id) for member in members]
        member_bound_space_ids = set(
            (await DepartmentKnowledgeSpaceDao.aget_department_ids_by_space_ids(member_space_ids)).keys()
        )

        space_ids = department_space_ids | member_bound_space_ids
        if not space_ids:
            return []
        filtered_members = [member for member in members if int(member.business_id) in space_ids]
        svc = KnowledgeSpaceService(request=request, login_user=login_user)
        return await svc._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=filtered_members,
            required_permission_id="view_space",
        )

    @classmethod
    async def get_all_department_spaces(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        order_by: str = "update_time",
    ) -> list[KnowledgeSpaceInfoResp]:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        cls._ensure_super_admin(login_user)
        bindings = await DepartmentKnowledgeSpaceDao.aget_all()
        if not bindings:
            return []

        spaces = await KnowledgeDao.async_get_spaces_by_ids(
            [binding.space_id for binding in bindings],
            order_by=order_by,
        )
        results = [KnowledgeSpaceInfoResp(**space.model_dump()) for space in spaces]
        svc = KnowledgeSpaceService(request=request, login_user=login_user)
        return await svc._decorate_department_metadata(results)

    @classmethod
    async def bind_space_to_department(cls, login_user, *, space_id: int, department_id: int) -> dict:
        cls._ensure_super_admin(login_user)
        team_ids = set(await KnowledgeSpaceScopeDao.aget_space_ids_by_level(KnowledgeSpaceLevelEnum.TEAM))
        if int(space_id) not in team_ids:
            raise SpaceNotFoundError(msg="只能绑定团队知识库")
        if await DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id) is not None:
            raise DepartmentKnowledgeSpaceExistsError(msg="该知识库已绑定部门")
        dept = await DepartmentDao.aget_by_id(department_id)
        if dept is None or getattr(dept, "status", "active") != "active":
            raise DepartmentNotFoundError()
        row = await DepartmentKnowledgeSpaceDao.acreate(
            tenant_id=login_user.tenant_id,
            department_id=department_id,
            space_id=space_id,
            created_by=login_user.user_id,
        )
        # Clinic spaces are stored with level TEAM_KS so they can be distinguished
        # from plain team spaces while still being grouped with them on display.
        await KnowledgeSpaceScopeDao.aupdate_level(space_id, KnowledgeSpaceLevelEnum.TEAM_KS)
        return {"space_id": row.space_id, "department_id": row.department_id}

    @classmethod
    async def rebind_space_to_department(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        space_id: int,
        department_id: int,
    ) -> KnowledgeSpaceInfoResp:
        """Rebind an existing department/clinic knowledge space to another department.

        Verifies the current binding exists, the target department is active and not
        already bound to a different space, then delegates to KnowledgeSpaceService
        so that scope, binding table, and permission tuples are updated consistently.
        """
        cls._ensure_super_admin(login_user)
        current_binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id)
        if current_binding is None:
            raise SpaceNotFoundError(msg="该知识库未绑定部门")

        target_dept = await DepartmentDao.aget_by_id(department_id)
        if target_dept is None or getattr(target_dept, "status", "active") != "active":
            raise DepartmentNotFoundError()

        existing_target = await DepartmentKnowledgeSpaceDao.aget_by_department_id(department_id)
        if existing_target is not None and int(existing_target.space_id) != int(space_id):
            raise DepartmentKnowledgeSpaceExistsError(msg="目标部门已被其他知识库绑定")

        space_service = KnowledgeSpaceService(request=request, login_user=login_user)
        await space_service.update_knowledge_space(
            space_id=space_id,
            department_id=department_id,
        )
        return await space_service.get_space_info(space_id)

    @classmethod
    async def unbind_space(cls, login_user, *, space_id: int) -> None:
        cls._ensure_super_admin(login_user)
        await DepartmentKnowledgeSpaceDao.adelete_by_space_id(space_id)

    @classmethod
    async def list_bindings(cls, login_user) -> list:
        cls._ensure_super_admin(login_user)
        rows = await DepartmentKnowledgeSpaceDao.aget_all()
        if not rows:
            return []
        spaces = await KnowledgeDao.async_get_spaces_by_ids([r.space_id for r in rows])
        name_map = {s.id: s.name for s in spaces}
        dept_map = {d.id: d.name for d in await DepartmentDao.aget_by_ids([r.department_id for r in rows])}
        return [
            {
                "space_id": r.space_id,
                "space_name": name_map.get(r.space_id, ""),
                "department_id": r.department_id,
                "department_name": dept_map.get(r.department_id, ""),
                "created_by": r.created_by,
                "create_time": str(getattr(r, "create_time", "")),
            }
            for r in rows
        ]

    @classmethod
    async def list_bindable_team_spaces(cls, login_user, *, keyword: str | None = None) -> list:
        cls._ensure_super_admin(login_user)
        team_ids = await KnowledgeSpaceScopeDao.aget_space_ids_by_level(KnowledgeSpaceLevelEnum.TEAM)
        if not team_ids:
            return []
        bound = {r.space_id for r in await DepartmentKnowledgeSpaceDao.aget_by_space_ids(team_ids)}
        free_ids = [i for i in team_ids if i not in bound]
        spaces = await KnowledgeDao.async_get_spaces_by_ids(free_ids) if free_ids else []
        result = [{"space_id": s.id, "name": s.name} for s in spaces]
        if keyword:
            kw = keyword.strip().lower()
            result = [x for x in result if kw in (x["name"] or "").lower()]
        return result

    @classmethod
    async def list_departments(cls, login_user) -> list:
        cls._ensure_super_admin(login_user)
        rows = await DepartmentDao.aget_all_active()
        nodes: dict[int, dict] = {}
        parent_ids: dict[int, int | None] = {}
        for department in rows:
            if department.id is None:
                continue
            department_id = int(department.id)
            nodes[department_id] = {
                "id": department_id,
                "name": department.name,
                "children": [],
                "_sort_order": getattr(department, "sort_order", 0),
            }
            parent_ids[department_id] = getattr(department, "parent_id", None)

        roots: list[dict] = []
        for department_id, node in nodes.items():
            parent_id = parent_ids[department_id]
            if parent_id in nodes:
                nodes[parent_id]["children"].append(node)
            else:
                roots.append(node)

        def sort_tree(items: list[dict]) -> None:
            items.sort(key=lambda item: (item["_sort_order"], item["name"], item["id"]))
            for item in items:
                sort_tree(item["children"])
                item.pop("_sort_order", None)

        sort_tree(roots)
        return roots
