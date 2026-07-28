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
        source_type = source.get("type", "")

        if source_type == "direct_user":
            for uid in source.get("user_ids") or []:
                try:
                    _add(int(uid))
                except (TypeError, ValueError):
                    logger.warning("approver_resolver: invalid user_id %r in direct_user source", uid)

        elif source_type == "department_admin":
            dept_id = getattr(req, "applicant_department_id", None)
            if dept_id:
                try:
                    ids = await _resolve_department_admins_with_ancestor_fallback(int(dept_id))
                    for uid in ids:
                        _add(uid)
                except Exception:
                    logger.exception("approver_resolver: failed to resolve department_admin for dept_id=%s", dept_id)

        elif source_type == "role_user":
            role_ids: list[int] = []
            for rid in source.get("role_ids") or []:
                try:
                    role_ids.append(int(rid))
                except (TypeError, ValueError):
                    logger.warning("approver_resolver: invalid role_id %r in role_user source", rid)
            if role_ids:
                try:
                    from bisheng.user.domain.models.user_role import UserRoleDao

                    rows = await UserRoleDao.aget_roles_user(role_ids)
                    for row in rows:
                        _add(int(row.user_id))
                except Exception:
                    logger.exception("approver_resolver: failed to resolve role_user for role_ids=%s", role_ids)

        elif source_type == "tenant_admin":
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
                logger.exception("approver_resolver: failed to resolve tenant_admin")

        elif source_type in (
            "knowledge_space_owner",
            "knowledge_space_manager",
            "space_admin",
            "target_knowledge_space_owner",
            "target_knowledge_space_manager",
            "target_knowledge_space_owner_department_admin",
            "target_knowledge_space_manager_department_admin",
            "channel_admin",
            "channel_owner",
            "channel_manager",
        ):
            # These must be resolved by the scenario handler itself.
            pass

        else:
            logger.warning("approver_resolver: unknown source type %r, skipping", source_type)

    return result


def _department_hierarchy_ids_from_path(path: str | None, dept_id: int) -> list[int]:
    hierarchy_ids: list[int] = []
    seen: set[int] = set()
    malformed_parts: list[str] = []

    for part in (path or "").split("/"):
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
            "approver_resolver: malformed department path for dept_id=%s: %r (non-numeric: %s)",
            dept_id,
            path,
            malformed_parts,
        )
        return [dept_id]

    if dept_id not in seen:
        hierarchy_ids.append(dept_id)

    return hierarchy_ids


def _strict_department_hierarchy_ids_from_path(path: str | None, dept_id: int) -> list[int]:
    parts = [part for part in (path or "").split("/") if part]
    if not parts or any(not part.isdigit() for part in parts):
        logger.warning(
            "approver_resolver: invalid file-publish department path for dept_id=%s: %r",
            dept_id,
            path,
        )
        return []

    hierarchy_ids = list(dict.fromkeys(int(part) for part in parts))
    if dept_id not in hierarchy_ids:
        logger.warning(
            "approver_resolver: file-publish department path does not contain dept_id=%s: %r",
            dept_id,
            path,
        )
        return []
    return hierarchy_ids


async def _resolve_department_admins_with_ancestor_fallback(dept_id: int) -> list[int]:
    from bisheng.database.models.department import DepartmentDao
    from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao

    dept = await DepartmentDao.aget_by_id(dept_id)
    hierarchy_ids = _department_hierarchy_ids_from_path(getattr(dept, "path", None), dept_id)

    for candidate_dept_id in reversed(hierarchy_ids):
        ids = await DepartmentAdminGrantDao.aget_user_ids_by_department(candidate_dept_id)
        if ids:
            return [int(uid) for uid in ids]

    return []


def _normalize_unique_ids(values: list[int], *, value_name: str) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            logger.warning("approver_resolver: invalid %s %r", value_name, value)
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


async def _load_primary_department_ids(user_ids: list[int]) -> dict[int, int]:
    from bisheng.database.models.department import UserDepartmentDao

    if not user_ids:
        return {}
    try:
        memberships = await UserDepartmentDao.aget_by_user_ids(user_ids)
    except Exception:
        logger.exception(
            "approver_resolver: failed to batch load primary departments for user_ids=%s",
            user_ids,
        )
        return {}

    primary_dept_by_user: dict[int, int] = {}
    for membership in memberships:
        try:
            if int(getattr(membership, "is_primary", 0)) != 1:
                continue
            user_id = int(membership.user_id)
            if user_id not in primary_dept_by_user:
                primary_dept_by_user[user_id] = int(membership.department_id)
        except (TypeError, ValueError):
            logger.warning("approver_resolver: invalid user department row %r", membership)
    return primary_dept_by_user


