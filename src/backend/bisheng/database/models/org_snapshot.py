"""Organisation snapshot on audit source rows, and the department predicate (F003).

Five tables carry ``operator_dept_id`` / ``operator_dept_path``: ``auditlog``,
``message_session``, ``model_call_record``, ``app_capability_call_record`` and
``app_access_log``. ``operator_dept_id`` holds

* ``NULL`` — not recorded (rows written before F003, or the lookup failed);
* ``0`` (``DEPT_NONE``) — the person had no primary department at the time;
* ``-1`` (``DEPT_NOT_APPLICABLE``) — no natural person behind the row
  (system trigger, service account, open-API caller);
* ``> 0`` — ``department.id`` of the primary department at the time.

The module lives in ``database/models`` because the writers it serves
(``AuditLogDao``, ``MessageSessionDao``) do too, and that layer must not import
``domain`` (arch-guard RULE-2). It only uses the existing department DAOs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from loguru import logger
from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import aliased

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, DepartmentDao, UserDepartmentDao

DEPT_NONE = 0
DEPT_NOT_APPLICABLE = -1
DEPT_STATUS_ACTIVE = "active"

Snapshot = tuple[int | None, str | None]
UNRECORDED: Snapshot = (None, None)
NOT_APPLICABLE: Snapshot = (DEPT_NOT_APPLICABLE, None)


def _path_ids(path: str | None) -> list[int]:
    return [int(part) for part in (path or "").strip("/").split("/") if part.isdigit()]


def _name_path(dept: Department, by_id: dict[int, Department]) -> str:
    names = [by_id[one].name for one in _path_ids(dept.path) if one in by_id]
    return "/".join(names) or dept.name


def resolve_user_dept(user_id: int | None) -> Snapshot:
    """Primary department of ``user_id`` right now, as ``(id, name path)``."""
    if not user_id:
        return UNRECORDED
    try:
        with bypass_tenant_filter():
            membership = UserDepartmentDao.get_user_primary_department(int(user_id))
            if membership is None:
                return DEPT_NONE, None
            dept = DepartmentDao.get_by_id(membership.department_id)
            if dept is None:
                return UNRECORDED
            ancestors = {one.id: one for one in DepartmentDao.get_by_ids(_path_ids(dept.path))}
        return dept.id, _name_path(dept, ancestors)
    except Exception:
        # Best effort by design: the audited operation has already happened and
        # must not fail because its department could not be looked up.
        logger.opt(exception=True).warning("audit org snapshot failed user_id={}", user_id)
        return UNRECORDED


async def aresolve_users_dept(user_ids: Iterable[int | None]) -> dict[int, Snapshot]:
    """Batch form of :func:`resolve_user_dept`; three queries whatever the size."""
    ids = sorted({int(one) for one in user_ids if one})
    if not ids:
        return {}
    try:
        with bypass_tenant_filter():
            memberships = await UserDepartmentDao.aget_by_user_ids(ids)
            primary = {one.user_id: one.department_id for one in memberships if one.is_primary == 1}
            depts = {one.id: one for one in await DepartmentDao.aget_by_ids(sorted(set(primary.values())))}
            ancestor_ids = sorted({one for dept in depts.values() for one in _path_ids(dept.path)})
            ancestors = {one.id: one for one in await DepartmentDao.aget_by_ids(ancestor_ids)}
    except Exception:
        # Same best-effort contract as resolve_user_dept.
        logger.opt(exception=True).warning("audit org snapshot failed user_ids={}", ids)
        return dict.fromkeys(ids, UNRECORDED)
    result: dict[int, Snapshot] = {}
    for user_id in ids:
        dept_id = primary.get(user_id)
        if dept_id is None:
            result[user_id] = (DEPT_NONE, None)
            continue
        dept = depts.get(dept_id)
        result[user_id] = (dept.id, _name_path(dept, ancestors)) if dept is not None else UNRECORDED
    return result


async def aresolve_user_dept(user_id: int | None) -> Snapshot:
    return (await aresolve_users_dept([user_id])).get(int(user_id), UNRECORDED) if user_id else UNRECORDED


def _unstamped(row: Any) -> bool:
    return getattr(row, "operator_dept_id", None) is None and getattr(row, "operator_dept_path", None) is None


def _apply(row: Any, snapshot: Snapshot) -> None:
    row.operator_dept_id, row.operator_dept_path = snapshot


#: ``subject_of(row)`` returns the natural person's user id, or ``None`` when
#: the row has no natural person behind it (written as ``-1``).
SubjectOf = Callable[[Any], int | None]


def stamp(rows: Iterable[Any], subject_of: SubjectOf) -> None:
    for row in rows:
        if not _unstamped(row):
            continue
        user_id = subject_of(row)
        _apply(row, NOT_APPLICABLE if user_id is None else resolve_user_dept(user_id))


async def astamp(rows: Iterable[Any], subject_of: SubjectOf) -> None:
    pending = [(row, subject_of(row)) for row in rows if _unstamped(row)]
    snapshots = await aresolve_users_dept(user_id for _, user_id in pending)
    for row, user_id in pending:
        _apply(row, NOT_APPLICABLE if user_id is None else snapshots.get(int(user_id), UNRECORDED))


def audit_log_subject(row: Any) -> int | None:
    """System triggers and service accounts are written as operator 0, some system writers as -1."""
    return row.operator_id if (row.operator_id or 0) > 0 else None


def session_subject(row: Any) -> int | None:
    """Open-API sessions carry a compatibility ``user_id``; it is not the actor."""
    if getattr(row, "api_subject_type", None):
        return None
    return row.user_id or None


def stamp_audit_logs(rows: Iterable[Any]) -> None:
    stamp(rows, audit_log_subject)


async def astamp_audit_logs(rows: Iterable[Any]) -> None:
    await astamp(rows, audit_log_subject)


def stamp_session(row: Any) -> None:
    stamp([row], session_subject)


async def astamp_session(row: Any) -> None:
    await astamp([row], session_subject)


# ---------------------------------------------------------------------------
# Department predicate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditDeptScope:
    """Which departments a caller may read. Built by ``department.domain``.

    ``unrestricted`` — platform super only: no department condition.
    Otherwise the closure is every department under one of ``admin_paths``
    (any status) plus ``exact_ids``; an empty closure means nothing is visible.
    Rows whose department is NULL / 0 / -1 are never in a closure.
    ``unattributed`` adds the 0 / -1 rows back for a tenant administrator; the
    query is already pinned to that tenant. NULL rows stay hidden.
    """

    unrestricted: bool = True
    admin_paths: tuple[str, ...] = ()
    exact_ids: tuple[int, ...] = ()
    unattributed: bool = False

    @classmethod
    def unlimited(cls) -> AuditDeptScope:
        return cls()

    @classmethod
    def restricted(
        cls, *, admin_paths: Iterable[str] = (), exact_ids: Iterable[int] = (), unattributed: bool = False
    ) -> AuditDeptScope:
        return cls(
            unrestricted=False,
            admin_paths=tuple(sorted({p for p in admin_paths if p})),
            exact_ids=tuple(sorted({int(i) for i in exact_ids})),
            unattributed=unattributed,
        )

    @property
    def shows_none(self) -> bool:
        return self.unrestricted or self.unattributed

    def digest_parts(self) -> list:
        return [self.unrestricted, list(self.admin_paths), list(self.exact_ids), self.unattributed]


@dataclass(frozen=True)
class DeptSelection:
    """What the caller ticked in the organisation panel."""

    dept_ids: tuple[int, ...] = ()
    include_descendants: bool = True
    include_none: bool = False
    include_unrecorded: bool = False

    @classmethod
    def of(
        cls,
        dept_ids: Iterable[int] | None = None,
        include_descendants: bool | None = True,
        include_none: bool | None = False,
        include_unrecorded: bool | None = False,
    ) -> DeptSelection:
        return cls(
            dept_ids=tuple(sorted({int(i) for i in (dept_ids or []) if int(i) > 0})),
            include_descendants=True if include_descendants is None else bool(include_descendants),
            include_none=bool(include_none),
            include_unrecorded=bool(include_unrecorded),
        )

    @property
    def is_empty(self) -> bool:
        return not (self.dept_ids or self.include_none or self.include_unrecorded)


def _closure(column, scope: AuditDeptScope):
    parts = []
    if scope.admin_paths:
        under_paths = or_(*(Department.path.startswith(path) for path in scope.admin_paths))
        parts.append(column.in_(select(Department.id).where(under_paths)))
    if scope.exact_ids:
        parts.append(column.in_(scope.exact_ids))
    if scope.unattributed:
        parts.append(column.in_([DEPT_NONE, DEPT_NOT_APPLICABLE]))
    return or_(*parts) if parts else false()


def _selection_clause(column, selection: DeptSelection):
    parts = []
    if selection.dept_ids:
        ids = list(selection.dept_ids)
        # Selected ids match exactly whatever their status, so an archived
        # department ticked on its own still matches its historical rows.
        parts.append(column.in_(ids))
        if selection.include_descendants:
            parent = aliased(Department)
            child = aliased(Department)
            # ``path`` ends with "/", so "/1/2/" never matches "/1/20/".
            descendants = (
                select(child.id)
                .join(parent, child.path.startswith(parent.path))
                .where(
                    parent.id.in_(ids),
                    parent.status == DEPT_STATUS_ACTIVE,
                    child.status == DEPT_STATUS_ACTIVE,
                )
            )
            parts.append(column.in_(descendants))
    if selection.include_none:
        parts.append(column == DEPT_NONE)
    if selection.include_unrecorded:
        parts.append(column.is_(None))
    return or_(*parts) if parts else None


def build_dept_predicate(column, scope: AuditDeptScope, selection: DeptSelection | None = None):
    """``WHERE`` clause for ``column`` (an ``operator_dept_id``), or ``None``.

    The selection only narrows the scope: for a restricted caller the
    unattributed options it may not see are dropped before anything else, and
    the result is always intersected with the closure.
    """
    selection = selection or DeptSelection()
    if not scope.unrestricted:
        selection = replace(
            selection, include_none=selection.include_none and scope.unattributed, include_unrecorded=False
        )
    chosen = _selection_clause(column, selection)
    if scope.unrestricted:
        return chosen
    closure = _closure(column, scope)
    return closure if chosen is None else and_(closure, chosen)


def dept_label_key(dept_id: int | None) -> str | None:
    """i18n key for the sentinel values; ``None`` means show the stored path."""
    if dept_id is None:
        return "log.org.unrecorded"
    if dept_id == DEPT_NONE:
        return "log.org.none"
    if dept_id == DEPT_NOT_APPLICABLE:
        return "log.org.notApplicable"
    return None


__all__ = [
    "DEPT_NONE",
    "DEPT_NOT_APPLICABLE",
    "NOT_APPLICABLE",
    "UNRECORDED",
    "AuditDeptScope",
    "DeptSelection",
    "aresolve_user_dept",
    "aresolve_users_dept",
    "astamp",
    "astamp_audit_logs",
    "astamp_session",
    "audit_log_subject",
    "build_dept_predicate",
    "dept_label_key",
    "resolve_user_dept",
    "session_subject",
    "stamp",
    "stamp_audit_logs",
    "stamp_session",
]
