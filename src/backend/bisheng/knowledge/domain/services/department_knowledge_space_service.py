from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.department import DepartmentNotFoundError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceExistsError,
    DepartmentSpacePrivateForbiddenError,
    SpaceAdminConflictError,
    SpaceAdminInvalidUserError,
    SpaceAdminRequiredError,
    SpaceNotFoundError,
    SpacePendingAdminError,
)
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    SpaceChannelMemberDao,
    UserRoleEnum,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.tenant import UserTenantDao
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    DepartmentKnowledgeSpaceBatchCreateReq,
    DepartmentKnowledgeSpaceVisibilityReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceInfoResp,
    KnowledgeSpaceService,
)
from bisheng.message.domain.services.notification_content import build_notify_content
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRevokeItem
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.user.domain.models.user import UserDao

_logger = logging.getLogger(__name__)

# Notification action codes (client i18n key: com_notifications_action_<code>).
SPACE_ADMIN_ASSIGNED_MESSAGE = "assigned_knowledge_space_admin"
SPACE_ADMIN_REVOKED_MESSAGE = "revoked_knowledge_space_admin"
# F045: sent to super admins when a department space loses its admin.
SPACE_PENDING_ADMIN_MESSAGE = "pending_knowledge_space_admin"

# F045: membership_source marking the materialized single-space-admin row.
SPACE_ADMIN_MEMBERSHIP_SOURCE = "space_admin"