async def resolve_file_publish_department_admins(
    *,
    start_department_ids: list[int],
    start_user_ids: list[int],
    applicant_user_id: int | None,
) -> list[int]:
    """Resolve department-admin branches for the file-publish scenario only.

    A candidate must hold the grant for the level currently being inspected,
    belong primarily to the start department's own ancestor chain, and not be
    the applicant.  Each branch stops at its nearest level with valid admins;
    branch results are then merged as one OR-node approver list.
    """
    from bisheng.database.models.department import DepartmentDao
    from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao

    ordered_start_department_ids = _normalize_unique_ids(
        start_department_ids,
        value_name="start department_id",
    )
    ordered_start_user_ids = _normalize_unique_ids(
        start_user_ids,
        value_name="start user_id",
    )
    if ordered_start_user_ids:
        primary_dept_by_start_user = await _load_primary_department_ids(ordered_start_user_ids)
        ordered_start_department_ids = _normalize_unique_ids(
            [
                *ordered_start_department_ids,
                *[
                    primary_dept_by_start_user[user_id]
                    for user_id in ordered_start_user_ids
                    if user_id in primary_dept_by_start_user
                ],
            ],
            value_name="start department_id",
        )

    if not ordered_start_department_ids:
        return []

    try:
        departments = await DepartmentDao.aget_by_ids(ordered_start_department_ids)
    except Exception:
        logger.exception(
            "approver_resolver: failed to batch load file-publish start departments for dept_ids=%s",
            ordered_start_department_ids,
        )
        return []

    department_by_id = {
        int(department.id): department for department in departments if getattr(department, "id", None) is not None
    }
    hierarchy_by_start_department: dict[int, list[int]] = {}
    all_candidate_department_ids: list[int] = []
    seen_candidate_departments: set[int] = set()
    for start_department_id in ordered_start_department_ids:
        department = department_by_id.get(start_department_id)
        if department is None:
            logger.warning(
                "approver_resolver: file-publish start department not found for dept_id=%s",
                start_department_id,
            )
            continue
        hierarchy_ids = _strict_department_hierarchy_ids_from_path(
            getattr(department, "path", None),
            start_department_id,
        )
        if not hierarchy_ids:
            continue
        hierarchy_by_start_department[start_department_id] = hierarchy_ids
        for candidate_department_id in hierarchy_ids:
            if candidate_department_id not in seen_candidate_departments:
                seen_candidate_departments.add(candidate_department_id)
                all_candidate_department_ids.append(candidate_department_id)

    if not all_candidate_department_ids:
        return []

    try:
        admin_ids_by_department = await DepartmentAdminGrantDao.aget_user_ids_by_departments(
            all_candidate_department_ids
        )
    except Exception:
        logger.exception(
            "approver_resolver: failed to batch load file-publish department admins for dept_ids=%s",
            all_candidate_department_ids,
        )
        return []

    candidate_admin_ids = _normalize_unique_ids(
        [
            user_id
            for department_id in all_candidate_department_ids
            for user_id in admin_ids_by_department.get(department_id, [])
        ],
        value_name="department admin user_id",
    )
    primary_dept_by_admin = await _load_primary_department_ids(candidate_admin_ids)

    excluded_user_id: int | None = None
    if applicant_user_id is not None:
        try:
            excluded_user_id = int(applicant_user_id)
        except (TypeError, ValueError):
            logger.warning(
                "approver_resolver: invalid applicant_user_id %r for file publish",
                applicant_user_id,
            )

    result: list[int] = []
    seen_result: set[int] = set()
    for start_department_id in ordered_start_department_ids:
        hierarchy_ids = hierarchy_by_start_department.get(start_department_id, [])
        allowed_primary_department_ids = set(hierarchy_ids)
        for candidate_department_id in reversed(hierarchy_ids):
            valid_level_admins: list[int] = []
            seen_level: set[int] = set()
            for raw_admin_user_id in admin_ids_by_department.get(candidate_department_id, []):
                try:
                    admin_user_id = int(raw_admin_user_id)
                except (TypeError, ValueError):
                    logger.warning(
                        "approver_resolver: invalid department admin user_id %r",
                        raw_admin_user_id,
                    )
                    continue
                if admin_user_id == excluded_user_id or admin_user_id in seen_level:
                    continue
                if primary_dept_by_admin.get(admin_user_id) not in allowed_primary_department_ids:
                    continue
                seen_level.add(admin_user_id)
                valid_level_admins.append(admin_user_id)
            if not valid_level_admins:
                continue
            for admin_user_id in valid_level_admins:
                if admin_user_id not in seen_result:
                    seen_result.add(admin_user_id)
                    result.append(admin_user_id)
            break

    return result


