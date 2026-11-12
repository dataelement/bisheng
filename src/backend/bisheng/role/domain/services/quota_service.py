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
from typing import Union

from bisheng.common.errcode.role import QuotaConfigInvalidError
from bisheng.common.errcode.tenant_quota import (
    QuotaResponsibilityChangedError,
    QuotaUsageUnavailableError,
    TenantQuotaExceededError,
    TenantRoleQuotaExceededError,
    TenantStorageQuotaExceededError,
)
from bisheng.database.models.tenant import TenantDao
from bisheng.role.application.effective_roles import load_effective_roles
from bisheng.role.domain.repositories.quota_repository import QuotaRepository

logger = logging.getLogger(__name__)

DEFAULT_ROLE_QUOTA: dict[str, int] = {
    "knowledge_space": 50,
    "knowledge_space_file": 500,  # GB
    "knowledge_space_subscribe": 100,
    "channel": 10,
    "channel_subscribe": 20,
    "info_source_subscribe": 200,
    "workflow": -1,
    "assistant": -1,
    "tool": -1,
    "dashboard": -1,
}

# Tenant-level only quota keys (F016): not in DEFAULT_ROLE_QUOTA because these
# are not role-level limits, but still need to pass validate_quota_config.
_TENANT_ONLY_QUOTA_KEYS = {"storage_gb", "user_count", "model_tokens_monthly"}

# Stored in role.quota_config JSON but not numeric quotas (menu UX flags).
# ``menu_approval_mode`` is the legacy global flag, kept for back-compat; the
# per-area flags (``_workbench`` / ``_admin``) supersede it (see F0xx role menu
# scope split). Reads fall back to the legacy key until a role is re-saved.
_MENU_APPROVAL_MODE_KEYS = {
    "menu_approval_mode",
    "menu_approval_mode_workbench",
    "menu_approval_mode_admin",
}
_ROLE_QUOTA_METADATA_KEYS = set(_MENU_APPROVAL_MODE_KEYS)

VALID_QUOTA_KEYS = set(DEFAULT_ROLE_QUOTA.keys()) | _TENANT_ONLY_QUOTA_KEYS | _ROLE_QUOTA_METADATA_KEYS


class QuotaResourceType:
    """Supported resource types for quota enforcement."""

    KNOWLEDGE_SPACE = "knowledge_space"
    KNOWLEDGE_SPACE_FILE = "knowledge_space_file"
    KNOWLEDGE_SPACE_SUBSCRIBE = "knowledge_space_subscribe"
    CHANNEL = "channel"
    CHANNEL_SUBSCRIBE = "channel_subscribe"
    INFO_SOURCE_SUBSCRIBE = "info_source_subscribe"
    WORKFLOW = "workflow"
    ASSISTANT = "assistant"
    TOOL = "tool"
    DASHBOARD = "dashboard"
    # F016 T02: tenant-only.
    STORAGE_GB = "storage_gb"
    USER_COUNT = "user_count"
    MODEL_TOKENS_MONTHLY = "model_tokens_monthly"


