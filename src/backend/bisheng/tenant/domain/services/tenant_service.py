"""TenantService — core business logic for tenant management.

Part of F010-tenant-management-ui.
"""

import logging

from bisheng.common.errcode.tenant import (
    TenantAdminRequiredError,
    TenantCodeDuplicateError,
    TenantCreationFailedError,
    TenantDisabledError,
    TenantHasUsersError,
    TenantNotFoundError,
    TenantSwitchForbiddenError,
)
from bisheng.common.errcode.tenant_tree import (
    TenantArchivedNotResumableError,
    TenantTreeRootProtectedError,
)
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import UserDepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant, TenantDao, UserTenantDao
from bisheng.tenant.domain.constants import TenantAuditAction
from bisheng.tenant.domain.schemas.tenant_schema import (
    TenantCreate,
    TenantDetail,
    TenantListItem,
    TenantQuotaResponse,
    TenantQuotaTreeNode,
    TenantQuotaTreeResponse,
    TenantQuotaUpdate,
    TenantQuotaUsageItem,
    TenantStatusUpdate,
    TenantUpdate,
    TenantUserAdd,
    UserTenantItem,
)

logger = logging.getLogger(__name__)

DISABLED_TENANT_KEY = "disabled_tenant:{}"


def _get_storage_quota(tenant: Tenant) -> float | None:
    """Extract storage_gb from quota_config if present."""
    if tenant.quota_config and "storage_gb" in tenant.quota_config:
        return tenant.quota_config["storage_gb"]
    return None


def _guard_default_tenant(tenant_id: int) -> None:
    """INV-T11: Root tenant is system-protected (disable/archive/delete → 22008)."""
    if tenant_id == ROOT_TENANT_ID:
        raise TenantTreeRootProtectedError()


# Fields safe to include in API responses (excludes create_user, storage_config internals)
_TENANT_RESPONSE_FIELDS = {
    "id",
    "tenant_code",
    "tenant_name",
    "logo",
    "status",
    "root_dept_id",
    "contact_name",
    "contact_phone",
    "contact_email",
    "quota_config",
    "create_time",
    "update_time",
}


def _safe_tenant_dump(tenant: Tenant) -> dict:
    """Serialize tenant with only API-safe fields."""
    return tenant.model_dump(include=_TENANT_RESPONSE_FIELDS)


