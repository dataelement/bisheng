"""F014 SSO login-sync orchestration.

End-to-end handler for ``POST /api/v1/internal/sso/login-sync``. See spec
§5.1 for the full 11-step contract: HMAC → Redis dedup lock → parent-chain
check → tenant_mapping → user upsert (incl. cross-source adoption) →
UserDepartment primary/secondary assignment → UserTenantSyncService leaf
derivation → leaf status check → JWT signing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator, List, Optional

from loguru import logger

from bisheng.common.errcode.sso_sync import (
    SsoCrossSourceUserError,
    SsoTenantDisabledError,
    SsoUserLockBusyError,
)
from bisheng.common.errcode.user import UserForbiddenError
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.department_admin_grant import (
    DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL,
    DEPARTMENT_ADMIN_GRANT_SOURCE_SSO,
    DepartmentAdminGrantDao,
)
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.database.constants import DefaultRole
from bisheng.permission.domain.services.legacy_rbac_sync_service import LegacyRBACSyncService
from bisheng.sso_sync.domain.constants import SSO_SOURCE
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
    TenantAuditAction,
    UserTenantSyncTrigger,
)
from bisheng.tenant.domain.services.user_tenant_sync_service import (
    UserTenantSyncService,
)
from bisheng.user.domain.models.user import User, UserDao
from bisheng.user.domain.services.auth import AuthJwt, LoginUser


_USER_LOCK_KEY = 'user:sso_lock:{external_user_id}'


class LoginSyncService:

    SOURCE = SSO_SOURCE

    @classmethod
    async def execute(
        cls, payload: LoginSyncRequest, request_ip: str = '',
    ) -> LoginSyncResponse:
        ttl = int(
            getattr(settings.sso_sync, 'user_lock_ttl_seconds', 30) or 30
        )
        lock_key = _USER_LOCK_KEY.format(
            external_user_id=payload.external_user_id,
        )

        async with _acquire_user_lock(lock_key, ttl=ttl) as acquired:
            if not acquired:
                raise SsoUserLockBusyError.http_exception(
                    f'another SSO login for {payload.external_user_id} is '
                    f'in progress'
                )
            return await cls._execute_locked(payload, request_ip)

    @classmethod
    async def _execute_locked(
        cls, payload: LoginSyncRequest, request_ip: str,
    ) -> LoginSyncResponse:
        with bypass_tenant_filter():
            token = set_current_tenant_id(ROOT_TENANT_ID)
            try:
                # --- parent chain check ---
                if payload.primary_dept_external_id:
                    all_exts = [payload.primary_dept_external_id] + list(
                        payload.secondary_dept_external_ids or []
                    )
                    ext_to_dept = await DeptUpsertService.assert_parent_chain_exists(
                        all_exts,
                    )
                    primary_dept = ext_to_dept[payload.primary_dept_external_id]
                    secondary_depts = [
                        ext_to_dept[e]
                        for e in (payload.secondary_dept_external_ids or [])
                        if e in ext_to_dept
                    ]
                else:
                    # Tolerance: no primary → user falls back to Root after
                    # sync_user.
                    primary_dept = None
                    secondary_depts = []

                # --- tenant_mapping (auxiliary, idempotent) ---
                await TenantMappingHandler.process(
                    payload.tenant_mapping or [], request_ip=request_ip,
                )

                # --- user upsert (w/ cross-source fallback) ---
                user = await cls._upsert_user(payload, request_ip=request_ip)

                # --- user_department upsert ---
                if primary_dept is not None:
                    await cls._ensure_primary(user.user_id, primary_dept.id)
                    await cls._ensure_secondaries(
                        user.user_id,
                        [d.id for d in secondary_depts],
                    )

                await cls._sync_department_admin_tuples(
                    user.user_id,
                    payload.department_admin_external_ids,
                )

                # --- leaf tenant derivation (may bump token_version) ---
                leaf_tenant = await UserTenantSyncService.sync_user(
                    user.user_id, trigger=UserTenantSyncTrigger.LOGIN,
                )

                # --- disabled / orphaned / archived → 403 ---
                if leaf_tenant.status != 'active':
                    logger.warning(
                        'F014 login blocked: user %s leaf tenant %s status=%s',
                        user.user_id, leaf_tenant.id, leaf_tenant.status,
                    )
                    raise SsoTenantDisabledError.http_exception(
                        f'tenant {leaf_tenant.id} status={leaf_tenant.status}'
                    )

                # --- sign JWT ---
                auth_jwt = AuthJwt()
                token_version = await UserDao.aget_token_version(user.user_id)
                access_token = LoginUser.create_access_token(
                    user, auth_jwt,
                    tenant_id=leaf_tenant.id,
                    token_version=token_version,
                )
            finally:
                current_tenant_id.reset(token)

        return LoginSyncResponse(
            user_id=user.user_id,
            leaf_tenant_id=leaf_tenant.id,
            token=access_token,
        )

    # -----------------------------------------------------------------------
    # Helper: user upsert with cross-source fallback.
    # -----------------------------------------------------------------------

    @classmethod
    async def _upsert_user(
        cls, payload: LoginSyncRequest, request_ip: str,
    ) -> User:
        ext = payload.external_user_id
        attrs = payload.user_attrs
        user = await UserDao.aget_by_source_external_id(cls.SOURCE, ext)
        if user is None:
            legacy = await UserDao.aget_by_external_id(ext)
            if legacy is not None:
                if int(getattr(legacy, 'delete', 0) or 0) == 1:
                    # Disabled accounts must not be re-adopted silently.
                    raise UserForbiddenError.http_exception()
                old_source = legacy.source
                write_migration_audit = False
                if old_source == cls.SOURCE:
                    # Race: another writer flipped the row between our two
                    # lookups. Adopt it as-is, no migration audit needed.
                    user = legacy
                else:
                    legacy.source = cls.SOURCE
                    write_migration_audit = True
                    user = legacy
                cls._apply_user_attrs(user, attrs)
                cls._touch_user_sync_time(user)
                await UserDao.aupdate_user(user)
                if write_migration_audit:
                    await AuditLogDao.ainsert_v2(
                        tenant_id=ROOT_TENANT_ID,
                        operator_id=0,
                        operator_tenant_id=ROOT_TENANT_ID,
                        action=TenantAuditAction.USER_SOURCE_MIGRATED.value,
                        target_type='user',
                        target_id=str(legacy.user_id),
                        metadata={
                            'old_source': old_source,
                            'new_source': cls.SOURCE,
                            'external_id': ext,
                            'via': 'sso_realtime',
                        },
                        ip_address=request_ip,
                    )
            else:
                new_user = User(
                    user_name=attrs.name or ext,
                    email=attrs.email,
                    phone_number=attrs.phone,
                    external_id=ext,
                    source=cls.SOURCE,
                    password='',
                )
                try:
                    user = await UserDao.add_user_and_default_role(new_user)
                    await LegacyRBACSyncService.sync_user_auth_created(
                        user.user_id,
                        [DefaultRole],
                    )
                except Exception as e:  # pragma: no cover — rare integrity race
                    logger.error(
                        'F014 could not create SSO user %s: %s', ext, e,
                    )
                    raise SsoCrossSourceUserError.http_exception(
                        f'failed to create user for external_id={ext}: {e}'
                    )
        else:
            if int(getattr(user, 'delete', 0) or 0) == 1:
                raise UserForbiddenError.http_exception()
            cls._apply_user_attrs(user, attrs)
            cls._touch_user_sync_time(user)
            await UserDao.aupdate_user(user)

        if int(getattr(user, 'delete', 0) or 0) == 1:
            raise UserForbiddenError.http_exception()
        return user

    @classmethod
    def _apply_user_attrs(cls, user: User, attrs) -> None:
        """Apply present HR attributes without clearing omitted fields."""
        if attrs.name and user.user_name != attrs.name:
            user.user_name = attrs.name
        if attrs.email is not None and user.email != attrs.email:
            user.email = attrs.email
        if attrs.phone is not None and user.phone_number != attrs.phone:
            user.phone_number = attrs.phone

    @classmethod
    def _touch_user_sync_time(cls, user: User) -> None:
        """Mark a successful existing-user sync even when attrs are unchanged."""
        user.update_time = datetime.now()

    # -----------------------------------------------------------------------
    # Helper: UserDepartment primary + secondary management.
    # -----------------------------------------------------------------------

    @classmethod
    async def _ensure_primary(cls, user_id: int, dept_id: int) -> None:
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
                user_id, current.department_id, is_primary=0,
            )
        existing = await UserDepartmentDao.aget_membership(user_id, dept_id)
        if existing is not None:
            await UserDepartmentDao.aset_primary_flag(
                user_id, dept_id, is_primary=1,
            )
        else:
            await UserDepartmentDao.aadd_member(
                user_id, dept_id, is_primary=1, source=cls.SOURCE,
            )
        await cls._sync_department_member_tuples(user_id, [dept_id])

    @classmethod
    async def _sync_department_member_tuples(
        cls, user_id: int, dept_ids: list[int],
    ) -> None:
        """Best-effort OpenFGA department membership repair for SSO login.

        Some older paths wrote ``user_department`` rows without the matching
        ``department#member`` tuple. Rewriting the member tuple during login is
        idempotent and lets department-resource grants work immediately.
        """
        if not dept_ids:
            return
        from bisheng.department.domain.services.department_change_handler import (
            DepartmentChangeHandler,
        )

        ops = []
        for dept_id in dict.fromkeys(int(did) for did in dept_ids):
            ops.extend(DepartmentChangeHandler.on_members_added(dept_id, [user_id]))
        await DepartmentChangeHandler.execute_async(ops)

    @classmethod
    async def _sync_department_admin_tuples(
        cls,
        user_id: int,
        admin_dept_external_ids: Optional[List[str]],
    ) -> None:
        """OpenFGA ``department#admin`` vs WeCom leader list + grant-source rows.

        - Field **omitted** (``None``): no FGA / DB grant changes (backward compatible).
        - Field **present** (including ``[]``): reconcile SSO departments the user
          belongs to. Only removes FGA ``admin`` when ``department_admin_grant``
          marks the grant as ``sso``; ``manual`` (management UI) is left intact.
        """
        from bisheng.department.domain.services.department_change_handler import (
            DepartmentChangeHandler,
        )

        if admin_dept_external_ids is None:
            return

        want = {str(x).strip() for x in admin_dept_external_ids if x and str(x).strip()}

        memberships = await UserDepartmentDao.aget_user_departments(user_id)
        dept_ids = list({m.department_id for m in memberships})
        depts = await DepartmentDao.aget_by_ids(dept_ids) if dept_ids else []
        dept_by_id = {int(d.id): d for d in depts if d.id is not None}

        reconcile_dept_ids: List[int] = []
        for row in memberships:
            dept = dept_by_id.get(int(row.department_id))
            if dept is None or getattr(dept, 'source', '') != cls.SOURCE:
                continue
            ext_raw = getattr(dept, 'external_id', None)
            if not ext_raw or not str(ext_raw).strip():
                continue
            reconcile_dept_ids.append(int(dept.id))

        grants = await DepartmentAdminGrantDao.aget_by_user_and_departments(
            user_id, reconcile_dept_ids,
        )
        grant_by_dept = {int(g.department_id): g for g in grants}

        ops = []
        upsert_sso_dept_ids: List[int] = []
        delete_grant_dept_ids: List[int] = []

        for row in memberships:
            dept = dept_by_id.get(int(row.department_id))
            if dept is None:
                continue
            if getattr(dept, 'source', '') != cls.SOURCE:
                continue
            ext_raw = getattr(dept, 'external_id', None)
            if not ext_raw:
                continue
            ext_key = str(ext_raw).strip()
            if not ext_key:
                continue
            did = int(dept.id)
            marker = grant_by_dept.get(did)

            if ext_key in want:
                if getattr(dept, 'status', '') != 'active':
                    continue
                if (
                    marker is not None
                    and getattr(marker, 'grant_source', '')
                    == DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL
                ):
                    continue
                ops.extend(
                    DepartmentChangeHandler.on_admin_set(did, [user_id])
                )
                upsert_sso_dept_ids.append(did)
            else:
                if (
                    marker is not None
                    and getattr(marker, 'grant_source', '')
                    == DEPARTMENT_ADMIN_GRANT_SOURCE_SSO
                ):
                    ops.extend(
                        DepartmentChangeHandler.on_admin_removed(did, [user_id])
                    )
                    delete_grant_dept_ids.append(did)

        if ops:
            await DepartmentChangeHandler.execute_async(ops)

        for did in dict.fromkeys(upsert_sso_dept_ids):
            await DepartmentAdminGrantDao.aupsert(
                user_id, did, DEPARTMENT_ADMIN_GRANT_SOURCE_SSO,
            )
        for did in dict.fromkeys(delete_grant_dept_ids):
            await DepartmentAdminGrantDao.adelete(user_id, did)

    @classmethod
    async def _ensure_secondaries(
        cls, user_id: int, dept_ids: list[int],
    ) -> None:
        """Add ``is_primary=0`` memberships for any dept_id the user does
        not already belong to. Single IN-list lookup instead of one query
        per dept (R2/R3 batch fix)."""
        if not dept_ids:
            return
        existing_rows = await UserDepartmentDao.aget_memberships_in_depts(
            user_id, dept_ids,
        )
        existing_ids = {row.department_id for row in existing_rows}
        to_add = [d for d in dept_ids if d not in existing_ids]
        for dept_id in to_add:
            await UserDepartmentDao.aadd_member(
                user_id, dept_id, is_primary=0, source=cls.SOURCE,
            )
        await cls._sync_department_member_tuples(user_id, dept_ids)


# -----------------------------------------------------------------------
# Module-level helper: Redis SETNX-based per-user login lock.
# -----------------------------------------------------------------------

@asynccontextmanager
async def _acquire_user_lock(
    lock_key: str, ttl: int = 30,
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
            lock_key, b'1', nx=True, ex=ttl,
        )
        acquired = bool(result)
    except Exception as e:
        logger.warning(
            'F014 Redis lock acquire failed (%s); proceeding without lock', e,
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
                logger.warning('F014 Redis lock release failed: %s', e)