class DepartmentKnowledgeSpaceService:
    DEFAULT_AUTH_TYPE = AuthTypeEnum.APPROVAL
    # Department knowledge spaces are not published to the square by default;
    # admins can opt in per-space via the edit dialog.
    DEFAULT_IS_RELEASED = False

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
    async def _grant_space_admin_manager(cls, *, space_id: int, user_id: int) -> bool:
        """Write the ``knowledge_space#manager`` tuple for the space admin.

        FGA failure is logged and reported as ``False``: the DB column stays the
        source of truth and the reconcile task repairs the tuple later, so the
        swap itself must not roll back. The boolean lets callers batch the F046
        file-change approver reconciliation into one dispatch per space
        (``dispatch_file_change_approver_reconcile=False`` suppresses the
        per-write dispatch inside ``authorize``).
        """
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
                enforce_fga_success=True,
                dispatch_file_change_approver_reconcile=False,
            )
            return True
        except Exception as e:
            _logger.warning(
                "Failed to write space admin manager tuple for space %s user %s: %s",
                space_id,
                user_id,
                e,
            )
            return False

    @classmethod
    async def _revoke_space_admin_manager(cls, *, space_id: int, user_id: int) -> bool:
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
                enforce_fga_success=True,
                dispatch_file_change_approver_reconcile=False,
            )
            return True
        except Exception as e:
            _logger.warning(
                "Failed to delete space admin manager tuple for space %s user %s: %s",
                space_id,
                user_id,
                e,
            )
            return False

    @classmethod
    async def _validate_admin_candidate(cls, *, user_id: int | None, tenant_id: int) -> int:
        """AC-02: the space admin must be an active user of the current tenant.

        Returns the validated user id. ``None``/0 → SpaceAdminRequiredError
        (AC-01); unknown, deleted/disabled, or out-of-tenant user →
        SpaceAdminInvalidUserError.
        """
        if not user_id:
            raise SpaceAdminRequiredError()
        user = await UserDao.aget_user(int(user_id))
        if user is None or user.delete:
            raise SpaceAdminInvalidUserError()
        if settings.multi_tenant.enabled:
            user_tenant = await UserTenantDao.aget_user_tenant(int(user_id), int(tenant_id))
            if user_tenant is None or user_tenant.is_active != 1:
                raise SpaceAdminInvalidUserError()
        return int(user_id)

    @classmethod
    async def _materialize_space_admin(cls, *, space_id: int, user_id: int) -> None:
        """Materialize the single space admin: ADMIN member row + manager tuple.

        The ``department_knowledge_space.admin_user_id`` column is the source of
        truth; this row/tuple pair only makes the admin visible to the member UI
        and the approval resolver (design decision 2).
        """
        existing = await SpaceChannelMemberDao.async_find_member(space_id, user_id)
        if existing is not None:
            if existing.membership_source != SPACE_ADMIN_MEMBERSHIP_SOURCE:
                # Remember the pre-promotion role so a later replacement can
                # demote back instead of dropping the membership (AC-07).
                existing.department_admin_promoted_from_role = (
                    existing.user_role.value if existing.user_role != UserRoleEnum.ADMIN else None
                )
                existing.membership_source = SPACE_ADMIN_MEMBERSHIP_SOURCE
            existing.user_role = UserRoleEnum.ADMIN
            existing.status = MembershipStatusEnum.ACTIVE
            await SpaceChannelMemberDao.update(existing)
        else:
            member = SpaceChannelMember(
                business_id=str(space_id),
                business_type=BusinessTypeEnum.SPACE,
                user_id=user_id,
                user_role=UserRoleEnum.ADMIN,
                status=MembershipStatusEnum.ACTIVE,
                membership_source=SPACE_ADMIN_MEMBERSHIP_SOURCE,
            )
            await SpaceChannelMemberDao.async_insert_member(member)
        if await cls._grant_space_admin_manager(space_id=space_id, user_id=user_id):
            await cls._reconcile_file_change_approvers(space_id)

    @classmethod
    async def _reconcile_file_change_approvers(cls, space_id: int) -> None:
        """Recompute the F046 file-change approvers after an admin relation write.

        The space admin IS the department space's file-change approver, so every
        materialize/dematerialize must refresh that cache. The per-write dispatch
        inside ``authorize`` is suppressed (``dispatch_file_change_approver_
        reconcile=False``) so one admin swap triggers exactly one reconcile per
        space instead of one per tuple. Best-effort: the periodic beat reconcile
        is the backstop, so a failure here must not break the admin change.
        """
        try:
            from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
                dispatch_file_change_approver_reconcile_for_spaces,
            )

            resource_tenant_id = await PermissionService.resolve_resource_tenant_id(
                "knowledge_space",
                str(space_id),
            )
            await dispatch_file_change_approver_reconcile_for_spaces(
                space_ids=[space_id],
                tenant_id=resource_tenant_id,
            )
        except Exception:
            _logger.exception("F046 approver reconcile dispatch failed for space %s", space_id)

    @classmethod
    async def _dematerialize_space_admin(cls, *, space_id: int, user_id: int) -> None:
        """Clear the space-admin materialization for ``user_id`` (AC-07).

        A member promoted from an ordinary role reverts to it; a pure admin row
        is removed. The manager tuple is revoked either way.
        """
        existing = await SpaceChannelMemberDao.async_find_member(space_id, user_id)
        if existing is not None and existing.membership_source == SPACE_ADMIN_MEMBERSHIP_SOURCE:
            previous_role = existing.department_admin_promoted_from_role
            if previous_role:
                existing.user_role = UserRoleEnum(previous_role)
                existing.membership_source = "manual"
                existing.department_admin_promoted_from_role = None
                existing.status = MembershipStatusEnum.ACTIVE
                await SpaceChannelMemberDao.update(existing)
            else:
                await SpaceChannelMemberDao.delete_space_member(space_id, user_id)
        if await cls._revoke_space_admin_manager(space_id=space_id, user_id=user_id):
            await cls._reconcile_file_change_approvers(space_id)

    @classmethod
    async def _super_admin_user_ids(cls) -> list[int]:
        """Platform super admins (AdminRole users) — notification receivers only.

        Never written into any space relation (AC-10).
        """
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user_role import UserRoleDao

        rows = await UserRoleDao.aget_roles_user([AdminRole])
        return sorted({int(row.user_id) for row in rows})

    @classmethod
    async def _notify(
        cls,
        *,
        sender_user_id: int,
        receiver_user_ids: list[int],
        action_code: str,
        space_id: int,
        navigable: bool = False,
    ) -> None:
        """Best-effort in-app notification; failures never break the main flow."""
        receivers = [uid for uid in receiver_user_ids if uid and uid != sender_user_id]
        if not receivers:
            return
        try:
            from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
            from bisheng.message.api.dependencies import get_message_service as _get_message_service

            space = await KnowledgeDao.aquery_by_id(space_id)
            space_name = space.name if space else str(space_id)
            async with get_async_db_session() as session:
                message_service = await _get_message_service(session)
                await message_service.send_generic_notify(
                    sender=sender_user_id,
                    receiver_user_ids=receivers,
                    content_item_list=build_notify_content(
                        action_code=action_code,
                        target_name=space_name,
                        business_type="knowledge_space_id",
                        business_id=space_id,
                        navigable=navigable,
                    ),
                    action_code=action_code,
                )
        except Exception:
            _logger.exception(
                "Failed to send %s notification for space %s",
                action_code,
                space_id,
            )

    @classmethod
    async def is_space_pending_admin(cls, space_id: int) -> bool:
        """True iff ``space_id`` is a department space currently without an admin."""
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(int(space_id))
        return binding is not None and binding.admin_user_id is None

    @classmethod
    async def ensure_space_not_pending_admin(cls, space_id: int) -> None:
        """AC-09 gate: block admin-gated operations while the space has no admin."""
        if await cls.is_space_pending_admin(space_id):
            raise SpacePendingAdminError()

    @classmethod
    async def replace_admin(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        department_id: int,
        new_admin_user_id: int,
    ) -> KnowledgeSpaceInfoResp:
        """Atomically swap the space admin (AC-05/06, super admin only).

        Order matters: the DB column swap is the atomic commit point; the new
        admin is materialized before the old one is torn down so the member/
        approver surface never passes through a zero-admin state.
        """
        cls._ensure_super_admin(login_user)
        binding = await DepartmentKnowledgeSpaceDao.aget_by_department_id(int(department_id))
        if binding is None:
            raise SpaceNotFoundError()
        new_admin = await cls._validate_admin_candidate(
            user_id=new_admin_user_id,
            tenant_id=login_user.tenant_id,
        )
        space_service = KnowledgeSpaceService(request=request, login_user=login_user)
        previous_admin = binding.admin_user_id
        if previous_admin == new_admin:
            await cls._materialize_space_admin(space_id=binding.space_id, user_id=new_admin)
            return await space_service.get_space_info(binding.space_id)

        swapped = await DepartmentKnowledgeSpaceDao.areplace_admin(
            row_id=binding.id,
            expected_admin_user_id=previous_admin,
            new_admin_user_id=new_admin,
        )
        if not swapped:
            # A concurrent replacement won the conditional UPDATE; the caller
            # retries against the fresh state (AC-06: no interleaved result).
            raise SpaceAdminConflictError()

        await cls._materialize_space_admin(space_id=binding.space_id, user_id=new_admin)
        if previous_admin:
            await cls._dematerialize_space_admin(space_id=binding.space_id, user_id=previous_admin)
            await cls._notify(
                sender_user_id=login_user.user_id,
                receiver_user_ids=[previous_admin],
                action_code=SPACE_ADMIN_REVOKED_MESSAGE,
                space_id=binding.space_id,
            )
        await cls._notify(
            sender_user_id=login_user.user_id,
            receiver_user_ids=[new_admin],
            action_code=SPACE_ADMIN_ASSIGNED_MESSAGE,
            space_id=binding.space_id,
            navigable=True,
        )
        return await space_service.get_space_info(binding.space_id)

    @classmethod
    async def handle_admin_invalidated(
        cls,
        user_id: int,
        *,
        operator_user_id: int | None = None,
        except_tenant_id: int | None = None,
    ) -> int:
        """AC-08: the admin account was deactivated / deleted / moved out.

        Marks every department space administered by ``user_id`` as pending
        admin configuration (column → NULL), tears down the materialization and
        notifies the super admins. Never auto-promotes anyone (AC-10). Returns
        the number of spaces flipped to pending.

        ``except_tenant_id`` serves the tenant-relocation entry: spaces in the
        tenant the user *moved into* keep their admin; everything else flips.
        The enumeration bypasses the tenant filter (relocation/SSO callers run
        outside the affected tenant's context) and each row is processed under
        its own tenant context, mirroring the Celery-Beat multi-tenant pattern.
        """
        with bypass_tenant_filter():
            rows = await DepartmentKnowledgeSpaceDao.aget_by_admin_user_id(int(user_id))
        if except_tenant_id is not None:
            rows = [row for row in rows if int(row.tenant_id or 0) != int(except_tenant_id)]
        if not rows:
            return 0
        super_admin_ids = await cls._super_admin_user_ids()
        flipped = 0
        for row in rows:
            previous_tenant = get_current_tenant_id()
            if row.tenant_id and row.tenant_id != previous_tenant:
                set_current_tenant_id(int(row.tenant_id))
            try:
                swapped = await DepartmentKnowledgeSpaceDao.areplace_admin(
                    row_id=row.id,
                    expected_admin_user_id=int(user_id),
                    new_admin_user_id=None,
                )
                if not swapped:
                    continue  # a super admin already re-assigned this space concurrently
                await cls._dematerialize_space_admin(space_id=row.space_id, user_id=int(user_id))
                await cls._notify(
                    sender_user_id=operator_user_id or int(user_id),
                    receiver_user_ids=super_admin_ids,
                    action_code=SPACE_PENDING_ADMIN_MESSAGE,
                    space_id=row.space_id,
                )
                flipped += 1
            finally:
                if previous_tenant is not None and row.tenant_id and row.tenant_id != previous_tenant:
                    set_current_tenant_id(previous_tenant)
        if flipped:
            _logger.info(
                "Marked %s department knowledge space(s) pending admin after user %s invalidation",
                flipped,
                user_id,
            )
        return flipped

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
                        include_children=False,
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
        if any(item.auth_type == AuthTypeEnum.PRIVATE for item in req.items):
            raise DepartmentSpacePrivateForbiddenError()
        dept_ids = [int(item.department_id) for item in req.items]
        if len(set(dept_ids)) != len(dept_ids):
            raise DepartmentKnowledgeSpaceExistsError(
                msg=f"Department ids are duplicated in request: {sorted(dept_ids)}"
            )

        dept_map = await cls._load_departments(dept_ids)
        existing = await DepartmentKnowledgeSpaceDao.aget_by_department_ids(list(dept_map.keys()))
        if existing:
            raise DepartmentKnowledgeSpaceExistsError(
                msg=f"Department knowledge space already exists: {sorted({row.department_id for row in existing})}"
            )

        # AC-01/02: validate every space admin up front — the whole batch is
        # rejected before any space is created, so a bad item cannot leave a
        # partially-created batch behind.
        admin_by_dept: dict[int, int] = {}
        for item in req.items:
            admin_by_dept[int(item.department_id)] = await cls._validate_admin_candidate(
                user_id=item.admin_user_id,
                tenant_id=login_user.tenant_id,
            )

        space_service = KnowledgeSpaceService(request=request, login_user=login_user)
        created_spaces: list[KnowledgeSpaceInfoResp] = []
        for item in req.items:
            dept = dept_map[int(item.department_id)]
            admin_user_id = admin_by_dept[int(item.department_id)]
            # AC-04: the creating super admin leaves no front-facing footprint —
            # no CREATOR member row, no owner tuple. Knowledge.user_id and
            # DepartmentKnowledgeSpace.created_by keep the audit trail only.
            space = await space_service.create_knowledge_space(
                name=item.name or cls._build_default_name(dept.name),
                description=item.description or cls._build_default_description(dept.name),
                icon=item.icon,
                auth_type=item.auth_type or cls.DEFAULT_AUTH_TYPE,
                is_released=cls.DEFAULT_IS_RELEASED if item.is_released is None else item.is_released,
                skip_user_limit=True,
                materialize_creator=False,
            )
            await DepartmentKnowledgeSpaceDao.acreate(
                tenant_id=login_user.tenant_id,
                department_id=dept.id,
                space_id=space.id,
                created_by=login_user.user_id,
                admin_user_id=admin_user_id,
            )
            await cls._grant_department_members_viewer(
                space_id=space.id,
                department_id=dept.id,
            )
            await cls._materialize_space_admin(space_id=space.id, user_id=admin_user_id)
            await cls._notify(
                sender_user_id=login_user.user_id,
                receiver_user_ids=[admin_user_id],
                action_code=SPACE_ADMIN_ASSIGNED_MESSAGE,
                space_id=space.id,
                navigable=True,
            )
            created_spaces.append(await space_service.get_space_info(space.id))
        return created_spaces

    @classmethod
    async def get_user_department_spaces(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        order_by: str = "update_time",
    ) -> list[KnowledgeSpaceInfoResp]:
        is_admin = login_user.is_admin()
        members = await SpaceChannelMemberDao.async_get_user_space_members(login_user.user_id)

        if is_admin:
            # Super admin sees every department knowledge space, not only the
            # ones bound to their own departments. The view_space pre-filter is
            # disabled below because admin passes every gate; keeping it would
            # wrongly drop spaces the admin has no explicit binding to.
            all_bindings = await DepartmentKnowledgeSpaceDao.aget_all()
            space_ids = {int(binding.space_id) for binding in all_bindings}
        else:
            user_departments = await UserDepartmentDao.aget_user_departments(login_user.user_id)
            department_ids = [
                int(row.department_id) for row in user_departments if getattr(row, "department_id", None) is not None
            ]
            department_bindings = await DepartmentKnowledgeSpaceDao.aget_by_department_ids(department_ids)
            department_space_ids = {int(binding.space_id) for binding in department_bindings}

            member_space_ids = [int(member.business_id) for member in members]
            member_bound_space_ids = set(
                (await DepartmentKnowledgeSpaceDao.aget_department_ids_by_space_ids(member_space_ids)).keys()
            )

            # A user can also gain access to a department space through an ad-hoc
            # authorization (viewer/editor/manager granted on the permission panel).
            # That path writes only an FGA relation — no membership row, and the
            # user need not be a member of the bound department — so neither branch
            # above catches it and the space would only surface under "我加入的".
            # Intersect the user's FGA-readable spaces with the department-bound set
            # so an individually-authorized user sees it under 部门知识空间 instead.
            accessible_ids = await PermissionService.list_accessible_ids(
                user_id=login_user.user_id,
                relation="can_read",
                object_type="knowledge_space",
                login_user=login_user,
            )
            authorized_bound_space_ids: set[int] = set()
            if accessible_ids:
                accessible_int_ids = [int(sid) for sid in accessible_ids if str(sid).isdigit()]
                if accessible_int_ids:
                    authorized_bound_space_ids = set(
                        (await DepartmentKnowledgeSpaceDao.aget_department_ids_by_space_ids(accessible_int_ids)).keys()
                    )

            space_ids = department_space_ids | member_bound_space_ids | authorized_bound_space_ids

        if not space_ids:
            return []
        filtered_members = [member for member in members if int(member.business_id) in space_ids]
        svc = KnowledgeSpaceService(request=request, login_user=login_user)
        return await svc._format_accessible_spaces(
            list(space_ids),
            order_by,
            memberships=filtered_members,
            required_permission_id=None if is_admin else "view_space",
        )

    @classmethod
    async def get_all_department_spaces(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        order_by: str = "update_time",
        include_hidden: bool = False,
    ) -> list[KnowledgeSpaceInfoResp]:
        """Return every department knowledge space for the management surface.

        ``include_hidden`` is False for the "已创建知识空间" list (hidden spaces
        are dropped) and True for the management dialog (which needs the hidden
        ones so they can be restored).
        """
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        cls._ensure_super_admin(login_user)
        bindings = await DepartmentKnowledgeSpaceDao.aget_all()
        if not include_hidden:
            bindings = [binding for binding in bindings if not binding.is_hidden]
        if not bindings:
            return []

        spaces = await KnowledgeDao.async_get_spaces_by_ids(
            [binding.space_id for binding in bindings],
            order_by=order_by,
        )
        results = [KnowledgeSpaceInfoResp(**space.model_dump()) for space in spaces]
        svc = KnowledgeSpaceService(request=request, login_user=login_user)
        await svc._populate_root_file_counts(results)
        return await svc._decorate_department_metadata(results)

    @classmethod
    async def set_spaces_hidden(
        cls,
        *,
        login_user: UserPayload,
        req: DepartmentKnowledgeSpaceVisibilityReq,
    ) -> int:
        """Hide or restore department knowledge spaces (super admin only).

        Only flips the ``is_hidden`` flag on the binding rows. The knowledge
        spaces, their files and member permissions (OpenFGA tuples / space
        members) are intentionally left untouched, so hiding is fully
        reversible. Returns the number of rows whose state actually changed.
        """
        cls._ensure_super_admin(login_user)
        department_ids = [int(dept_id) for dept_id in req.department_ids]
        if not department_ids:
            return 0
        return await DepartmentKnowledgeSpaceDao.aset_hidden_by_department_ids(
            department_ids,
            req.is_hidden,
        )