async def resolve_folder_delete_notify_recipients(operator_user_id: int) -> list[int]:
    """Resolve department admins to notify when *operator_user_id* deletes a folder.

    Walks the operator's primary-department path from leaf to root:

    - If the operator is a grant admin of the candidate department, skip the
      entire level (including co-admins) and continue to the parent.
    - Otherwise return that level's grant admins, excluding the operator.
    - If no level yields recipients, return an empty list.
    """
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
    from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao

    try:
        operator_id = int(operator_user_id)
    except (TypeError, ValueError):
        logger.warning(
            "approver_resolver: invalid operator_user_id %r for folder delete notify",
            operator_user_id,
        )
        return []

    try:
        membership = await UserDepartmentDao.aget_user_primary_department(operator_id)
    except Exception:
        logger.exception(
            "approver_resolver: failed to load primary department for operator_user_id=%s",
            operator_id,
        )
        return []

    if membership is None:
        return []

    try:
        dept_id = int(membership.department_id)
    except (TypeError, ValueError):
        logger.warning(
            "approver_resolver: invalid primary department for operator_user_id=%s membership=%r",
            operator_id,
            membership,
        )
        return []

    try:
        dept = await DepartmentDao.aget_by_id(dept_id)
    except Exception:
        logger.exception(
            "approver_resolver: failed to load department %s for folder delete notify",
            dept_id,
        )
        return []

    if dept is None:
        return []

    hierarchy_ids = _department_hierarchy_ids_from_path(getattr(dept, "path", None), dept_id)

    for candidate_dept_id in reversed(hierarchy_ids):
        try:
            grant_ids = [
                int(uid) for uid in await DepartmentAdminGrantDao.aget_user_ids_by_department(candidate_dept_id)
            ]
        except Exception:
            logger.exception(
                "approver_resolver: failed to load department admins for dept_id=%s",
                candidate_dept_id,
            )
            continue

        if not grant_ids:
            continue
        if operator_id in grant_ids:
            # Operator is an admin of this level — skip the whole level.
            continue
        return [uid for uid in grant_ids if uid != operator_id]

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
            logger.warning("approver_resolver: invalid user_id %r in department_admin source", user_id)
            continue
        if normalized_user_id not in seen_users:
            seen_users.add(normalized_user_id)
            ordered_user_ids.append(normalized_user_id)

    if not ordered_user_ids:
        return []

    try:
        memberships = await UserDepartmentDao.aget_by_user_ids(ordered_user_ids)
    except Exception:
        logger.exception(
            "approver_resolver: failed to batch load primary departments for user_ids=%s", ordered_user_ids
        )
        return []

    primary_dept_by_user: dict[int, int] = {}
    for membership in memberships:
        try:
            if int(getattr(membership, "is_primary", 0)) != 1:
                continue
            user_id = int(membership.user_id)
            if user_id not in primary_dept_by_user:
                primary_dept_by_user[user_id] = int(membership.department_id)
        except (TypeError, ValueError):
            logger.warning("approver_resolver: invalid user department row %r", membership)

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
        logger.exception("approver_resolver: failed to batch load departments for dept_ids=%s", ordered_dept_ids)
        return []

    department_by_id = {int(dept.id): dept for dept in departments if getattr(dept, "id", None) is not None}
    hierarchy_by_user: dict[int, list[int]] = {}
    all_candidate_dept_ids: list[int] = []
    seen_candidates: set[int] = set()

    for user_id in ordered_user_ids:
        dept_id = primary_dept_by_user.get(user_id)
        if not dept_id:
            continue
        dept = department_by_id.get(dept_id)
        if dept is None:
            logger.warning(
                "approver_resolver: primary department not found for user_id=%s dept_id=%s", user_id, dept_id
            )
            continue
        hierarchy_ids = _department_hierarchy_ids_from_path(getattr(dept, "path", None), dept_id)
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
            "approver_resolver: failed to batch load department admins for dept_ids=%s",
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
