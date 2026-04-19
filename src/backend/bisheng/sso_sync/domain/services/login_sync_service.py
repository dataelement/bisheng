"""F014 SSO login-sync orchestration.

End-to-end handler for ``POST /api/v1/internal/sso/login-sync``. See spec
§5.1 for the full 11-step contract: HMAC → Redis dedup lock → parent-chain
check → tenant_mapping → user upsert (incl. cross-source adoption) →
UserDepartment primary/secondary assignment → UserTenantSyncService leaf
derivation → leaf status check → JWT signing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

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
from bisheng.database.models.department import UserDepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
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
        user = await UserDao.aget_by_source_external_id(cls.SOURCE, ext)
        if user is None:
            legacy = await UserDao.aget_by_external_id(ext)
            if legacy is not None:
                if int(getattr(legacy, 'delete', 0) or 0) == 1:
                    # Disabled accounts must not be re-adopted silently.
                    raise UserForbiddenError.http_exception()
                old_source = legacy.source
                if old_source == cls.SOURCE:
                    # Race: another writer flipped the row between our two
                    # lookups. Adopt it as-is, no migration audit needed.
                    user = legacy
                else:
                    legacy.source = cls.SOURCE
                    await UserDao.aupdate_user(legacy)
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
                    user = legacy
            else:
                new_user = User(
                    user_name=payload.user_attrs.name or ext,
                    email=payload.user_attrs.email,
                    phone_number=payload.user_attrs.phone,
                    external_id=ext,
                    source=cls.SOURCE,
                    password='',
                )
                try:
                    user = await UserDao.add_user_and_default_role(new_user)
                except Exception as e:  # pragma: no cover — rare integrity race
                    logger.error(
                        'F014 could not create SSO user %s: %s', ext, e,
                    )
                    raise SsoCrossSourceUserError.http_exception(
                        f'failed to create user for external_id={ext}: {e}'
                    )
        else:
            dirty = False
            attrs = payload.user_attrs
            if attrs.name and user.user_name != attrs.name:
                user.user_name = attrs.name
                dirty = True
            if attrs.email and user.email != attrs.email:
                user.email = attrs.email
                dirty = True
            if attrs.phone and user.phone_number != attrs.phone:
                user.phone_number = attrs.phone
                dirty = True
            if dirty:
                await UserDao.aupdate_user(user)

        if int(getattr(user, 'delete', 0) or 0) == 1:
            raise UserForbiddenError.http_exception()
        return user

    # -----------------------------------------------------------------------
    # Helper: UserDepartment primary + secondary management.
    # -----------------------------------------------------------------------

    @classmethod
    async def _ensure_primary(cls, user_id: int, dept_id: int) -> None:
        """Make (user_id, dept_id) the primary department, demoting any
        previous primary to ``is_primary=0``. Idempotent."""
        current = await UserDepartmentDao.aget_user_primary_department(user_id)
        if current is not None and current.department_id == dept_id:
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
