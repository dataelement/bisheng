"""QuotaService — three-level quota enforcement engine (F005).

Three-level quota calculation:
  1. Admin shortcircuit → -1 (unlimited)
  2. Role-level: multi-role takes max; any -1 → unlimited; missing key → default
  3. Tenant-level: hard limit caps effective via min(tenant_remaining, role_quota)

Quota values: -1 = unlimited, 0 = prohibited, positive int = upper limit.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Optional

from bisheng.common.errcode.role import QuotaExceededError, QuotaConfigInvalidError
from bisheng.database.models.role import RoleDao
from bisheng.database.models.tenant import TenantDao
from bisheng.user.domain.models.user_role import UserRoleDao

logger = logging.getLogger(__name__)

DEFAULT_ROLE_QUOTA: dict[str, int] = {
    'knowledge_space': 30,
    'knowledge_space_file': 500,  # GB
    'channel': 10,
    'channel_subscribe': 20,
    'workflow': -1,
    'assistant': -1,
    'tool': -1,
    'dashboard': -1,
}

# Tenant-level only quota keys (F016): not in DEFAULT_ROLE_QUOTA because these
# are not role-level limits, but still need to pass validate_quota_config.
_TENANT_ONLY_QUOTA_KEYS = {'storage_gb', 'user_count', 'model_tokens_monthly'}

VALID_QUOTA_KEYS = set(DEFAULT_ROLE_QUOTA.keys()) | _TENANT_ONLY_QUOTA_KEYS

# Resource counting SQL templates — keyed by {col}=:{param} placeholder.
# Shared between tenant-level and user-level counts.
_RESOURCE_COUNT_TEMPLATES: dict[str, str] = {
    'knowledge_space': "SELECT COUNT(*) FROM knowledge WHERE {col}=:{param} AND status != -1",
    'knowledge_space_file': "SELECT COALESCE(SUM(file_size), 0) FROM knowledgefile WHERE {col}=:{param} AND status IN (1,2)",
    'channel': "SELECT COUNT(*) FROM channel WHERE {col}=:{param} AND status='active'",
    'channel_subscribe': "SELECT COUNT(*) FROM channel WHERE {col}=:{param} AND status='active'",
    'workflow': "SELECT COUNT(*) FROM flow WHERE {col}=:{param} AND flow_type=10 AND status!=0",
    'assistant': "SELECT COUNT(*) FROM flow WHERE {col}=:{param} AND flow_type=5 AND status!=0",
    'tool': "SELECT COUNT(*) FROM gpts_tools WHERE {col}=:{param} AND is_delete=0",
    'dashboard': "SELECT COUNT(*) FROM flow WHERE {col}=:{param} AND flow_type=15 AND status!=0",
    # F016 T02: tenant-only resource types.
    # storage_gb: total bytes of active knowledge files; converted to GB in _count_resource.
    'storage_gb': "SELECT COALESCE(SUM(file_size), 0) FROM knowledgefile WHERE {col}=:{param} AND status IN (1,2)",
    # user_count: active users in the tenant; only meaningful when {col}='tenant_id'
    # (user-level count returns 0 because user_tenant.user_id column is the join, not filter).
    'user_count': (
        "SELECT COUNT(DISTINCT ut.user_id) FROM user_tenant ut "
        "INNER JOIN user u ON u.user_id = ut.user_id "
        "WHERE ut.{col}=:{param} AND ut.is_active=1 AND u.delete=0"
    ),
    # model_tokens_monthly: F017 dependency. Table llm_token_log may not exist
    # yet; _count_resource's try/except returns 0 on missing table (stub-safe).
    'model_tokens_monthly': (
        "SELECT COALESCE(SUM(total_tokens), 0) FROM llm_token_log "
        "WHERE {col}=:{param} AND created_at >= DATE_FORMAT(NOW(), '%Y-%m-01')"
    ),
}


class QuotaResourceType:
    """Supported resource types for quota enforcement."""
    KNOWLEDGE_SPACE = 'knowledge_space'
    KNOWLEDGE_SPACE_FILE = 'knowledge_space_file'
    CHANNEL = 'channel'
    CHANNEL_SUBSCRIBE = 'channel_subscribe'
    WORKFLOW = 'workflow'
    ASSISTANT = 'assistant'
    TOOL = 'tool'
    DASHBOARD = 'dashboard'
    # F016 T02: tenant-only.
    STORAGE_GB = 'storage_gb'
    USER_COUNT = 'user_count'
    MODEL_TOKENS_MONTHLY = 'model_tokens_monthly'


class QuotaService:
    """Stateless service for quota enforcement. All methods are @classmethod."""

    @classmethod
    async def get_effective_quota(
        cls,
        user_id: int,
        resource_type: str,
        tenant_id: int,
        login_user=None,
    ) -> int:
        """Three-level effective quota calculation.

        Returns -1 for unlimited, 0 for prohibited, or positive int limit.
        """
        if login_user and login_user.is_admin():
            return -1

        user_roles = await UserRoleDao.aget_user_roles(user_id)
        role_ids = [r.role_id for r in user_roles]

        if not role_ids:
            role_quota = DEFAULT_ROLE_QUOTA.get(resource_type, -1)
        else:
            roles = await RoleDao.aget_role_by_ids(role_ids)
            all_quotas = cls._compute_role_quotas(roles)
            role_quota = all_quotas.get(resource_type, DEFAULT_ROLE_QUOTA.get(resource_type, -1))
            if role_quota == -1:
                return -1

        return await cls._apply_tenant_cap(role_quota, tenant_id, resource_type)

    @classmethod
    async def _apply_tenant_cap(cls, role_quota: int, tenant_id: int, resource_type: str) -> int:
        """Apply tenant hard limit to role quota."""
        tenant = await TenantDao.aget_by_id(tenant_id)
        tenant_limit = (tenant.quota_config or {}).get(resource_type, -1) if tenant else -1

        if tenant_limit == -1:
            return role_quota

        tenant_used = await cls.get_tenant_resource_count(tenant_id, resource_type)
        tenant_remaining = max(tenant_limit - tenant_used, 0)

        if role_quota == -1:
            return tenant_remaining
        return min(tenant_remaining, role_quota)

    @classmethod
    async def check_quota(
        cls,
        user_id: int,
        resource_type: str,
        tenant_id: int,
        login_user=None,
    ) -> bool:
        """Check if user can create one more resource.

        Returns True if allowed.
        Raises QuotaExceededError if quota exhausted (AC-20).
        """
        effective = await cls.get_effective_quota(user_id, resource_type, tenant_id, login_user)
        if effective == -1:
            return True

        user_used = await cls.get_user_resource_count(user_id, resource_type)
        if user_used >= effective:
            raise QuotaExceededError(
                msg=f'Resource quota exceeded for {resource_type}',
            )
        return True

    @classmethod
    async def get_all_effective_quotas(
        cls,
        user_id: int,
        tenant_id: int,
        login_user=None,
    ) -> list:
        """Get effective quotas for all resource types (AC-15).

        Uses asyncio.gather to batch resource count queries.
        """
        from bisheng.role.domain.schemas.role_schema import EffectiveQuotaItem

        is_admin = login_user and login_user.is_admin()

        if is_admin:
            role_quotas = {k: -1 for k in DEFAULT_ROLE_QUOTA}
        else:
            user_roles = await UserRoleDao.aget_user_roles(user_id)
            role_ids = [r.role_id for r in user_roles]
            if role_ids:
                roles = await RoleDao.aget_role_by_ids(role_ids)
                role_quotas = cls._compute_role_quotas(roles)
            else:
                role_quotas = dict(DEFAULT_ROLE_QUOTA)

        tenant = await TenantDao.aget_by_id(tenant_id)
        tenant_config = (tenant.quota_config or {}) if tenant else {}

        # Batch all resource count queries concurrently
        resource_types = list(DEFAULT_ROLE_QUOTA.keys())
        tenant_counts, user_counts = await asyncio.gather(
            asyncio.gather(*(cls.get_tenant_resource_count(tenant_id, rt) for rt in resource_types)),
            asyncio.gather(*(cls.get_user_resource_count(user_id, rt) for rt in resource_types)),
        )

        items = []
        for i, resource_type in enumerate(resource_types):
            role_q = role_quotas.get(resource_type, DEFAULT_ROLE_QUOTA.get(resource_type, -1))
            tenant_q = tenant_config.get(resource_type, -1)
            tenant_used = tenant_counts[i]
            user_used = user_counts[i]

            if is_admin:
                effective = -1
            elif tenant_q == -1:
                effective = role_q
            else:
                tenant_remaining = max(tenant_q - tenant_used, 0)
                effective = tenant_remaining if role_q == -1 else min(tenant_remaining, role_q)

            items.append(EffectiveQuotaItem(
                resource_type=resource_type,
                role_quota=role_q,
                tenant_quota=tenant_q,
                tenant_used=tenant_used,
                user_used=user_used,
                effective=effective,
            ))
        return items

    @classmethod
    def role_knowledge_space_file_limit_gb(cls, role) -> int:
        """Single role: storage quota (GB) from quota_config vs deprecated column.

        Returns ``-1`` when quota_config marks unlimited for this role.
        """
        qc = (role.quota_config or {}).get('knowledge_space_file')
        if qc == -1:
            return -1
        legacy = getattr(role, 'knowledge_space_file_limit', None) or 0
        candidates: list[int] = []
        if qc is not None and isinstance(qc, int) and qc > 0:
            candidates.append(qc)
        if isinstance(legacy, int) and legacy > 0:
            candidates.append(legacy)
        return max(candidates) if candidates else 0

    @classmethod
    def _compute_role_quotas(cls, roles) -> dict:
        """Compute multi-role quota: take max per resource type, -1 wins (AC-16)."""
        result = {}
        for resource_type in DEFAULT_ROLE_QUOTA:
            max_q = None
            for role in roles:
                q = (role.quota_config or {}).get(resource_type)
                if q is None:
                    q = DEFAULT_ROLE_QUOTA.get(resource_type, -1)
                if q == -1:
                    max_q = -1
                    break
                if max_q is None or q > max_q:
                    max_q = q
            result[resource_type] = max_q if max_q is not None else DEFAULT_ROLE_QUOTA.get(resource_type, -1)
        return result

    @classmethod
    async def _count_resource(cls, col: str, val, resource_type: str) -> int:
        """Shared resource counting — used by both tenant and user counts."""
        from bisheng.core.database import get_async_db_session
        from sqlalchemy import text

        template = _RESOURCE_COUNT_TEMPLATES.get(resource_type)
        if not template:
            return 0

        param = 'id_val'
        sql = template.format(col=col, param=param)
        try:
            async with get_async_db_session() as session:
                result = await session.execute(text(sql), {param: val})
                count = result.scalar() or 0
                if resource_type in ('knowledge_space_file', 'storage_gb'):
                    count = count // (1024 * 1024 * 1024)
                return count
        except Exception as e:
            logger.warning('Failed to count resource %s for %s=%s: %s', resource_type, col, val, e)
            return 0

    @classmethod
    async def get_tenant_resource_count(cls, tenant_id: int, resource_type: str) -> int:
        """Count tenant-level resource usage."""
        return await cls._count_resource('tenant_id', tenant_id, resource_type)

    @classmethod
    async def get_user_resource_count(cls, user_id: int, resource_type: str) -> int:
        """Count user-level resource usage."""
        return await cls._count_resource('user_id', user_id, resource_type)

    @classmethod
    def validate_quota_config(cls, quota_config: Optional[dict]) -> None:
        """Validate quota_config values (AC-10c).

        Valid keys: those in VALID_QUOTA_KEYS.
        Valid values: -1 (unlimited), 0 (prohibited), positive integer.
        Raises QuotaConfigInvalidError on invalid keys or values.
        """
        if not quota_config:
            return
        for key, value in quota_config.items():
            if key not in VALID_QUOTA_KEYS:
                raise QuotaConfigInvalidError(
                    msg=f'quota_config contains unknown key: {key}',
                )
            if isinstance(value, bool) or not isinstance(value, int):
                raise QuotaConfigInvalidError(
                    msg=f'quota_config[{key}] must be an integer, got {type(value).__name__}',
                )
            if value < -1:
                raise QuotaConfigInvalidError(
                    msg=f'quota_config[{key}] must be -1, 0, or positive integer, got {value}',
                )


def require_quota(resource_type: str):
    """Decorator for resource creation endpoints (AD-04).

    Usage:
        @require_quota(QuotaResourceType.KNOWLEDGE_SPACE)
        async def create_knowledge_space(*, login_user: LoginUser = Depends(...)):
            ...

    Note: Defined in F005, applied to resource endpoints in F008.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            login_user = kwargs.get('login_user')
            if login_user:
                await QuotaService.check_quota(
                    user_id=login_user.user_id,
                    resource_type=resource_type,
                    tenant_id=login_user.tenant_id,
                    login_user=login_user,
                )
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)
        return wrapper
    return decorator
