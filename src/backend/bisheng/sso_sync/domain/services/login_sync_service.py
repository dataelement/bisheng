"""F014 SSO login-sync orchestration.

End-to-end handler for ``POST /api/v1/internal/sso/login-sync``. Runs the
11-step flow documented in ``features/v2.5.1/014-sso-org-realtime-sync/
spec.md`` §5.1:

1. HMAC (enforced by :func:`verify_hmac` dependency).
2. Redis SETNX lock keyed on ``external_user_id`` to dedupe concurrent
   logins of the same SSO user (AC-08 edge case).
3. Enter ``bypass_tenant_filter`` + stamp ``current_tenant_id=ROOT`` so
   ORM event hooks and audit writes have a coherent tenant context.
4. Parent-chain check (strict mode per Phase-3 decision → 19312 if any
   department referenced in the payload has not yet been pushed).
5. Optional ``tenant_mapping`` processing via
   :class:`TenantMappingHandler` (idempotent, PRD §5.2.3).
6. User upsert with cross-source fallback — reuse existing records first,
   create only as a last resort.
7. UserDepartment upsert (primary + secondary), kicking the F012 ORM hook
   that triggers :meth:`UserTenantSyncService.sync_user` implicitly; we
   call it explicitly below to also cover the no-change path.
8. :meth:`UserTenantSyncService.sync_user` — derives the leaf tenant,
   bumps ``token_version`` if the leaf moved.
9. Disabled / orphaned / archived leaf tenant → 403 + 19303 (AC-04
   edge).
10. Issue JWT via :meth:`LoginUser.create_access_token` with the derived
    ``tenant_id`` + ``token_version``.
11. Return ``{user_id, leaf_tenant_id, token}``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

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
from bisheng.database.models.department import (
    DepartmentDao,
    UserDepartment,
    UserDepartmentDao,
)
from bisheng.database.models.tenant import ROOT_TENANT_ID
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
from bisheng.tenant.domain.constants import UserTenantSyncTrigger
from bisheng.tenant.domain.services.user_tenant_sync_service import (
    UserTenantSyncService,
)
from bisheng.user.domain.models.user import User, UserDao
from bisheng.user.domain.services.auth import AuthJwt, LoginUser


_USER_LOCK_KEY = 'user:sso_lock:{external_user_id}'


class LoginSyncService:

    SOURCE = 'sso'

    @classmethod
    async def execute(
        cls, payload: LoginSyncRequest, request_ip: str = '',
    ) -> LoginSyncResponse:
        """Run the 11-step login-sync flow. See module docstring for the
        full ordering contract. The caller has already passed HMAC via
        :func:`verify_hmac`; here we only worry about application-level
        correctness.
        """
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
                # --- ④ parent chain check ---
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

                # --- ⑤ tenant_mapping (auxiliary, idempotent) ---
                await TenantMappingHandler.process(
                    payload.tenant_mapping or [], request_ip=request_ip,
                )

                # --- ⑥ user upsert (w/ cross-source fallback) ---
                user = await cls._upsert_user(payload, request_ip=request_ip)

                # --- ⑦ user_department upsert ---
                if primary_dept is not None:
                    await cls._ensure_primary(user.user_id, primary_dept.id)
                    await cls._ensure_secondaries(
                        user.user_id,
                        [d.id for d in secondary_depts],
                    )

                # --- ⑧ leaf tenant derivation (may bump token_version) ---
                leaf_tenant = await UserTenantSyncService.sync_user(
                    user.user_id, trigger=UserTenantSyncTrigger.LOGIN,
                )

                # --- ⑨ disabled / orphaned / archived → 403 ---
                if leaf_tenant.status != 'active':
                    logger.warning(
                        'F014 login blocked: user %s leaf tenant %s status=%s',
                        user.user_id, leaf_tenant.id, leaf_tenant.status,
                    )
                    raise SsoTenantDisabledError.http_exception(
                        f'tenant {leaf_tenant.id} status={leaf_tenant.status}'
                    )

                # --- ⑩ sign JWT ---
                auth_jwt = AuthJwt()
                token_version = await UserDao.aget_token_version(user.user_id)
                access_token = LoginUser.create_access_token(
                    user, auth_jwt,
                    tenant_id=leaf_tenant.id,
                    token_version=token_version,
                )
            finally:
                current_tenant_id.reset(token)

        # --- ⑪ response ---
        return LoginSyncResponse(
            user_id=user.user_id,
            leaf_tenant_id=leaf_tenant.id,
            token=access_token,
        )

    # -----------------------------------------------------------------------
    # Helper: user upsert with cross-source fallback (T9).
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
                    # Race: someone just wrote the row. Adopt it anyway.
                    user = legacy
                else:
                    legacy.source = cls.SOURCE
                    await UserDao.aupdate_user(legacy)
                    await AuditLogDao.ainsert_v2(
                        tenant_id=ROOT_TENANT_ID,
                        operator_id=0,
                        operator_tenant_id=ROOT_TENANT_ID,
                        action='user.source_migrated',
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
        previous primary to ``is_primary=0``. Preserves all other
        memberships. Idempotent."""
        current = await UserDepartmentDao.aget_user_primary_department(user_id)
        if current is not None and current.department_id == dept_id:
            return  # no change
        if current is not None:
            # Demote old primary in place instead of deleting, so the
            # membership history stays intact and F012 sync_user is
            # triggered purely by the new primary assignment.
            await _demote_primary(user_id, current.department_id)
        # Add new primary; membership may already exist as secondary → upgrade.
        existing_membership = await _find_membership(user_id, dept_id)
        if existing_membership is not None:
            await _promote_to_primary(user_id, dept_id)
        else:
            await UserDepartmentDao.aadd_member(
                user_id, dept_id, is_primary=1, source=cls.SOURCE,
            )

    @classmethod
    async def _ensure_secondaries(
        cls, user_id: int, dept_ids: list[int],
    ) -> None:
        if not dept_ids:
            return
        for dept_id in dept_ids:
            existing = await _find_membership(user_id, dept_id)
            if existing is not None:
                continue
            await UserDepartmentDao.aadd_member(
                user_id, dept_id, is_primary=0, source=cls.SOURCE,
            )


