from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def resolve_approvers_from_sources(sources: list[dict], req: Any) -> list[int]:
    """Resolve the full approver user-id list from a node's ``sources`` config.

    Each entry in *sources* has at least a ``type`` key.  Supported types:

    ``direct_user``
        Explicit user IDs stored in ``user_ids`` (list[int]).

    ``department_admin``
        Admins of the applicant's department (from ``DepartmentAdminGrantDao``).
        Falls back to an empty list when ``applicant_department_id`` is unset.

    ``tenant_admin``
        Users who are tenant admin of the current tenant (via ``TenantService``).

    ``knowledge_space_owner`` / ``knowledge_space_manager`` / ``space_admin``
        These are resolved by the specific scenario handler that knows the
        relevant space.  This utility returns an empty contribution for them —
        the handler is expected to override or augment as needed.

    ``channel_admin``
        Channel admins are scenario-specific; returns empty here.

    Unknown types are silently skipped with a warning.
    """
    seen: set[int] = set()
    result: list[int] = []

    def _add(uid: int) -> None:
        if uid not in seen:
            seen.add(uid)
            result.append(uid)

    for source in sources:
        source_type = source.get('type', '')

        if source_type == 'direct_user':
            for uid in (source.get('user_ids') or []):
                try:
                    _add(int(uid))
                except (TypeError, ValueError):
                    logger.warning('approver_resolver: invalid user_id %r in direct_user source', uid)

        elif source_type == 'department_admin':
            dept_id = getattr(req, 'applicant_department_id', None)
            if dept_id:
                try:
                    from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao
                    ids = await DepartmentAdminGrantDao.aget_user_ids_by_department(int(dept_id))
                    for uid in ids:
                        _add(uid)
                except Exception:
                    logger.exception('approver_resolver: failed to resolve department_admin for dept_id=%s', dept_id)

        elif source_type == 'tenant_admin':
            # Resolve tenant admins via system AdminRole users.
            # Full FGA-based resolution would require a list_users call; using
            # AdminRole (role_id=1) as a pragmatic approximation.
            try:
                from bisheng.database.constants import AdminRole
                from bisheng.user.domain.models.user_role import UserRoleDao
                rows = await UserRoleDao.aget_roles_user([AdminRole])
                for row in rows:
                    _add(int(row.user_id))
            except Exception:
                logger.exception('approver_resolver: failed to resolve tenant_admin')

        elif source_type in (
            'knowledge_space_owner', 'knowledge_space_manager', 'space_admin',
            'channel_admin', 'channel_owner', 'channel_manager',
        ):
            # These must be resolved by the scenario handler itself.
            pass

        else:
            logger.warning('approver_resolver: unknown source type %r, skipping', source_type)

    return result
