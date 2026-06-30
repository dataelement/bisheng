"""F014 SSO login-sync orchestration.

End-to-end handler for ``POST /api/v1/internal/sso/login-sync``. See spec
§5.1 for the full 11-step contract: HMAC → Redis dedup lock → parent-chain
check → tenant_mapping → user upsert (incl. source-preserving cross-source
adoption) →
UserDepartment primary/secondary assignment → UserTenantSyncService leaf
derivation → leaf status check → JWT signing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from loguru import logger

from bisheng.common.errcode.sso_sync import (
    SsoTenantDisabledError,
    SsoUserLockBusyError,
    SsoUserNotFoundError,
)
from bisheng.common.errcode.user import UserForbiddenError, UserMultiLoginConflictError
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.constants import (
    USER_DISABLE_SOURCE_GATEWAY,
    USER_DISABLE_SOURCE_ORG_SYNC,
    AdminRole,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.department_admin_grant import (
    DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL,
    DEPARTMENT_ADMIN_GRANT_SOURCE_SSO,
    DepartmentAdminGrantDao,
)
from bisheng.database.models.role import RoleDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.permission.domain.services.legacy_rbac_sync_service import LegacyRBACSyncService
from bisheng.sso_sync.domain.constants import (
    DEFAULT_SSO_SYNC_SOURCE,
    WECOM_SOURCE,
)
from bisheng.sso_sync.domain.schemas.payloads import (
    LoginSyncRequest,
    LoginSyncResponse,
)
from bisheng.sso_sync.domain.services.dept_upsert_service import (
    DeptUpsertService,
)
from bisheng.sso_sync.domain.services.tenant_mapping_handler import (
    TenantMappingHandler,
)
from bisheng.tenant.domain.constants import (
    UserTenantSyncTrigger,
)
from bisheng.tenant.domain.services.user_tenant_sync_service import (
    UserTenantSyncService,
)
from bisheng.user.domain.models.user import User, UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.user.domain.services.auth import AuthJwt, LoginUser
from bisheng.user.domain.services.user import UserService
from bisheng.user.domain.const import USER_CURRENT_SESSION

_USER_LOCK_KEY = "user:sso_lock:{external_user_id}"


class LoginSyncService:
    SOURCE = DEFAULT_SSO_SYNC_SOURCE

    @staticmethod
    def _disable_source_for_row(row_source: str, want_delete: int) -> str | None:
        if want_delete != 1:
            return None
        if row_source == WECOM_SOURCE:
            return USER_DISABLE_SOURCE_ORG_SYNC
        return USER_DISABLE_SOURCE_GATEWAY

    @classmethod
    async def execute(
        cls,
        payload: LoginSyncRequest,
        request_ip: str = "",
        row_source: str = DEFAULT_SSO_SYNC_SOURCE,
    ) -> LoginSyncResponse:
        ttl = int(getattr(settings.sso_sync, "user_lock_ttl_seconds", 30) or 30)
        lock_key = _USER_LOCK_KEY.format(
            external_user_id=payload.external_user_id,
        )

        async with _acquire_user_lock(lock_key, ttl=ttl) as acquired:
            if not acquired:
                raise SsoUserLockBusyError.http_exception(
                    f"another SSO login for {payload.external_user_id} is in progress"
                )
            return await cls._execute_locked(
                payload,
                request_ip,
                row_source,
            )

    @classmethod
    async def _execute_locked(
        cls,
        payload: LoginSyncRequest,
        request_ip: str,
        row_source: str,
    ) -> LoginSyncResponse:
        with bypass_tenant_filter():
            token = set_current_tenant_id(ROOT_TENANT_ID)
            try:
                # --- parent chain (enabled + disabled WeCom users share binding) ---
                if payload.primary_dept_external_id:
                    all_exts = [
                        payload.primary_dept_external_id,
                        *(payload.secondary_dept_external_ids or []),
                    ]
                    ext_to_dept = await DeptUpsertService.assert_parent_chain_exists(
                        all_exts,
                        source=row_source,
                    )
                    primary_dept = ext_to_dept[payload.primary_dept_external_id]
                    secondary_depts = [
                        ext_to_dept[e] for e in (payload.secondary_dept_external_ids or []) if e in ext_to_dept
                    ]
                else:
                    primary_dept = None
                    secondary_depts = []

                await TenantMappingHandler.process(
                    payload.tenant_mapping or [],
                    request_ip=request_ip,
                    dept_source=row_source,
                )

                user, full_department_override = await cls._upsert_user(
                    payload,
                    request_ip=request_ip,
                    row_source=row_source,
                )

                if full_department_override:
                    await cls._replace_departments_full(
                        user.user_id,
                        primary_dept.id if primary_dept is not None else None,
                        [d.id for d in secondary_depts],
                        row_source=row_source,
                    )
                elif primary_dept is not None:
                    await cls._ensure_primary(
                        user.user_id,
                        primary_dept.id,
                        row_source=row_source,
                    )
                    reconcile_secondary = "secondary_dept_external_ids" in payload.model_fields_set
                    await cls._ensure_secondaries(
                        user.user_id,
                        [d.id for d in secondary_depts],
                        row_source=row_source,
                        reconcile_remove=reconcile_secondary,
                    )

                await cls._sync_department_admin_tuples(
                    user.user_id,
                    payload.department_admin_external_ids,
                    row_source=row_source,
                )

                # WeCom-style disable: keep department rows for org-tree placeholder (PRD 8b).
                if payload.account_disabled is True:
                    await UserService.ainvalidate_jwt_after_account_disabled(
                        int(user.user_id or 0),
                    )
                    return LoginSyncResponse(
                        user_id=int(user.user_id or 0),
                        leaf_tenant_id=ROOT_TENANT_ID,
                        token="",
                    )

                leaf_tenant = await UserTenantSyncService.sync_user(
                    user.user_id,
                    trigger=UserTenantSyncTrigger.LOGIN,
                )

                if leaf_tenant.status != "active":
                    logger.warning(
                        "F014 login blocked: user %s leaf tenant %s status=%s",
                        user.user_id,
                        leaf_tenant.id,
                        leaf_tenant.status,
                    )
                    raise SsoTenantDisabledError.http_exception(f"tenant {leaf_tenant.id} status={leaf_tenant.status}")

                guard = await UserService._reject_login_if_user_has_no_usable_access(user)
                if guard is not None:
                    from bisheng.common.errcode.user import (
                        UserNoRoleForLoginError,
                        UserNoWebMenuForLoginError,
                    )

                    if guard.status_code == UserNoRoleForLoginError.Code:
                        raise UserNoRoleForLoginError()
                    raise UserNoWebMenuForLoginError()

                if (
                    not payload.force_login
                    and await UserService.has_other_active_session(int(user.user_id))
                ):
                    raise UserMultiLoginConflictError()

                auth_jwt = AuthJwt()
                token_version = await UserDao.aget_token_version(user.user_id)
                access_token = LoginUser.create_access_token(
                    user,
                    auth_jwt,
                    tenant_id=leaf_tenant.id,
                    token_version=token_version,
                )
                redis_client = await get_redis_client()
                await redis_client.aset(
                    USER_CURRENT_SESSION.format(user.user_id),
                    access_token,
                    auth_jwt.cookie_conf.jwt_token_expire_time + 3600,
                )
            finally:
                current_tenant_id.reset(token)

        return LoginSyncResponse(
            user_id=user.user_id,
            leaf_tenant_id=leaf_tenant.id,
            token=access_token,
        )

    # -----------------------------------------------------------------------
    # Helper: user upsert with source-preserving cross-source fallback.
    # -----------------------------------------------------------------------

    @classmethod
    async def _upsert_user(
        cls,
        payload: LoginSyncRequest,
        request_ip: str,
        row_source: str,
    ) -> tuple[User, bool]:
        ext = payload.external_user_id
        attrs = payload.user_attrs
        full_department_override = False
        user = await UserDao.aget_by_source_external_id(row_source, ext)
        if user is None:
            legacy = await UserDao.aget_by_external_id(ext)
            if legacy is not None:
                if int(getattr(legacy, "delete", 0) or 0) == 1:
                    # Do not re-adopt disabled rows unless the sync payload
                    # explicitly states account state (e.g. WeCom enable/disable).
                    if payload.account_disabled is None:
                        raise UserForbiddenError.http_exception()
                old_source = getattr(legacy, "source", None)
                if old_source == row_source:
                    # Race: another writer flipped the row between our two
                    # lookups. Adopt it as-is.
                    user = legacy
                else:
                    logger.info(
                        "SSO login-sync reused existing cross-source user "
                        "without source migration: user_id=%s external_id=%s "
                        "existing_source=%s login_source=%s",
                        legacy.user_id,
                        ext,
                        old_source,
                        row_source,
                    )
                    user = legacy
                cls._apply_user_attrs(user, attrs)
                cls._touch_user_sync_time(user)
                await UserDao.aupdate_user(user)
            else:
                logger.warning(
                    "SSO login-sync rejected missing user: external_id=%s source=%s",
                    ext,
                    row_source,
                )
                raise SsoUserNotFoundError.http_exception(f"account is invalid for external_id={ext}")
        else:
            # WeCom (and Gateway) send explicit ``account_disabled``; when False,
            # the row below must flip ``delete`` back to 0. Unconditional forbid
            # here blocked re-enable after 企微禁用 → 再启用 (delete stayed 1).
            if int(getattr(user, "delete", 0) or 0) == 1:
                if payload.account_disabled is None:
                    raise UserForbiddenError.http_exception()
            cls._apply_user_attrs(user, attrs)
            cls._touch_user_sync_time(user)
            await UserDao.aupdate_user(user)

        # Gateway org sync: optional explicit account enable/disable
        if payload.account_disabled is not None:
            want = 1 if payload.account_disabled else 0
            if int(getattr(user, "delete", 0) or 0) != want:
                user.delete = want
                user.disable_source = cls._disable_source_for_row(row_source, want)
                await UserDao.aupdate_user(user)

        if int(getattr(user, "delete", 0) or 0) == 1 and payload.account_disabled is not True:
            raise UserForbiddenError.http_exception()
        return user, full_department_override

    @staticmethod
    def _normalize_contact_field(val: str | None) -> str | None:
        """Strip; empty string → None. ``None`` means omit (do not overwrite in apply)."""
        if val is None:
            return None
        s = val.strip()
        return s if s else None

    @classmethod
    def _apply_user_attrs(cls, user: User, attrs) -> None:
        """Apply present HR attributes without clearing omitted fields."""
        if attrs.name:
            nm = attrs.name.strip()
            if nm and user.user_name != nm:
                user.user_name = nm
        if attrs.email is not None:
            ne = cls._normalize_contact_field(attrs.email)
            if user.email != ne:
                user.email = ne
        if attrs.phone is not None:
            np = cls._normalize_contact_field(attrs.phone)
            if user.phone_number != np:
                user.phone_number = np

    @classmethod
    def _touch_user_sync_time(cls, user: User) -> None:
        """Mark a successful existing-user sync even when attrs are unchanged."""
        user.update_time = datetime.now()

    # -----------------------------------------------------------------------
    # Helper: UserDepartment primary + secondary management.
    # -----------------------------------------------------------------------

    @classmethod
    async def _ensure_primary(
        cls,
        user_id: int,
        dept_id: int,
        *,
        row_source: str,
    ) -> None:
        """Make (user_id, dept_id) the primary department, demoting any
        previous primary to ``is_primary=0``. Idempotent."""
        current = await UserDepartmentDao.aget_user_primary_department(user_id)
        if current is not None and current.department_id == dept_id:
            await cls._sync_department_member_tuples(user_id, [dept_id])
            return
        if current is not None:
            # Demote old primary in place instead of deleting to preserve
            # membership history; F012 sync_user reads only the flag.
            await UserDepartmentDao.aset_primary_flag(
                user_id,
                current.department_id,
                is_primary=0,
            )
        existing = await UserDepartmentDao.aget_membership(user_id, dept_id)
        if existing is not None:
            await UserDepartmentDao.aset_primary_flag(
                user_id,
                dept_id,
                is_primary=1,
            )
        else:
            await UserDepartmentDao.aadd_member(
                user_id,
                dept_id,
                is_primary=1,
                source=row_source,
            )
        await cls._sync_department_member_tuples(user_id, [dept_id])

    @classmethod
    async def _replace_departments_full(
        cls,
        user_id: int,
        primary_dept_id: int | None,
        secondary_dept_ids: list[int],
        *,
        row_source: str,
    ) -> None:
        """Replace all department memberships from the imported payload."""
        desired_secondary_ids = [
            int(did) for did in secondary_dept_ids if did is not None and int(did) != int(primary_dept_id or 0)
        ]
        desired_dept_ids: list[int] = []
        if primary_dept_id is not None:
            desired_dept_ids.append(int(primary_dept_id))
        desired_dept_ids.extend(desired_secondary_ids)
        desired_dept_ids = list(dict.fromkeys(desired_dept_ids))

        current_memberships = await UserDepartmentDao.aget_user_departments(user_id)
        current_dept_ids = list(dict.fromkeys(int(row.department_id) for row in current_memberships))

        await cls._replace_department_scoped_roles(
            user_id,
            revoke_dept_ids=current_dept_ids,
            apply_dept_ids=desired_dept_ids,
        )

        for department_id in current_dept_ids:
            await cls._remove_department_membership(user_id, department_id)

        if primary_dept_id is not None:
            await UserDepartmentDao.aadd_member(
                user_id,
                int(primary_dept_id),
                is_primary=1,
                source=row_source,
            )
        for department_id in desired_secondary_ids:
            await UserDepartmentDao.aadd_member(
                user_id,
                int(department_id),
                is_primary=0,
                source=row_source,
            )

        await cls._sync_department_member_tuples(user_id, desired_dept_ids)

    @classmethod
    async def _replace_department_scoped_roles(
        cls,
        user_id: int,
        *,
        revoke_dept_ids: list[int],
        apply_dept_ids: list[int],
    ) -> None:
        """Revoke removed department-scoped roles, then apply target defaults."""
        current_roles = await UserRoleDao.aget_user_roles(user_id)
        current_role_ids = {int(row.role_id) for row in current_roles}

        target_role_ids = set(current_role_ids)
        if revoke_dept_ids and current_role_ids:
            role_rows = await RoleDao.aget_role_by_ids(list(current_role_ids))
            revoke_scope = {int(did) for did in revoke_dept_ids}
            revoke_role_ids = {
                int(role.id)
                for role in role_rows
                if getattr(role, "id", None) is not None
                and int(getattr(role, "department_id", 0) or 0) in revoke_scope
                and int(role.id) != AdminRole
            }
            target_role_ids -= revoke_role_ids

        if apply_dept_ids:
            dept_rows = await DepartmentDao.aget_by_ids(apply_dept_ids)
            default_role_ids = {
                int(role_id)
                for dept in dept_rows
                for role_id in (getattr(dept, "default_role_ids", None) or [])
                if role_id is not None and int(role_id) != AdminRole
            }
            target_role_ids.update(default_role_ids)

        need_add = sorted(target_role_ids - current_role_ids)
        need_del = sorted(current_role_ids - target_role_ids)
        if need_add:
            UserRoleDao.add_user_roles(user_id, need_add)
        if need_del:
            UserRoleDao.delete_user_roles(user_id, need_del)
        if need_add or need_del:
            await LegacyRBACSyncService.sync_user_role_change(
                user_id,
                current_role_ids,
                target_role_ids,
            )

    @classmethod
    async def _sync_department_member_tuples(
        cls,
        user_id: int,
        dept_ids: list[int],
    ) -> None:
        """Best-effort OpenFGA department membership repair for SSO login.

        Some older paths wrote ``user_department`` rows without the matching
        ``department#member`` tuple. Rewriting the member tuple during login is
        idempotent and lets department-resource grants work immediately.
        """
        if not dept_ids:
            return
        ops = []
        for dept_id in dict.fromkeys(int(did) for did in dept_ids):
            ops.extend(DepartmentChangeHandler.on_members_added(dept_id, [user_id]))
        await DepartmentChangeHandler.execute_async(ops)

    @classmethod
    async def _sync_department_admin_tuples(
        cls,
        user_id: int,
        admin_dept_external_ids: list[str] | None,
        *,
        row_source: str,
    ) -> None:
        """OpenFGA ``department#admin`` vs WeCom leader list + grant-source rows.

        - Field **omitted** (``None``): no FGA / DB grant changes (backward compatible).
        - Field **present** (including ``[]``): reconcile SSO departments the user
          belongs to. Only removes FGA ``admin`` when ``department_admin_grant``
          marks the grant as ``sso``; ``manual`` (management UI) is left intact.
        """
        if admin_dept_external_ids is None:
            return

        want = {str(x).strip() for x in admin_dept_external_ids if x and str(x).strip()}

        memberships = await UserDepartmentDao.aget_user_departments(user_id)
        dept_ids = list({m.department_id for m in memberships})
        depts = await DepartmentDao.aget_by_ids(dept_ids) if dept_ids else []
        dept_by_id = {int(d.id): d for d in depts if d.id is not None}

        reconcile_dept_ids: list[int] = []
        for row in memberships:
            dept = dept_by_id.get(int(row.department_id))
            if dept is None or getattr(dept, "source", "") != row_source:
                continue
            ext_raw = getattr(dept, "external_id", None)
            if not ext_raw or not str(ext_raw).strip():
                continue
            reconcile_dept_ids.append(int(dept.id))

        grants = await DepartmentAdminGrantDao.aget_by_user_and_departments(
            user_id,
            reconcile_dept_ids,
        )
        grant_by_dept = {int(g.department_id): g for g in grants}

        ops = []
        upsert_sso_dept_ids: list[int] = []
        delete_grant_dept_ids: list[int] = []

        for row in memberships:
            dept = dept_by_id.get(int(row.department_id))
            if dept is None:
                continue
            if getattr(dept, "source", "") != row_source:
                continue
            ext_raw = getattr(dept, "external_id", None)
            if not ext_raw:
                continue
            ext_key = str(ext_raw).strip()
            if not ext_key:
                continue
            did = int(dept.id)
            marker = grant_by_dept.get(did)

            if ext_key in want:
                if getattr(dept, "status", "") != "active":
                    continue
                if marker is not None and getattr(marker, "grant_source", "") == DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL:
                    continue
                ops.extend(DepartmentChangeHandler.on_admin_set(did, [user_id]))
                upsert_sso_dept_ids.append(did)
            else:
                if marker is not None and getattr(marker, "grant_source", "") == DEPARTMENT_ADMIN_GRANT_SOURCE_SSO:
                    ops.extend(DepartmentChangeHandler.on_admin_removed(did, [user_id]))
                    delete_grant_dept_ids.append(did)

        if ops:
            await DepartmentChangeHandler.execute_async(ops)

        for did in dict.fromkeys(upsert_sso_dept_ids):
            await DepartmentAdminGrantDao.aupsert(
                user_id,
                did,
                DEPARTMENT_ADMIN_GRANT_SOURCE_SSO,
            )
        for did in dict.fromkeys(delete_grant_dept_ids):
            await DepartmentAdminGrantDao.adelete(user_id, did)

    @classmethod
    async def _remove_sso_secondary_membership(
        cls,
        user_id: int,
        department_id: int,
    ) -> None:
        """Remove a secondary membership from an org-synced department.

        Mirrors management UI removal: member + admin FGA + ``department_admin_grant``.
        """
        await cls._remove_department_membership(user_id, department_id)

    @classmethod
    async def _remove_department_membership(
        cls,
        user_id: int,
        department_id: int,
    ) -> None:
        """Remove a department membership and its FGA/admin markers."""
        await UserDepartmentDao.aremove_member(user_id, department_id)
        ops = DepartmentChangeHandler.on_member_removed(
            department_id, user_id
        ) + DepartmentChangeHandler.on_admin_removed(department_id, [user_id])
        await DepartmentChangeHandler.execute_async(ops)
        await DepartmentAdminGrantDao.adelete(user_id, department_id)

    @classmethod
    async def _reconcile_remove_sso_secondary_memberships(
        cls,
        user_id: int,
        want_secondary_ids: set[int],
        *,
        row_source: str,
    ) -> None:
        """Drop secondary rows for ``source=row_source`` departments not in ``want``."""
        memberships = await UserDepartmentDao.aget_user_departments(user_id)
        to_drop: list[int] = []
        for row in memberships:
            if int(getattr(row, "is_primary", 0) or 0) != 0:
                continue
            did = int(row.department_id)
            if did in want_secondary_ids:
                continue
            to_drop.append(did)
        if not to_drop:
            return
        unique_drop = list(dict.fromkeys(to_drop))
        depts = await DepartmentDao.aget_by_ids(unique_drop)
        dept_by_id = {int(d.id): d for d in depts if d.id is not None}
        for did in unique_drop:
            dept = dept_by_id.get(did)
            if dept is None:
                continue
            if getattr(dept, "source", "") != row_source:
                continue
            await cls._remove_sso_secondary_membership(user_id, did)

    @classmethod
    async def _ensure_secondaries(
        cls,
        user_id: int,
        dept_ids: list[int],
        *,
        row_source: str,
        reconcile_remove: bool,
    ) -> None:
        """Secondary departments: optional remove-then-add.

        When ``reconcile_remove`` is True (payload explicitly included
        ``secondary_dept_external_ids``), secondary memberships under
        ``department.source == row_source`` that are absent from ``dept_ids``
        are removed. Local-only departments are left unchanged.

        When False (field omitted), only add missing secondaries (legacy
        Gateway behaviour).
        """
        want_ids = {int(x) for x in dept_ids if x is not None}
        if reconcile_remove:
            await cls._reconcile_remove_sso_secondary_memberships(
                user_id,
                want_ids,
                row_source=row_source,
            )
        if not dept_ids:
            return
        existing_rows = await UserDepartmentDao.aget_memberships_in_depts(
            user_id,
            dept_ids,
        )
        existing_ids = {row.department_id for row in existing_rows}
        to_add = [d for d in dept_ids if d not in existing_ids]
        for dept_id in to_add:
            await UserDepartmentDao.aadd_member(
                user_id,
                dept_id,
                is_primary=0,
                source=row_source,
            )
        await cls._sync_department_member_tuples(user_id, dept_ids)


# -----------------------------------------------------------------------
# Module-level helper: Redis SETNX-based per-user login lock.
# -----------------------------------------------------------------------


@asynccontextmanager
async def _acquire_user_lock(
    lock_key: str,
    ttl: int = 30,
) -> AsyncIterator[bool]:
    """SETNX + TTL in a single Redis roundtrip (``SET key value NX EX ttl``).

    Yields True iff we acquired the lock. On yield=False the caller must
    not run the protected flow. The lock is always released on exit
    (best-effort). Redis outages degrade gracefully to non-locked mode —
    blocking login during transient Redis failures would be worse than
    losing the dedup guarantee for the duration of the outage.
    """
    redis = None
    acquired = False
    try:
        redis = await get_redis_client()
        # Atomic SETNX + EX — avoids the two-step (setnx + expire) race
        # where a crash between the two leaves a TTL-less lock.
        result = await redis.async_connection.set(
            lock_key,
            b"1",
            nx=True,
            ex=ttl,
        )
        acquired = bool(result)
    except Exception as e:
        logger.warning(
            "F014 Redis lock acquire failed (%s); proceeding without lock",
            e,
        )
        acquired = True
        redis = None
    try:
        yield acquired
    finally:
        if redis is not None and acquired:
            try:
                await redis.adelete(lock_key)
            except Exception as e:  # pragma: no cover
                logger.warning("F014 Redis lock release failed: %s", e)
