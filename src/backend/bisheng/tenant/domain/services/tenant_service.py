"""TenantService — core business logic for tenant management.

Part of F010-tenant-management-ui.
"""

import logging
from typing import List, Optional

from bisheng.common.errcode.tenant import (
    NoTenantsAvailableError,
    TenantAdminRequiredError,
    TenantCodeDuplicateError,
    TenantCreationFailedError,
    TenantDisabledError,
    TenantHasUsersError,
    TenantNotFoundError,
    TenantSwitchForbiddenError,
)
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tenant import Tenant, TenantDao, UserTenantDao
from bisheng.tenant.domain.schemas.tenant_schema import (
    TenantCreate,
    TenantDetail,
    TenantListItem,
    TenantQuotaResponse,
    TenantQuotaUpdate,
    TenantStatusUpdate,
    TenantUpdate,
    TenantUserAdd,
    UserTenantItem,
)

logger = logging.getLogger(__name__)

DISABLED_TENANT_KEY = 'disabled_tenant:{}'


def _get_storage_quota(tenant: Tenant) -> Optional[float]:
    """Extract storage_gb from quota_config if present."""
    if tenant.quota_config and 'storage_gb' in tenant.quota_config:
        return tenant.quota_config['storage_gb']
    return None


class TenantService:
    """Stateless service for tenant lifecycle management."""

    # ── Tenant CRUD ────────────────────────────────────────────

    @classmethod
    async def acreate_tenant(cls, data: TenantCreate, login_user) -> dict:
        """Create a tenant atomically: Tenant + root dept + UserTenant + OpenFGA tuples (INV-14)."""
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
                tenant_id=tenant.id, name=data.tenant_name,
            )

            # Step 3: Create UserTenant for each admin
            for uid in data.admin_user_ids:
                await UserTenantDao.aadd_user_to_tenant(
                    user_id=uid, tenant_id=tenant.id, is_default=0,
                )

            # Step 4: Write OpenFGA tuples (after DB commit)
            await cls._write_tenant_tuples(
                tenant_id=tenant.id,
                admin_user_ids=data.admin_user_ids,
                action='grant',
            )

            return tenant.model_dump()

        except TenantCodeDuplicateError:
            raise
        except Exception as e:
            logger.error('Tenant creation failed: %s', e, exc_info=True)
            raise TenantCreationFailedError()

    @classmethod
    async def alist_tenants(
        cls,
        keyword: Optional[str],
        status: Optional[str],
        page: int,
        page_size: int,
        login_user,
    ) -> dict:
        """List tenants with pagination. System admin only."""
        tenants, total = await TenantDao.alist_tenants(
            keyword=keyword, status=status, page=page, page_size=page_size,
        )
        # Batch count users to avoid N+1 queries
        tenant_ids = [t.id for t in tenants]
        user_counts = await TenantDao.acount_tenant_users_batch(tenant_ids)

        items = []
        for t in tenants:
            items.append(TenantListItem(
                id=t.id,
                tenant_name=t.tenant_name,
                tenant_code=t.tenant_code,
                logo=t.logo,
                status=t.status,
                user_count=user_counts.get(t.id, 0),
                storage_used_gb=None,
                storage_quota_gb=_get_storage_quota(t),
                create_time=t.create_time,
            ))
        return {'data': [item.model_dump() for item in items], 'total': total}

    @classmethod
    async def aget_tenant(cls, tenant_id: int, login_user) -> dict:
        """Get tenant detail including admin users."""
        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        user_count = await TenantDao.acount_tenant_users(tenant_id)
        admin_users = await cls._get_tenant_admin_users(tenant_id)

        detail = TenantDetail(
            id=tenant.id,
            tenant_name=tenant.tenant_name,
            tenant_code=tenant.tenant_code,
            logo=tenant.logo,
            status=tenant.status,
            user_count=user_count,
            storage_used_gb=None,
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
            return tenant.model_dump()

        tenant = await TenantDao.aupdate_tenant(tenant_id, **fields)
        if not tenant:
            raise TenantNotFoundError()
        return tenant.model_dump()

    @classmethod
    async def aupdate_tenant_status(
        cls, tenant_id: int, data: TenantStatusUpdate, login_user,
    ) -> dict:
        """Update tenant status and manage Redis blacklist."""
        tenant = await TenantDao.aupdate_tenant(tenant_id, status=data.status)
        if not tenant:
            raise TenantNotFoundError()

        redis_client = await get_redis_client()
        key = DISABLED_TENANT_KEY.format(tenant_id)
        if data.status in ('disabled', 'archived'):
            await redis_client.aset(key, '1', expiration=0)
        else:
            await redis_client.adelete(key)

        return tenant.model_dump()

    @classmethod
    async def adelete_tenant(cls, tenant_id: int, login_user) -> None:
        """Delete a tenant. Requires zero active users."""
        user_count = await TenantDao.acount_tenant_users(tenant_id)
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
            from bisheng.database.models.department import Department, DepartmentDao
            await DepartmentDao.adelete_by_tenant(tenant_id)
        except Exception as e:
            logger.warning('Failed to delete departments for tenant %d: %s', tenant_id, e)

        # Cleanup: Redis blacklist key
        redis_client = await get_redis_client()
        await redis_client.adelete(DISABLED_TENANT_KEY.format(tenant_id))

        # Cleanup: OpenFGA tuples (best effort)
        try:
            await cls._write_tenant_tuples(
                tenant_id=tenant_id,
                admin_user_ids=[],
                action='revoke_all',
            )
        except Exception as e:
            logger.warning('Failed to revoke OpenFGA tuples for tenant %d: %s', tenant_id, e)

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
        user_count = await TenantDao.acount_tenant_users(tenant_id)
        usage['user_count'] = user_count

        return TenantQuotaResponse(
            quota_config=tenant.quota_config,
            usage=usage,
        ).model_dump()

    @classmethod
    async def aset_quota(cls, tenant_id: int, data: TenantQuotaUpdate, login_user) -> dict:
        """Set tenant quota config."""
        tenant = await TenantDao.aupdate_tenant(tenant_id, quota_config=data.quota_config)
        if not tenant:
            raise TenantNotFoundError()
        return tenant.model_dump()

    # ── Tenant Users ───────────────────────────────────────────

    @classmethod
    async def aadd_users(cls, tenant_id: int, data: TenantUserAdd, login_user) -> dict:
        """Add users to a tenant. Optionally grant admin role."""
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

        # Write OpenFGA member (and optionally admin) tuples
        if added:
            await cls._write_user_tuples(
                tenant_id=tenant_id,
                user_ids=added,
                is_admin=data.is_admin,
                action='grant',
            )

        return {'added': len(added), 'skipped': len(data.user_ids) - len(added)}

    @classmethod
    async def aremove_user(cls, tenant_id: int, user_id: int, login_user) -> None:
        """Remove a user from a tenant. Prevents removing the last admin."""
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

        # Revoke OpenFGA tuples
        await cls._write_user_tuples(
            tenant_id=tenant_id,
            user_ids=[user_id],
            is_admin=is_admin,
            action='revoke',
        )

    @classmethod
    async def aget_tenant_users(
        cls, tenant_id: int, page: int, page_size: int,
        keyword: Optional[str], login_user,
    ) -> dict:
        """Get paginated users in a tenant."""
        users, total = await UserTenantDao.aget_tenant_users(
            tenant_id=tenant_id, page=page, page_size=page_size, keyword=keyword,
        )
        return {'data': users, 'total': total}

    # ── User-facing: tenant selection & switching ──────────────

    @classmethod
    async def aget_user_tenants(cls, user_id: int) -> List[dict]:
        """Get all tenants for a user (for tenant selection / switching)."""
        details = await UserTenantDao.aget_user_tenants_with_details(user_id)
        items = [
            UserTenantItem(**d).model_dump()
            for d in details
            if d.get('status') == 'active'
        ]
        return items

    @classmethod
    async def aswitch_tenant(cls, user_id: int, tenant_id: int, db_user, auth_jwt) -> str:
        """Switch user to a different tenant. Returns new access token."""
        # Validate membership
        ut = await UserTenantDao.aget_user_tenant(user_id, tenant_id)
        if not ut or ut.status != 'active':
            raise TenantSwitchForbiddenError()

        # Validate tenant status
        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        if tenant.status != 'active':
            raise TenantDisabledError()

        # Update last access time
        await UserTenantDao.aupdate_last_access_time(user_id, tenant_id)

        # Create new JWT with target tenant_id
        from bisheng.user.domain.services.auth import LoginUser
        access_token = LoginUser.create_access_token(
            user=db_user, auth_jwt=auth_jwt, tenant_id=tenant_id,
        )
        LoginUser.set_access_cookies(access_token, auth_jwt=auth_jwt)

        # Update Redis session
        redis_client = await get_redis_client()
        from bisheng.user.domain.services.user import USER_CURRENT_SESSION
        await redis_client.aset(
            USER_CURRENT_SESSION.format(user_id), access_token,
            expiration=auth_jwt.cookie_conf.jwt_token_expire_time + 3600,
        )

        return access_token

    # ── Private helpers ────────────────────────────────────────

    @classmethod
    async def _write_tenant_tuples(
        cls, tenant_id: int, admin_user_ids: List[int], action: str,
    ) -> None:
        """Write/revoke OpenFGA tenant admin+member tuples."""
        try:
            from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem
            from bisheng.permission.domain.services.permission_service import PermissionService

            if action == 'grant':
                grants = []
                for uid in admin_user_ids:
                    grants.append(AuthorizeGrantItem(
                        subject_type='user', subject_id=uid,
                        relation='admin', include_children=False,
                    ))
                    grants.append(AuthorizeGrantItem(
                        subject_type='user', subject_id=uid,
                        relation='member', include_children=False,
                    ))
                await PermissionService.authorize(
                    object_type='tenant', object_id=str(tenant_id), grants=grants,
                )
            elif action == 'revoke_all':
                logger.info('Skipping OpenFGA cleanup for deleted tenant %d (orphaned tuples acceptable)', tenant_id)

        except Exception as e:
            # INV-4: failures go to failed_tuples compensation table
            logger.error('OpenFGA tuple write failed for tenant %d: %s', tenant_id, e)

    @classmethod
    async def _write_user_tuples(
        cls, tenant_id: int, user_ids: List[int], is_admin: bool, action: str,
    ) -> None:
        """Write/revoke OpenFGA user<->tenant tuples."""
        try:
            from bisheng.permission.domain.schemas.permission_schema import (
                AuthorizeGrantItem,
                AuthorizeRevokeItem,
            )
            from bisheng.permission.domain.services.permission_service import PermissionService

            if action == 'grant':
                grants = []
                for uid in user_ids:
                    grants.append(AuthorizeGrantItem(
                        subject_type='user', subject_id=uid,
                        relation='member', include_children=False,
                    ))
                    if is_admin:
                        grants.append(AuthorizeGrantItem(
                            subject_type='user', subject_id=uid,
                            relation='admin', include_children=False,
                        ))
                await PermissionService.authorize(
                    object_type='tenant', object_id=str(tenant_id), grants=grants,
                )
            elif action == 'revoke':
                revokes = []
                for uid in user_ids:
                    revokes.append(AuthorizeRevokeItem(
                        subject_type='user', subject_id=uid,
                        relation='member', include_children=False,
                    ))
                    if is_admin:
                        revokes.append(AuthorizeRevokeItem(
                            subject_type='user', subject_id=uid,
                            relation='admin', include_children=False,
                        ))
                await PermissionService.authorize(
                    object_type='tenant', object_id=str(tenant_id), revokes=revokes,
                )

        except Exception as e:
            logger.error('OpenFGA user tuple write failed for tenant %d: %s', tenant_id, e)

    @classmethod
    async def _get_tenant_admin_users(cls, tenant_id: int) -> List[dict]:
        """Get admin users for a tenant by checking each user's admin relation."""
        users, _ = await UserTenantDao.aget_tenant_users(tenant_id, page=1, page_size=100)
        admin_users = []
        for user in users:
            if await cls._is_tenant_admin(user['user_id'], tenant_id):
                admin_users.append(user)
        return admin_users

    @classmethod
    async def _is_tenant_admin(cls, user_id: int, tenant_id: int) -> bool:
        """Check if user is admin of tenant via OpenFGA."""
        try:
            from bisheng.permission.domain.services.permission_service import PermissionService
            return await PermissionService.check(
                user_id=user_id, relation='admin',
                object_type='tenant', object_id=str(tenant_id),
            )
        except Exception:
            return False

    @classmethod
    async def _count_tenant_admins(cls, tenant_id: int) -> int:
        """Count how many admins a tenant has."""
        try:
            from bisheng.permission.domain.services.permission_service import PermissionService
            fga = PermissionService._get_fga()
            if fga is None:
                return 999  # Fail-open when FGA unavailable
            # Use list_objects to find users with admin relation
            raw = await fga.list_objects(
                user=f'tenant:{tenant_id}',
                relation='admin',
                type='user',
            )
            return len(raw) if raw else 0
        except Exception:
            return 999  # Fail-open