class QuotaService:
    """Stateless service for quota enforcement. All methods are @classmethod."""

    @classmethod
    async def get_effective_quota(
        cls,
        user_id: int,
        resource_type: str,
        tenant_id: int,
        login_user=None,
    ) -> Union[int, float]:
        """Three-level effective quota calculation.

        Returns -1 for unlimited, 0 for prohibited, or a positive limit (``float`` GB
        for ``knowledge_space_file`` when configured with decimals; otherwise ``int``).
        """
        if login_user and login_user.is_admin():
            return -1

        policy = await cls._budget_policy(user_id, tenant_id)
        role_quota = cls._compute_role_quotas(policy.roles).get(
            resource_type, DEFAULT_ROLE_QUOTA.get(resource_type, -1)
        )

        return await cls._apply_tenant_cap(role_quota, tenant_id, resource_type)

    @staticmethod
    async def _budget_policy(user_id: int, tenant_id: int):
        policy = await load_effective_roles(user_id)
        if policy.home_tenant_id != tenant_id:
            raise QuotaResponsibilityChangedError()
        return policy

    @classmethod
    async def _apply_tenant_cap(
        cls, role_quota: Union[int, float], tenant_id: int, resource_type: str
    ) -> Union[int, float]:
        """Apply tenant hard limit to role quota (single-tenant view).

        v2.5.0 baseline — retained for `get_effective_quota` which powers the
        front-end `/me/quotas` endpoint. The Tenant-tree-aware variant is
        `_apply_tenant_chain_cap` (F016 T04, used only by `check_quota`).
        """
        tenant = await TenantDao.aget_by_id(tenant_id)
        if tenant is None or tenant.status != "active":
            raise QuotaUsageUnavailableError(usage_state="UNAVAILABLE")
        tenant_limit = (tenant.quota_config or {}).get(resource_type, -1)

        if tenant_limit == -1:
            return role_quota

        tenant_used = await cls.get_tenant_resource_count(tenant_id, resource_type)
        tenant_remaining = max(tenant_limit - tenant_used, 0)

        if role_quota == -1:
            return tenant_remaining
        return min(tenant_remaining, role_quota)

    @classmethod
    async def _apply_tenant_chain_cap(
        cls,
        role_quota: Union[int, float],
        tenant_id: int,
        resource_type: str,
    ) -> tuple[Union[int, float], tuple[int, str, Union[int, float], Union[int, float], str] | None]:
        """F016 T04 — Tenant-chain hard-limit check (leaf + Root if Child).

        Returns ``(effective_remaining, blocker)``:
          - ``effective_remaining`` — min of all chain nodes' remaining values,
            further min with ``role_quota``; ``-1`` means unlimited across
            chain + role.
          - ``blocker`` — ``None`` if chain passes; otherwise
            ``(blocker_tenant_id, reason, used, limit, tenant_name)`` where
            ``reason`` is one of:
              * ``'tenant_limit'`` — leaf (Child) tenant limit exhausted
              * ``'root_hardcap'`` — Root tenant hard-cap exhausted; for
                Child users this means the group-wide ceiling is reached
                (AC-08, msg variant must contain '集团总量已耗尽').
            ``used`` and ``limit`` are tenant-level usage and cap (in the unit
            the resource_type uses — GB for storage), surfaced so the caller
            can format human-readable error messages.

        Storage cap aliasing: when ``resource_type`` is ``'knowledge_space_file'``
        or ``'storage_gb'``, the tenant-level cap is read from the canonical
        ``'storage_gb'`` key on ``tenant.quota_config``. Tenant management UI
        only writes ``storage_gb`` (see TenantQuotaDialog), so this alias keeps
        the role-level decorator (``KNOWLEDGE_SPACE_FILE``) compatible with the
        tenant-level field name.

        Implements INV-T9 (Root usage = self + Σ active Child) via
        ``_aggregate_root_usage``, and INV-T6 (shared-resource sibling
        isolation) via ``_count_usage_strict``.
        """
        # Tenant metadata lookups cross tenant boundaries (leaf + parent Root);
        # wrap in bypass_tenant_filter() so any future ORM-event-listener
        # injection on the `tenant` table (were it ever to gain a tenant_id
        # column) cannot silently filter them out. The Tenant model currently
        # has no tenant_id column so this is defensive, matching the
        # project-wide convention (see TenantDao.aget_children_ids_active).
        from bisheng.core.context.tenant import bypass_tenant_filter

        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
            if not tenant or tenant.status != "active":
                raise QuotaUsageUnavailableError(usage_state="UNAVAILABLE")

            # MVP 2-layer: chain is [leaf] or [leaf, Root]; F011 INV-T1.
            chain: list = [tenant]
            if tenant.parent_tenant_id is not None:
                root = await TenantDao.aget_by_id(tenant.parent_tenant_id)
                if not root or root.status != "active":
                    raise QuotaUsageUnavailableError(usage_state="UNAVAILABLE")
                chain.append(root)

        # Tenant config writes "storage_gb"; role config writes "knowledge_space_file".
        # When checking storage from the role-level decorator, alias to storage_gb.
        cap_key = "storage_gb" if resource_type in ("knowledge_space_file", "storage_gb") else resource_type

        tenant_min_remaining: Union[int, float] = -1
        for t in chain:
            limit = (t.quota_config or {}).get(cap_key, -1)
            if limit == -1:
                continue
            is_root = t.parent_tenant_id is None
            used = (
                await cls._aggregate_root_usage(t.id, resource_type)
                if is_root
                else await cls._count_usage_strict(t.id, resource_type)
            )
            remaining = max(limit - used, 0)
            if remaining == 0:
                reason = "root_hardcap" if is_root else "tenant_limit"
                return 0, (t.id, reason, used, limit, t.tenant_name or "")
            tenant_min_remaining = remaining if tenant_min_remaining == -1 else min(tenant_min_remaining, remaining)

        if role_quota == -1:
            return tenant_min_remaining, None
        if tenant_min_remaining == -1:
            return role_quota, None
        return min(tenant_min_remaining, role_quota), None

    @staticmethod
    def _make_storage_quota_error(
        blocker: tuple[int, str, Union[int, float], Union[int, float], str],
        resource_type: str,
    ) -> TenantStorageQuotaExceededError:
        blocker_tid, reason, used, limit, tenant_name = blocker
        return TenantStorageQuotaExceededError(
            msg=(f"Storage quota exceeded at tenant {blocker_tid} ({reason}) for {resource_type}: {used}/{limit} GB"),
            used_gb=used,
            quota_gb=limit,
            tenant_name=tenant_name,
            tenant_id=blocker_tid,
            reason=reason,
        )

    @classmethod
    async def check_quota(
        cls,
        user_id: int,
        resource_type: str,
        tenant_id: int,
        login_user=None,
        delta: int | float = 1,
        tenant_delta: int | float | None = None,
    ) -> bool:
        """Check if user can create one more resource (F016 T04 Tenant-tree aware).

        Enforcement order (fail-fast):
          1. Admin short-circuit (INV-T5 global super admin bypasses all quota).
          2. Tenant-chain check via ``_apply_tenant_chain_cap``:
               - blocker.reason == 'tenant_limit' → ``TenantQuotaExceededError(19401)``
               - blocker.reason == 'root_hardcap' → ``TenantQuotaExceededError(19401)``
                 with msg containing '集团总量已耗尽' (AC-08).
               - If resource_type is storage-related ('storage_gb' or
                 'knowledge_space_file'), upgrade exception to
                 ``TenantStorageQuotaExceededError(19403)`` (AC-04).
          3. Role-quota check on top of Tenant-chain effective:
               - ``TenantRoleQuotaExceededError(19402)``.

        Returns True when allowed. Raises one of the 194xx subclasses when
        exceeded.
        """
        if login_user and login_user.is_admin():
            return True

        if isinstance(delta, bool) or not isinstance(delta, (int, float)) or delta < 0:
            raise ValueError("Quota delta must be a nonnegative number")
        if tenant_delta is not None and tenant_delta > delta:
            raise ValueError("Tenant delta cannot exceed this resource owner's delta")
        if delta == 0:
            return True
        tenant_delta = delta if tenant_delta is None else tenant_delta
        if isinstance(tenant_delta, bool) or not isinstance(tenant_delta, (int, float)) or tenant_delta < 0:
            raise ValueError("Tenant quota delta must be a nonnegative number")
        policy = await cls._budget_policy(user_id, tenant_id)
        role_quota = cls._compute_role_quotas(policy.roles).get(
            resource_type, DEFAULT_ROLE_QUOTA.get(resource_type, -1)
        )
        tenant_remaining, blocker = (-1, None)
        if tenant_delta > 0:
            tenant_remaining, blocker = await cls._apply_tenant_chain_cap(-1, tenant_id, resource_type)

        if blocker is not None:
            blocker_tid, reason, used, limit, tenant_name = blocker
            if resource_type in ("storage_gb", "knowledge_space_file"):
                # kwargs are flattened into response.data by main.handle_http_exception;
                # the platform i18n template `errors.19403` consumes used_gb / quota_gb
                # to render "当前企业存储配额已耗尽（X/Y GB）".
                raise cls._make_storage_quota_error(blocker, resource_type)
            if reason == "root_hardcap":
                raise TenantQuotaExceededError(
                    msg=(f"集团总量已耗尽 (Root tenant {blocker_tid} quota for {resource_type} reached)"),
                    used=used,
                    quota=limit,
                    tenant_name=tenant_name,
                    tenant_id=blocker_tid,
                    reason=reason,
                )
            raise TenantQuotaExceededError(
                msg=f"Tenant {blocker_tid} quota exceeded for {resource_type}",
                used=used,
                quota=limit,
                tenant_name=tenant_name,
                tenant_id=blocker_tid,
                reason=reason,
            )

        if tenant_remaining != -1 and tenant_delta > tenant_remaining:
            if resource_type in ("storage_gb", "knowledge_space_file"):
                raise TenantStorageQuotaExceededError()
            raise TenantQuotaExceededError()
        if role_quota == -1:
            return True
        user_used = await cls.get_user_resource_count(user_id, resource_type, tenant_id=tenant_id)
        if user_used + delta > role_quota + (1e-9 if resource_type == "knowledge_space_file" else 0):
            raise TenantRoleQuotaExceededError(used=user_used, quota=role_quota, resource_type=resource_type)
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
            role_quotas = dict.fromkeys(DEFAULT_ROLE_QUOTA, -1)
        else:
            policy = await cls._budget_policy(user_id, tenant_id)
            role_quotas = cls._compute_role_quotas(policy.roles)

        tenant = await TenantDao.aget_by_id(tenant_id)
        tenant_config = (tenant.quota_config or {}) if tenant else {}

        # Batch all resource count queries concurrently
        resource_types = list(DEFAULT_ROLE_QUOTA.keys())
        tenant_counts, user_counts = await asyncio.gather(
            asyncio.gather(*(cls.get_tenant_resource_count(tenant_id, rt) for rt in resource_types)),
            asyncio.gather(*(cls.get_user_resource_count(user_id, rt, tenant_id=tenant_id) for rt in resource_types)),
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

            if is_admin:
                available = -1
            else:
                tenant_remaining, _ = await cls._apply_tenant_chain_cap(-1, tenant_id, resource_type)
                role_remaining = -1 if role_q == -1 else max(role_q - user_used, 0)
                finite = [value for value in (role_remaining, tenant_remaining) if value != -1]
                available = min(finite) if finite else -1

            items.append(
                EffectiveQuotaItem(
                    resource_type=resource_type,
                    role_quota=role_q,
                    tenant_quota=tenant_q,
                    tenant_used=tenant_used,
                    user_used=user_used,
                    effective=effective,
                    available=available,
                )
            )
        return items

    @classmethod
    def role_knowledge_space_file_limit_gb(cls, role) -> float:
        """Single role: storage quota (GB) from quota_config vs deprecated column.

        Returns ``-1.0`` when quota_config marks unlimited for this role.
        ``0.0`` means no positive cap from this role row (merge with other roles / default).
        """
        qc = (role.quota_config or {}).get("knowledge_space_file")
        if qc == -1:
            return -1.0
        candidates: list[float] = []
        if qc is not None and isinstance(qc, (int, float)) and not isinstance(qc, bool):
            g = float(qc)
            if g > 0:
                candidates.append(round(g, 1))
        return max(candidates) if candidates else 0.0

    @classmethod
    def _aggregate_knowledge_space_file_limit_gb(cls, roles) -> float:
        """Multi-role MIN for knowledge space upload (GB); ``-1`` = unlimited.

        Per product rule the effective cap is the STRICTEST (smallest) finite
        quota across the user's roles. ``-1`` (unlimited) is treated as +∞: it is
        ignored whenever any finite cap exists, and only wins when every role
        that sets this quota is unlimited.
        """
        if not roles:
            return float(DEFAULT_ROLE_QUOTA["knowledge_space_file"])
        min_gb: float | None = None
        saw_unlimited = False
        for role in roles:
            g = cls.role_knowledge_space_file_limit_gb(role)
            if g == -1.0:
                saw_unlimited = True  # +∞: never the min unless it is the only kind
                continue
            if g > 0:
                min_gb = g if min_gb is None else min(min_gb, g)
        if min_gb is not None:
            return round(float(min_gb), 1)
        if saw_unlimited:
            return -1.0  # every role that sets this quota is unlimited
        return float(DEFAULT_ROLE_QUOTA["knowledge_space_file"])

    @staticmethod
    def _knowledge_space_quota_gb_to_bytes(gb: float) -> int:
        g = round(float(gb), 1)
        return int(round(g * (1024**3)))

    @classmethod
    async def get_tenant_storage_used_bytes(cls, tenant_id: int | None) -> int:
        """Tenant-level storage used in bytes (root aggregates children, leaf strict).

        Shares the SQL template ``storage_gb`` with the quota interceptor so
        listing UI and write-path checks stay in lock-step. No admin
        short-circuit — super admin writes also count toward the target tenant.
        """
        if tenant_id is None:
            raise QuotaUsageUnavailableError(usage_state="UNAVAILABLE")
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.models.tenant import TenantDao

        with bypass_tenant_filter():
            tenant = await TenantDao.aget_by_id(tenant_id)
        if not tenant:
            raise QuotaUsageUnavailableError(usage_state="UNAVAILABLE")
        used_gb = (
            await cls._aggregate_root_usage(tenant_id, "storage_gb")
            if tenant.parent_tenant_id is None
            else await cls._count_usage_strict(tenant_id, "storage_gb")
        )
        return int(round(float(used_gb) * (1024**3)))

    @classmethod
    async def get_tenant_storage_remaining_bytes(
        cls,
        tenant_id: int | None,
    ) -> int | None:
        """Tenant-chain storage remaining in bytes for the write path.

        Reuses ``_apply_tenant_chain_cap`` so that Root + leaf caps and the
        ``storage_gb`` alias are honoured. Behaviour:

        * Chain blocker (any node already exhausted) → raises
          ``TenantStorageQuotaExceededError(19403)`` directly. Callers do not
          need to re-check ``used >= limit``.
        * Effective ``-1`` (no cap on the chain) → returns ``None``.
        * Otherwise → returns remaining bytes (effective_gb × 1024³).

        No admin short-circuit on purpose: tenant storage policy applies to
        everyone, including global super admins writing into a child tenant.
        """
        if tenant_id is None:
            return None
        effective, blocker = await cls._apply_tenant_chain_cap(
            -1,
            tenant_id,
            "storage_gb",
        )
        if blocker is not None:
            raise cls._make_storage_quota_error(blocker, "storage_gb")
        if effective == -1:
            return None
        return int(round(float(effective) * (1024**3)))

    @classmethod
    async def get_knowledge_space_upload_limit_bytes(cls, login_user) -> int | None:
        """Total upload cap in bytes for knowledge-space files (role max × tenant chain).

        ``None`` means unlimited. Tenant storage exhaustion raises 19403 so
        callers do not misreport tenant policy as an account upload-cap error.
        """
        if login_user and login_user.is_admin():
            return None
        user_id = login_user.user_id
        tenant_id = login_user.tenant_id
        policy = await cls._budget_policy(user_id, tenant_id)
        role_gb = cls._aggregate_knowledge_space_file_limit_gb(policy.roles)
        if role_gb == -1:
            eff, blocker = await cls._apply_tenant_chain_cap(-1, tenant_id, "knowledge_space_file")
            if blocker is not None:
                raise cls._make_storage_quota_error(blocker, "knowledge_space_file")
            if eff == -1:
                return None
            return cls._knowledge_space_quota_gb_to_bytes(float(eff))
        eff, blocker = await cls._apply_tenant_chain_cap(role_gb, tenant_id, "knowledge_space_file")
        if blocker is not None:
            raise cls._make_storage_quota_error(blocker, "knowledge_space_file")
        return cls._knowledge_space_quota_gb_to_bytes(float(eff))

    @classmethod
    def _compute_role_quotas(cls, roles) -> dict:
        """Compute multi-role quota: take max per resource type, -1 wins (AC-16)."""
        result = {}
        for resource_type in DEFAULT_ROLE_QUOTA:
            if resource_type == "knowledge_space_file":
                result[resource_type] = cls._aggregate_knowledge_space_file_limit_gb(roles)
                continue
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
    async def _count_resource(cls, col: str, val, resource_type: str, *, tenant_id: int | None = None):
        if col == "tenant_id":
            return await QuotaRepository.count(int(val), resource_type)
        if col != "user_id":
            raise ValueError("Unknown usage subject")
        if tenant_id is None:
            from bisheng.user.application.policy_bindings import read_policy_subject

            tenant_id = (await read_policy_subject(int(val))).home_tenant_id
        return await QuotaRepository.count(tenant_id, resource_type, user_id=int(val))

    @classmethod
    async def _distinct_info_source_ids(cls, col: str, val, *, tenant_id: int | None = None):
        if col == "tenant_id":
            return await QuotaRepository.source_ids(int(val))
        if col != "user_id":
            raise ValueError("Unknown usage subject")
        if tenant_id is None:
            from bisheng.user.application.policy_bindings import read_policy_subject

            tenant_id = (await read_policy_subject(int(val))).home_tenant_id
        return await QuotaRepository.source_ids(tenant_id, user_id=int(val))

    @classmethod
    async def check_info_source_subscribe_limit(
        cls,
        user_id: int,
        tenant_id: int,
        candidate_source_ids,
        login_user=None,
    ) -> None:
        """Enforce the ``info_source_subscribe`` quota before adding sources.

        Usage counts DEDUPED sources across the user's channels, so the
        candidate list is merged with the current set before comparing —
        reusing an already-counted source never consumes an extra slot.
        ``0`` therefore blocks any addition; admins / ``-1`` pass through.
        Raises ``TenantRoleQuotaExceededError(19402)`` when exceeded.
        """
        if not candidate_source_ids:
            return
        used_ids = await cls._distinct_info_source_ids("user_id", user_id, tenant_id=tenant_id)
        candidates = {sid for sid in candidate_source_ids if sid}
        delta = len(candidates - used_ids)
        if delta == 0:
            return
        policy = await load_effective_roles(user_id)
        if policy.is_identity_admin:
            return  # Existing budget-owner super-admin exemption.
        if policy.home_tenant_id != tenant_id:
            raise QuotaResponsibilityChangedError()
        if login_user and login_user.is_admin():
            return
        role_limit = cls._compute_role_quotas(policy.roles)[QuotaResourceType.INFO_SOURCE_SUBSCRIBE]
        if role_limit != -1 and len(used_ids) + delta > role_limit:
            raise TenantRoleQuotaExceededError(used=len(used_ids), quota=role_limit)
        tenant_ids = await cls._distinct_info_source_ids("tenant_id", tenant_id)
        tenant_delta = len(candidates - tenant_ids)
        if tenant_delta:
            remaining, blocker = await cls._apply_tenant_chain_cap(
                -1, tenant_id, QuotaResourceType.INFO_SOURCE_SUBSCRIBE
            )
            if blocker is not None or (remaining != -1 and tenant_delta > remaining):
                raise TenantQuotaExceededError()

    @classmethod
    async def get_tenant_resource_count(cls, tenant_id: int, resource_type: str) -> int | float:
        return await cls._count_resource("tenant_id", tenant_id, resource_type)

    @classmethod
    async def get_user_resource_count(
        cls, user_id: int, resource_type: str, *, tenant_id: int | None = None
    ) -> int | float:
        return await cls._count_resource("user_id", user_id, resource_type, tenant_id=tenant_id)

    # -----------------------------------------------------------------------
    # F016 T03: Tenant-tree quota counting helpers.
    # -----------------------------------------------------------------------

    @classmethod
    async def _count_usage_strict(cls, tenant_id: int, resource_type: str) -> int:
        """Bind each chain node independently before the scoped ORM count."""
        from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope

        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            return await cls.get_tenant_resource_count(tenant_id, resource_type)

    @classmethod
    async def _aggregate_root_usage(cls, root_id: int, resource_type: str) -> int:
        """Root usage = Root self + Σ all active Child usage (INV-T9, AC-07).

        Only ``status='active'`` Children count; ``disabled / archived / orphaned``
        are excluded because those tenants can no longer create resources and the
        quota semantics treat them as "exited the pool" (spec §5).

        Uses ``asyncio.gather`` to parallelize per-child counts and avoid N+1.
        """
        from bisheng.database.models.tenant import TenantDao

        root_self = await cls._count_usage_strict(root_id, resource_type)
        child_ids = await TenantDao.aget_children_ids_active(root_id)
        if not child_ids:
            return root_self
        child_counts = await asyncio.gather(
            *(cls._count_usage_strict(cid, resource_type) for cid in child_ids),
        )
        return root_self + sum(child_counts)

    @classmethod
    async def get_storage_used_gb_batch(
        cls,
        tenant_ids: list[int],
    ) -> dict[int, float]:
        """Batch tenant storage_gb usage for the tenant management UI.

        Root rows aggregate self + Σ active children (INV-T9); leaf rows use
        strict-equality count (INV-T6). Both paths share the SQL template
        ``storage_gb`` (file_source IN ('channel','space_upload')) so the displayed value matches what
        the quota interceptor enforces on writes.

        Returns ``{tid: gb_float}`` with 0.0 for tenants that have no usage.
        Tenant ids that do not exist are omitted from the map.
        """
        if not tenant_ids:
            return {}
        from bisheng.database.models.tenant import TenantDao

        tenants = await TenantDao.aget_by_ids(tenant_ids)
        if not tenants:
            return {}

        async def _one(t) -> tuple[int, float]:
            is_root = t.parent_tenant_id is None
            used = (
                await cls._aggregate_root_usage(t.id, "storage_gb")
                if is_root
                else await cls._count_usage_strict(t.id, "storage_gb")
            )
            return t.id, float(used)

        rows = await asyncio.gather(*(_one(t) for t in tenants))
        return dict(rows)

    # GB-valued quotas: -1 (unlimited) or 0.1~999 with at most 1 decimal place.
    # ``storage_gb`` (tenant-level) and ``knowledge_space_file`` (role-level)
    # share the same value shape so the management UI can use one input control.
    _GB_FLOAT_QUOTA_KEYS = frozenset({"storage_gb", "knowledge_space_file"})

    # Bounded integer quotas: inclusive [lo, hi]. Unlike open-ended int quotas,
    # ``-1`` (unlimited) is NOT a legal value here — the product fixes the range.
    _BOUNDED_INT_QUOTA_RANGES: dict[str, tuple[int, int]] = {
        "info_source_subscribe": (0, 10000),
    }

    @staticmethod
    def _validate_gb_float_quota(key: str, value) -> None:
        """GB float quota: -1 (unlimited) or 0.1~999 with at most 1 decimal."""
        if value == -1:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise QuotaConfigInvalidError(
                msg=f"quota_config[{key}] must be -1 or a number, got {type(value).__name__}",
            )
        num = float(value)
        r = round(num, 1)
        if abs(r - num) > 1e-6:
            raise QuotaConfigInvalidError(
                msg=f"quota_config[{key}] allows at most one decimal place, got {value!r}",
            )
        if r < 0.1 or r > 99999:
            raise QuotaConfigInvalidError(
                msg=f"quota_config[{key}] must be -1 or between 0.1 and 99999 (GB), got {value}",
            )

    @classmethod
    def _validate_bounded_int_quota(cls, key: str, value, bounds: tuple[int, int]) -> None:
        """Bounded integer quota: plain int within inclusive [lo, hi]."""
        lo, hi = bounds
        if isinstance(value, bool) or not isinstance(value, int):
            raise QuotaConfigInvalidError(
                msg=f"quota_config[{key}] must be an integer, got {type(value).__name__}",
            )
        if value < lo or value > hi:
            raise QuotaConfigInvalidError(
                msg=f"quota_config[{key}] must be between {lo} and {hi}, got {value}",
            )

    @classmethod
    def validate_quota_config(cls, quota_config: dict | None) -> None:
        """Validate quota_config values (AC-10c).

        Valid keys: those in VALID_QUOTA_KEYS.
        Valid values: depend on key — GB-valued keys allow ``-1`` or 0.1~999
        with one decimal place; the rest accept ``-1``, ``0``, or positive int.
        Raises QuotaConfigInvalidError on invalid keys or values.
        """
        if not quota_config:
            return
        for key, value in quota_config.items():
            if key not in VALID_QUOTA_KEYS:
                raise QuotaConfigInvalidError(
                    msg=f"quota_config contains unknown key: {key}",
                )
            if key in _MENU_APPROVAL_MODE_KEYS:
                if isinstance(value, bool):
                    continue
                if isinstance(value, int) and value in (0, 1):
                    continue
                raise QuotaConfigInvalidError(
                    msg=f"quota_config[{key}] must be boolean or 0/1, got {value!r}",
                )
            if key in cls._GB_FLOAT_QUOTA_KEYS:
                cls._validate_gb_float_quota(key, value)
                continue
            bounded_range = cls._BOUNDED_INT_QUOTA_RANGES.get(key)
            if bounded_range is not None:
                cls._validate_bounded_int_quota(key, value, bounded_range)
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise QuotaConfigInvalidError(
                    msg=f"quota_config[{key}] must be an integer, got {type(value).__name__}",
                )
            if value < -1:
                raise QuotaConfigInvalidError(
                    msg=f"quota_config[{key}] must be -1, 0, or positive integer, got {value}",
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
            login_user = kwargs.get("login_user")
            if login_user:
                delta = 1
                if resource_type == QuotaResourceType.TOOL:
                    payload = kwargs.get("req")
                    children = payload.get("children") if isinstance(payload, dict) else None
                    if isinstance(children, list):
                        delta = max(len(children), 1)  # Keep the existing empty-category precheck.
                if resource_type == QuotaResourceType.KNOWLEDGE_SPACE_FILE:
                    size = getattr(kwargs.get("file"), "size", None)
                    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                        raise QuotaUsageUnavailableError(usage_state="UNAVAILABLE")
                    delta = size / (1024**3)
                await QuotaService.check_quota(
                    user_id=login_user.user_id,
                    resource_type=resource_type,
                    tenant_id=login_user.tenant_id,
                    login_user=login_user,
                    delta=delta,
                )
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper

    return decorator