class TenantService:
    """Stateless service for tenant lifecycle management."""

    # ── Tenant CRUD ────────────────────────────────────────────

    @classmethod
    async def acreate_tenant(cls, data: TenantCreate, login_user) -> dict:
        """Create a tenant atomically with its root department and permissions (INV-14)."""
        # Check tenant_code uniqueness
        with bypass_tenant_filter():
            existing = await TenantDao.aget_by_code(data.tenant_code)
        if existing:
            raise TenantCodeDuplicateError()

        try:
            # Step 1: Create Tenant record
            tenant = Tenant(
                tenant_name=data.tenant_name,
                tenant_code=data.tenant_code,
                logo=data.logo,
                contact_name=data.contact_name,
                contact_phone=data.contact_phone,
                contact_email=data.contact_email,
                quota_config=data.quota_config,
                create_user=login_user.user_id,
            )
            with bypass_tenant_filter():
                tenant = await TenantDao.acreate_tenant(tenant)

            # Step 2: Create root department
            from bisheng.department.domain.services.department_service import DepartmentService

            await DepartmentService.acreate_root_department(
                tenant_id=tenant.id,
                name=data.tenant_name,
            )

            # Step 3: Create UserTenant for each admin
            for uid in data.admin_user_ids:
                await UserTenantDao.aadd_user_to_tenant(
                    user_id=uid,
                    tenant_id=tenant.id,
                    is_default=0,
                )

            # Step 4: apply tenant permissions after DB commit.
            await cls._apply_tenant_permissions(
                tenant_id=tenant.id,
                admin_user_ids=data.admin_user_ids,
                action="grant",
            )

            # Step 5: Child/root tenant bootstrap — copy builtin tools so
            # workstation config inheritance can remap by tool_key.
            from bisheng.workstation.domain.services import WorkStationService

            await WorkStationService.acopy_root_builtin_tools_to_tenant(tenant.id)

            # Step 6: seed the kernel's built-in Linsight skills. Startup seeding
            # only covers tenants that existed then, so without this a tenant
            # created later would never get them. Best-effort: a skill is not
            # worth failing tenant creation over, and the next restart re-seeds.
            try:
                from bisheng.linsight.domain.services.builtin_skill_seeder import seed_builtin_skills

                await seed_builtin_skills([tenant.id])
            except Exception:
                logger.warning("built-in skill seeding failed for new tenant %s", tenant.id, exc_info=True)

            return _safe_tenant_dump(tenant)

        except TenantCodeDuplicateError:
            raise
        except Exception as e:
            logger.error("Tenant creation failed: %s", e, exc_info=True)
            raise TenantCreationFailedError()

    @classmethod
    async def alist_tenants(
        cls,
        keyword: str | None,
        status: str | None,
        page: int,
        page_size: int,
        login_user,
    ) -> dict:
        """List tenants with pagination. System admin only."""
        import asyncio

        from bisheng.role.domain.services.quota_service import QuotaService

        tenants, total = await TenantDao.alist_tenants(
            keyword=keyword,
            status=status,
            page=page,
            page_size=page_size,
        )
        # F024 phase-2: count via primary-dept-in-subtree so the column
        # matches the dialog list source exactly. v2.5.0 ``aadd_users``
        # residue rows in UserTenant no longer surface as phantom members.
        tenant_ids = [t.id for t in tenants]
        user_counts, usage_map = await asyncio.gather(
            UserDepartmentDao.acount_users_by_tenant_subtree_batch(tenant_ids),
            QuotaService.get_storage_used_gb_batch(tenant_ids),
        )

        # Strip the ``#archived#<ts>`` suffix injected by ``unmount_child`` so
        # operators see the original code in the tenant list. The stored value
        # only carries the suffix to keep the UNIQUE index on tenant_code free
        # for a remount under the same code (see ``archived_tenant_code``).
        from bisheng.tenant.domain.services.tenant_mount_service import (
            display_tenant_code,
        )

        items = []
        for t in tenants:
            items.append(
                TenantListItem(
                    id=t.id,
                    tenant_name=t.tenant_name,
                    tenant_code=display_tenant_code(t.tenant_code),
                    logo=t.logo,
                    status=t.status,
                    user_count=user_counts.get(t.id, 0),
                    storage_used_gb=round(usage_map.get(t.id, 0.0), 2),
                    storage_quota_gb=_get_storage_quota(t),
                    create_time=t.create_time,
                )
            )
        return {"data": [item.model_dump() for item in items], "total": total}

    @classmethod
    async def aget_tenant(cls, tenant_id: int, login_user) -> dict:
        """Get tenant detail including admin users."""
        from bisheng.role.domain.services.quota_service import QuotaService

        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        user_count = await UserDepartmentDao.acount_users_by_tenant_subtree(tenant_id)
        admin_users = await cls._get_tenant_admin_users(tenant_id)
        usage_map = await QuotaService.get_storage_used_gb_batch([tenant_id])

        from bisheng.tenant.domain.services.tenant_mount_service import (
            display_tenant_code,
        )

        detail = TenantDetail(
            id=tenant.id,
            tenant_name=tenant.tenant_name,
            tenant_code=display_tenant_code(tenant.tenant_code),
            logo=tenant.logo,
            status=tenant.status,
            user_count=user_count,
            storage_used_gb=round(usage_map.get(tenant_id, 0.0), 2),
            storage_quota_gb=_get_storage_quota(tenant),
            create_time=tenant.create_time,
            root_dept_id=tenant.root_dept_id,
            contact_name=tenant.contact_name,
            contact_phone=tenant.contact_phone,
            contact_email=tenant.contact_email,
            quota_config=tenant.quota_config,
            storage_config=tenant.storage_config,
            admin_users=admin_users,
        )
        return detail.model_dump()

    @classmethod
    async def aupdate_tenant(cls, tenant_id: int, data: TenantUpdate, login_user) -> dict:
        """Update tenant info (name/logo/contact). tenant_code is immutable."""
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            with bypass_tenant_filter():
                tenant = await TenantDao.aget_by_id(tenant_id)
            if not tenant:
                raise TenantNotFoundError()
            return _safe_tenant_dump(tenant)

        tenant = await TenantDao.aupdate_tenant(tenant_id, **fields)
        if not tenant:
            raise TenantNotFoundError()
        return _safe_tenant_dump(tenant)

    @classmethod
    async def aupdate_tenant_status(
        cls,
        tenant_id: int,
        data: TenantStatusUpdate,
        login_user,
    ) -> dict:
        """Update tenant status and manage Redis blacklist.

        On a transition into ``disabled`` we additionally revoke active JWTs
        for every user whose active leaf is this tenant (PRD §5.1.3 step 1)
        so the frontend hits a 401 and redirects to login instead of just
        silently 403-ing every request.
        """
        _guard_default_tenant(tenant_id)

        with bypass_tenant_filter():
            prior = await TenantDao.aget_by_id(tenant_id)
        if not prior:
            raise TenantNotFoundError()
        # ``archived`` is terminal — see TenantArchivedNotResumableError.
        # Without this guard, the frontend's "enable" button silently brings
        # an unmounted tenant back to ``active`` with no mount point.
        if prior.status == "archived" and data.status != "archived":
            raise TenantArchivedNotResumableError()
        became_disabled = prior.status != "disabled" and data.status == "disabled"

        tenant = await TenantDao.aupdate_tenant(tenant_id, status=data.status)
        if not tenant:
            raise TenantNotFoundError()

        redis_client = await get_redis_client()
        key = DISABLED_TENANT_KEY.format(tenant_id)
        if data.status in ("disabled", "archived"):
            await redis_client.aset(key, "1", expiration=0)
        else:
            await redis_client.adelete(key)

        if became_disabled:
            await cls._revoke_active_jwts_for_tenant(
                tenant_id,
                operator_id=getattr(login_user, "user_id", 0),
            )

        return _safe_tenant_dump(tenant)

    @classmethod
    async def _revoke_active_jwts_for_tenant(
        cls,
        tenant_id: int,
        operator_id: int,
    ) -> None:
        """PRD §5.1.3 step 1: bump token_version for every active leaf user."""
        from bisheng.user.domain.services.user import UserService

        user_ids = await UserTenantDao.aget_active_user_ids_by_tenant(tenant_id)
        for uid in user_ids:
            try:
                await UserService.ainvalidate_jwt_after_account_disabled(uid)
            except Exception as exc:
                logger.warning(
                    "JWT revoke failed user_id=%s tenant_id=%s: %s",
                    uid,
                    tenant_id,
                    exc,
                )

        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=operator_id,
                operator_tenant_id=ROOT_TENANT_ID,
                action=TenantAuditAction.DISABLE.value,
                target_type="tenant",
                target_id=str(tenant_id),
                metadata={
                    "revoked_user_ids": user_ids,
                    "revoked_count": len(user_ids),
                    "jwt_revoke": True,
                },
            )
        except Exception as exc:
            logger.warning(
                "audit log failed for tenant.disable tenant_id=%s: %s",
                tenant_id,
                exc,
            )

    @classmethod
    async def adelete_tenant(cls, tenant_id: int, login_user) -> None:
        """Delete a tenant. Requires zero active users."""
        _guard_default_tenant(tenant_id)
        # F024 phase-2: gate the delete on the same "primary dept in subtree"
        # source the UI shows, so admins are never blocked by phantom
        # UserTenant residue rows they cannot see.
        user_count = await UserDepartmentDao.acount_users_by_tenant_subtree(tenant_id)
        if user_count > 0:
            raise TenantHasUsersError()

        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        # Cleanup: UserTenant records (may have inactive ones)
        await UserTenantDao.adelete_by_tenant(tenant_id)

        # Cleanup: root department
        try:
            from bisheng.database.models.department import DepartmentDao

            await DepartmentDao.adelete_by_tenant(tenant_id)
        except Exception as e:
            logger.warning("Failed to delete departments for tenant %d: %s", tenant_id, e)

        # Cleanup: Redis blacklist key
        redis_client = await get_redis_client()
        await redis_client.adelete(DISABLED_TENANT_KEY.format(tenant_id))

        # Cleanup tenant permissions (best effort).
        try:
            await cls._apply_tenant_permissions(
                tenant_id=tenant_id,
                admin_user_ids=[],
                action="revoke_all",
            )
        except Exception as e:
            logger.warning("Failed to revoke permissions for tenant %d: %s", tenant_id, e)

        # Delete tenant record
        await TenantDao.adelete_tenant(tenant_id)

    # ── Quota ──────────────────────────────────────────────────

    @classmethod
    async def aget_quota(cls, tenant_id: int, login_user) -> dict:
        """Get tenant quota config and usage."""
        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        usage = {}
        user_count = await UserDepartmentDao.acount_users_by_tenant_subtree(tenant_id)
        usage["user_count"] = user_count

        return TenantQuotaResponse(
            quota_config=tenant.quota_config,
            usage=usage,
        ).model_dump()

    @classmethod
    async def aset_quota(cls, tenant_id: int, data: TenantQuotaUpdate, login_user) -> dict:
        """Set tenant quota config.

        Validates ``quota_config`` keys/values via
        ``QuotaService.validate_quota_config`` before persisting so unknown
        resource types and malformed values are rejected with
        ``QuotaConfigInvalidError(24005)`` (F010 AC-4.2 / F016 AC-03 fix —
        the endpoint previously accepted any JSON payload unchecked).
        """
        from bisheng.role.domain.services.quota_service import QuotaService

        QuotaService.validate_quota_config(data.quota_config)

        tenant = await TenantDao.aupdate_tenant(tenant_id, quota_config=data.quota_config)
        if not tenant:
            raise TenantNotFoundError()
        return _safe_tenant_dump(tenant)

    # F016 AC-06: tenant quota tree (global super admin only).

    @classmethod
    async def aget_quota_tree(cls, login_user) -> TenantQuotaTreeResponse:
        """Build the full Tenant quota tree (Root + all active Children).

        Root usage is aggregated (Root self + Σ active Child, INV-T9) so the
        group-wide ceiling is visible; Child usage is strict-equality (INV-T6)
        so shared Root resources don't double-count.

        Only exposed to global super admin per AC-06; Child Admins continue
        using the scalar `GET /tenants/{id}/quota` endpoint to avoid cross-
        Child visibility leaks.
        """
        from bisheng.role.domain.services.quota_service import (
            VALID_QUOTA_KEYS,
            QuotaService,
        )

        with bypass_tenant_filter():
            root = await TenantDao.aget_by_id(ROOT_TENANT_ID)
            if not root:
                raise TenantNotFoundError()
            child_ids = await TenantDao.aget_children_ids_active(ROOT_TENANT_ID)
            children = [await TenantDao.aget_by_id(cid) for cid in child_ids]

        sorted_keys = sorted(VALID_QUOTA_KEYS)

        async def _build_usage(tid: int, is_root: bool, config: dict) -> list[TenantQuotaUsageItem]:
            items: list[TenantQuotaUsageItem] = []
            for rt in sorted_keys:
                limit = (config or {}).get(rt, -1)
                used = (
                    await QuotaService._aggregate_root_usage(tid, rt)
                    if is_root
                    else await QuotaService._count_usage_strict(tid, rt)
                )
                if limit == -1:
                    utilization = 0.0  # front-end renders as "unlimited"
                elif limit == 0:
                    utilization = 1.0 if used > 0 else 0.0
                else:
                    utilization = used / limit
                items.append(
                    TenantQuotaUsageItem(
                        resource_type=rt,
                        used=used,
                        limit=limit,
                        utilization=utilization,
                    )
                )
            return items

        root_node = TenantQuotaTreeNode(
            tenant_id=root.id,
            tenant_name=root.tenant_name,
            parent_tenant_id=root.parent_tenant_id,
            quota_config=root.quota_config or {},
            usage=await _build_usage(root.id, is_root=True, config=root.quota_config or {}),
        )

        child_nodes: list[TenantQuotaTreeNode] = []
        for c in children:
            if c is None:
                continue
            child_nodes.append(
                TenantQuotaTreeNode(
                    tenant_id=c.id,
                    tenant_name=c.tenant_name,
                    parent_tenant_id=c.parent_tenant_id,
                    quota_config=c.quota_config or {},
                    usage=await _build_usage(c.id, is_root=False, config=c.quota_config or {}),
                )
            )

        return TenantQuotaTreeResponse(root=root_node, children=child_nodes)

    # ── Tenant Users ───────────────────────────────────────────

    @classmethod
    async def aadd_users(cls, tenant_id: int, data: TenantUserAdd, login_user) -> dict:
        """**DEPRECATED in v2.5.1 (F024)**: tenant membership is derived from
        the user's primary department. The public ``POST /tenants/{id}/users``
        endpoint returns 410 Gone; this implementation is retained only for
        internal scripts that need to write passive ``UserTenant`` rows
        during migration. Will be removed in v2.6.0."""
        import warnings

        warnings.warn(
            "TenantService.aadd_users is deprecated since v2.5.1 (F024); "
            "change the user's primary department to alter tenant membership.",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "F024 deprecated: TenantService.aadd_users called for tenant_id=%d "
            "with %d uids; this path bypasses leaf-tenant derivation and will "
            "be removed in v2.6.0",
            tenant_id,
            len(data.user_ids or []),
        )
        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        added = []
        for uid in data.user_ids:
            existing = await UserTenantDao.aget_user_tenant(uid, tenant_id)
            if existing:
                continue
            await UserTenantDao.aadd_user_to_tenant(user_id=uid, tenant_id=tenant_id)
            added.append(uid)

        # Grant member and optional admin permissions.
        if added:
            await cls._apply_user_permissions(
                tenant_id=tenant_id,
                user_ids=added,
                is_admin=data.is_admin,
                action="grant",
            )

        return {"added": len(added), "skipped": len(data.user_ids) - len(added)}

    @classmethod
    async def aremove_user(cls, tenant_id: int, user_id: int, login_user) -> None:
        """**DEPRECATED in v2.5.1 (F024)**: see ``aadd_users``. Public
        ``DELETE /tenants/{id}/users/{user_id}`` endpoint returns 410 Gone;
        this implementation retained for internal use only."""
        import warnings

        warnings.warn(
            "TenantService.aremove_user is deprecated since v2.5.1 (F024); "
            "change the user's primary department to alter tenant membership.",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "F024 deprecated: TenantService.aremove_user called for "
            "tenant_id=%d user_id=%d; this path bypasses leaf-tenant "
            "derivation and will be removed in v2.6.0",
            tenant_id,
            user_id,
        )
        ut = await UserTenantDao.aget_user_tenant(user_id, tenant_id)
        if not ut:
            return

        # Check if user is admin — if so, ensure at least one admin remains
        is_admin = await cls._is_tenant_admin(user_id, tenant_id)
        if is_admin:
            admin_count = await cls._count_tenant_admins(tenant_id)
            if admin_count <= 1:
                raise TenantAdminRequiredError()

        # Remove UserTenant record
        await UserTenantDao.aremove_user_from_tenant(user_id, tenant_id)

        # Revoke user permissions.
        await cls._apply_user_permissions(
            tenant_id=tenant_id,
            user_ids=[user_id],
            is_admin=is_admin,
            action="revoke",
        )

    @classmethod
    async def aget_tenant_users(
        cls,
        tenant_id: int,
        page: int,
        page_size: int,
        keyword: str | None,
        login_user,
    ) -> dict:
        """Get paginated users in a tenant.

        F024: data source switched from ``UserTenantDao.aget_tenant_users``
        (queries UserTenant rows) to ``UserDepartmentDao.aget_users_by_tenant_subtree``
        (queries primary-dept-in-tenant-subtree). Aligns with
        ``TenantResolver`` so v2.5.0 ``aadd_users`` residue rows do not
        surface as phantom members. Return shape unchanged.
        """
        from bisheng.database.models.department import UserDepartmentDao

        users, total = await UserDepartmentDao.aget_users_by_tenant_subtree(
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
            keyword=keyword,
        )
        return {"data": users, "total": total}

    # ── User-facing: tenant selection & switching ──────────────

    @classmethod
    async def aget_user_tenants(cls, user_id: int) -> list[dict]:
        """Get all tenants for a user (for tenant selection / switching)."""
        details = await UserTenantDao.aget_user_tenants_with_details(user_id)
        items = [UserTenantItem(**d).model_dump() for d in details if d.get("status") == "active"]
        return items

    @classmethod
    async def aswitch_tenant(cls, user_id: int, tenant_id: int, db_user, auth_jwt) -> str:
        """Switch user to a different tenant. Returns new access token."""
        # Validate membership
        ut = await UserTenantDao.aget_user_tenant(user_id, tenant_id)
        if not ut or ut.status != "active":
            raise TenantSwitchForbiddenError()

        # Validate tenant status
        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        if tenant.status != "active":
            raise TenantDisabledError()

        # Update last access time
        await UserTenantDao.aupdate_last_access_time(user_id, tenant_id)

        from bisheng.common.errcode.user import UserNoRoleForLoginError, UserNoWebMenuForLoginError
        from bisheng.user.domain.services.user import UserService

        guard = await UserService._reject_login_if_user_has_no_usable_access(db_user)
        if guard is not None:
            if guard.status_code == UserNoRoleForLoginError.Code:
                raise UserNoRoleForLoginError()
            raise UserNoWebMenuForLoginError()

        # Create new JWT with target tenant_id
        from bisheng.user.domain.services.auth import LoginUser

        access_token = LoginUser.create_access_token(
            user=db_user,
            auth_jwt=auth_jwt,
            tenant_id=tenant_id,
        )
        LoginUser.set_access_cookies(access_token, auth_jwt=auth_jwt)

        # Update Redis session
        redis_client = await get_redis_client()
        from bisheng.user.domain.services.user import USER_CURRENT_SESSION

        await redis_client.aset(
            USER_CURRENT_SESSION.format(user_id),
            access_token,
            expiration=auth_jwt.cookie_conf.jwt_token_expire_time + 3600,
        )

        return access_token

    # ── Private helpers ────────────────────────────────────────

    @classmethod
    async def _apply_tenant_permissions(
        cls,
        tenant_id: int,
        admin_user_ids: list[int],
        action: str,
    ) -> None:
        """Grant or revoke tenant identity permissions."""
        try:
            from bisheng.permission.application import (
                PermissionObject,
                PermissionRelation,
                PermissionRelationChange,
                PermissionSubject,
                get_permission_relation_api,
            )

            if action == "grant":
                resource = PermissionObject("tenant", str(tenant_id))
                changes = tuple(
                    PermissionRelationChange(
                        action="grant",
                        relation=PermissionRelation(
                            subject=PermissionSubject("user", str(uid)),
                            relation=relation,
                            resource=resource,
                        ),
                    )
                    for uid in admin_user_ids
                    for relation in ("admin", "member")
                )
                permissions = await get_permission_relation_api()
                await permissions.apply_changes(changes, crash_safe=True)
            elif action == "revoke_all":
                logger.info("Skipping permission cleanup for deleted tenant %d", tenant_id)

        except Exception as e:
            logger.error("Permission update failed for tenant %d: %s", tenant_id, e)

    @classmethod
    async def _apply_user_permissions(
        cls,
        tenant_id: int,
        user_ids: list[int],
        is_admin: bool,
        action: str,
    ) -> None:
        """Apply user membership and admin permission changes."""
        try:
            from bisheng.permission.application import (
                PermissionObject,
                PermissionRelation,
                PermissionRelationChange,
                PermissionSubject,
                get_permission_relation_api,
            )

            change_action = "grant" if action == "grant" else "revoke"
            resource = PermissionObject("tenant", str(tenant_id))
            relations = ("member", "admin") if is_admin else ("member",)
            changes = tuple(
                PermissionRelationChange(
                    action=change_action,
                    relation=PermissionRelation(
                        subject=PermissionSubject("user", str(uid)),
                        relation=relation,
                        resource=resource,
                    ),
                )
                for uid in user_ids
                for relation in relations
            )
            permissions = await get_permission_relation_api()
            await permissions.apply_changes(changes, crash_safe=True)

        except Exception as e:
            logger.error("User permission update failed for tenant %d: %s", tenant_id, e)

    @classmethod
    async def _get_tenant_admin_users(cls, tenant_id: int) -> list[dict]:
        """Get admin users for a tenant through one permission batch check.

        Sequential per-user permission checks (the pre-fix shape)
        hung the edit-tenant dialog on Root: each check went through the
        full permission pipeline (~2.5–3s) and 100 UserTenant rows pushed
        the response past the 120s frontend timeout. batch_check folds
        them into one permission round-trip while preserving the semantic — the
        authorization model still resolves super_admin → admin, so Root
        super_admins continue to surface as Root admins.
        """
        users, _ = await UserTenantDao.aget_tenant_users(tenant_id, page=1, page_size=100)
        if not users:
            return []
        flags = await cls._batch_check_tenant_admin(
            [u["user_id"] for u in users],
            tenant_id,
        )
        return [u for u, ok in zip(users, flags) if ok]

    @classmethod
    async def _is_tenant_admin(cls, user_id: int, tenant_id: int) -> bool:
        """Check whether a user is a tenant administrator."""
        try:
            from bisheng.permission.application import (
                PermissionObject,
                PermissionSubject,
                get_permission_relation_api,
            )

            permissions = await get_permission_relation_api()
            return await permissions.check(
                subject=PermissionSubject("user", str(user_id)),
                relation="admin",
                resource=PermissionObject("tenant", str(tenant_id)),
            )
        except Exception:
            return False

    @classmethod
    async def _batch_check_tenant_admin(
        cls,
        user_ids: list[int],
        tenant_id: int,
    ) -> list[bool]:
        """Resolve admin flags through the permission application in one batch.

        Returns a list aligned with ``user_ids``. On any permission service
        failure returns all-False so callers can
        apply their own fail-closed policy.
        """
        if not user_ids:
            return []
        try:
            from bisheng.permission.application import (
                PermissionObject,
                PermissionRelation,
                PermissionSubject,
                get_permission_relation_api,
            )

            permissions = await get_permission_relation_api()
            checks = tuple(
                PermissionRelation(
                    subject=PermissionSubject("user", str(user_id)),
                    relation="admin",
                    resource=PermissionObject("tenant", str(tenant_id)),
                )
                for user_id in user_ids
            )
            return list(await permissions.batch_check(checks))
        except Exception as e:
            logger.warning(
                "batch_check tenant admins failed (tenant_id=%s): %s",
                tenant_id,
                e,
            )
            return [False] * len(user_ids)

    @classmethod
    async def _count_tenant_admins(cls, tenant_id: int) -> int:
        """Count admins through one permission application batch check.

        Falls back to counting all users when permissions are unavailable (fail-closed
        against last-admin removal: count will be >= 1).
        """
        users, _ = await UserTenantDao.aget_tenant_users(
            tenant_id,
            page=1,
            page_size=100,
        )
        if not users:
            return 0
        flags = await cls._batch_check_tenant_admin(
            [u["user_id"] for u in users],
            tenant_id,
        )
        count = sum(1 for f in flags if f)
        return count if count > 0 else len(users)  # Fail-closed: assume all users are admins.
