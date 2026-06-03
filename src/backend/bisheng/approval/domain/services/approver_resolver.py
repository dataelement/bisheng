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
        Admins of the applicant's department, falling back to the nearest
        ancestor department with admins. Falls back to an empty list when
        ``applicant_department_id`` is unset or no department in the chain has
        admins.

    ``role_user``
        Users who hold any role listed in ``role_ids``.

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
                    ids = await _resolve_department_admins_with_ancestor_fallback(int(dept_id))
                    for uid in ids:
                        _add(uid)
                except Exception:
                    logger.exception('approver_resolver: failed to resolve department_admin for dept_id=%s', dept_id)

        elif source_type == 'role_user':
            role_ids: list[int] = []
            for rid in (source.get('role_ids') or []):
                try:
                    role_ids.append(int(rid))
                except (TypeError, ValueError):
                    logger.warning('approver_resolver: invalid role_id %r in role_user source', rid)
            if role_ids:
                try:
                    from bisheng.user.domain.models.user_role import UserRoleDao
                    rows = await UserRoleDao.aget_roles_user(role_ids)
                    for row in rows:
                        _add(int(row.user_id))
                except Exception:
                    logger.exception('approver_resolver: failed to resolve role_user for role_ids=%s', role_ids)

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
            'target_knowledge_space_owner', 'target_knowledge_space_manager',
            'target_knowledge_space_owner_department_admin',
            'target_knowledge_space_manager_department_admin',
            'channel_admin', 'channel_owner', 'channel_manager',
        ):
            # These must be resolved by the scenario handler itself.
            pass

        else:
            logger.warning('approver_resolver: unknown source type %r, skipping', source_type)

    return result


def _department_hierarchy_ids_from_path(path: str | None, dept_id: int) -> list[int]:
    hierarchy_ids: list[int] = []
    seen: set[int] = set()
    malformed_parts: list[str] = []

    for part in (path or '').split('/'):
        if not part:
            continue
        if not part.isdigit():
            malformed_parts.append(part)
            continue
        candidate_id = int(part)
        if candidate_id not in seen:
            seen.add(candidate_id)
            hierarchy_ids.append(candidate_id)

    if malformed_parts:
        logger.warning(
            'approver_resolver: malformed department path for dept_id=%s: %r (non-numeric: %s)',
            dept_id, path, malformed_parts,
        )
        return [dept_id]

    if dept_id not in seen:
        hierarchy_ids.append(dept_id)

    return hierarchy_ids


async def _resolve_department_admins_with_ancestor_fallback(dept_id: int) -> list[int]:
    from bisheng.database.models.department import DepartmentDao
    from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao

    dept = await DepartmentDao.aget_by_id(dept_id)
    hierarchy_ids = _department_hierarchy_ids_from_path(getattr(dept, 'path', None), dept_id)

    for candidate_dept_id in reversed(hierarchy_ids):
        ids = await DepartmentAdminGrantDao.aget_user_ids_by_department(candidate_dept_id)
        if ids:
            return [int(uid) for uid in ids]

    return []


async def resolve_department_admins_for_user_ids(user_ids: list[int]) -> list[int]:
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
    from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao

    ordered_user_ids: list[int] = []
    seen_users: set[int] = set()
    for user_id in user_ids:
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError):
            logger.warning('approver_resolver: invalid user_id %r in department_admin source', user_id)
            continue
        if normalized_user_id not in seen_users:
            seen_users.add(normalized_user_id)
            ordered_user_ids.append(normalized_user_id)

    if not ordered_user_ids:
        return []

    try:
        memberships = await UserDepartmentDao.aget_by_user_ids(ordered_user_ids)
    except Exception:
        logger.exception('approver_resolver: failed to batch load primary departments for user_ids=%s', ordered_user_ids)
        return []

    primary_dept_by_user: dict[int, int] = {}
    for membership in memberships:
        try:
            if int(getattr(membership, 'is_primary', 0)) != 1:
                continue
            user_id = int(getattr(membership, 'user_id'))
            if user_id not in primary_dept_by_user:
                primary_dept_by_user[user_id] = int(getattr(membership, 'department_id'))
        except (TypeError, ValueError):
            logger.warning('approver_resolver: invalid user department row %r', membership)

    ordered_dept_ids: list[int] = []
    seen_depts: set[int] = set()
    for user_id in ordered_user_ids:
        dept_id = primary_dept_by_user.get(user_id)
        if dept_id and dept_id not in seen_depts:
            seen_depts.add(dept_id)
            ordered_dept_ids.append(dept_id)

    if not ordered_dept_ids:
        return []

    try:
        departments = await DepartmentDao.aget_by_ids(ordered_dept_ids)
    except Exception:
        logger.exception('approver_resolver: failed to batch load departments for dept_ids=%s', ordered_dept_ids)
        return []

    department_by_id = {int(getattr(dept, 'id')): dept for dept in departments if getattr(dept, 'id', None) is not None}
    hierarchy_by_user: dict[int, list[int]] = {}
    all_candidate_dept_ids: list[int] = []
    seen_candidates: set[int] = set()

    for user_id in ordered_user_ids:
        dept_id = primary_dept_by_user.get(user_id)
        if not dept_id:
            continue
        dept = department_by_id.get(dept_id)
        if dept is None:
            logger.warning('approver_resolver: primary department not found for user_id=%s dept_id=%s', user_id, dept_id)
            continue
        hierarchy_ids = _department_hierarchy_ids_from_path(getattr(dept, 'path', None), dept_id)
        hierarchy_by_user[user_id] = hierarchy_ids
        for candidate_dept_id in hierarchy_ids:
            if candidate_dept_id not in seen_candidates:
                seen_candidates.add(candidate_dept_id)
                all_candidate_dept_ids.append(candidate_dept_id)

    if not all_candidate_dept_ids:
        return []

    try:
        admin_ids_by_department = await DepartmentAdminGrantDao.aget_user_ids_by_departments(all_candidate_dept_ids)
    except Exception:
        logger.exception(
            'approver_resolver: failed to batch load department admins for dept_ids=%s',
            all_candidate_dept_ids,
        )
        return []

    seen: set[int] = set()
    result: list[int] = []

    def _add(uid: int) -> None:
        if uid not in seen:
            seen.add(uid)
            result.append(uid)

    for user_id in ordered_user_ids:
        for candidate_dept_id in reversed(hierarchy_by_user.get(user_id, [])):
            admin_ids = admin_ids_by_department.get(candidate_dept_id) or []
            if admin_ids:
                for admin_user_id in admin_ids:
                    _add(int(admin_user_id))
                break

    return result