# -----------------------------------------------------------------------
# Module-level helpers (kept unnamespaced so the tests can patch them
# without worrying about classmethod mocking).
# -----------------------------------------------------------------------

@asynccontextmanager
async def _acquire_user_lock(
    lock_key: str, ttl: int = 30,
) -> AsyncIterator[bool]:
    """Redis SETNX-based lock with bounded TTL. Yields True iff we acquired
    the lock. On yield=False the caller must not run the protected flow.
    The lock is always released on exit (best-effort)."""
    redis = None
    acquired = False
    try:
        redis = await get_redis_client()
        acquired = await redis.asetNx(lock_key, '1', expiration=ttl)
    except Exception as e:
        logger.warning(
            'F014 Redis lock acquire failed (%s); proceeding without lock', e,
        )
        # Degrade to non-locked: serialisation becomes best-effort. The
        # alternative (blocking login during Redis outages) is worse.
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


async def _find_membership(
    user_id: int, dept_id: int,
) -> Optional[UserDepartment]:
    from sqlmodel import select
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        result = await session.exec(
            select(UserDepartment).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == dept_id,
            )
        )
        return result.first()


async def _demote_primary(user_id: int, dept_id: int) -> None:
    from sqlalchemy import update
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        await session.execute(
            update(UserDepartment)
            .where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == dept_id,
            )
            .values(is_primary=0)
        )
        await session.commit()


async def _promote_to_primary(user_id: int, dept_id: int) -> None:
    from sqlalchemy import update
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        await session.execute(
            update(UserDepartment)
            .where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == dept_id,
            )
            .values(is_primary=1)
        )
        await session.commit()
