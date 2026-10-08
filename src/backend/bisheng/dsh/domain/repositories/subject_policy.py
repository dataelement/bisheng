"""Department/role model grants and effective per-user policy resolution."""

import hashlib

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import (
    DshInvalidRequestError,
    DshOperationConflictError,
    DshSeatLimitReachedError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.database.constants import AdminRole
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicy, DshSubjectPolicyAudit
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.schemas.model_policy import DshModelPolicyState, DshPolicySnapshot
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole

SUBJECT_TYPES = {"DEPARTMENT", "ROLE"}


def _state(row: DshSubjectPolicy | None) -> dict:
    return {
        "enabled": bool(row.enabled) if row else False,
        "monthly_token_limit": row.monthly_token_limit if row else 0,
        "version": row.version if row else 0,
    }


class DshSubjectPolicyRepository:
    def __init__(self, session: Session):
        self.session = session

    def _departments(self) -> list[Department]:
        tenant = require_tenant()
        with strict_tenant_filter():
            rows = list(
                self.session.exec(
                    select(Department)
                    .where(Department.tenant_id == tenant, Department.status == "active")
                    .order_by(Department.sort_order, Department.id)
                ).all()
            )
        return rows

    def _roles(self) -> list[Role]:
        tenant = require_tenant()
        with bypass_tenant_filter():
            return list(
                self.session.exec(
                    select(Role)
                    .where(
                        Role.id > AdminRole,
                        or_(
                            Role.role_type == "global",
                            and_(Role.role_type == "tenant", Role.tenant_id == tenant),
                        ),
                    )
                    .order_by(Role.role_type, Role.role_name, Role.id)
                ).all()
            )

    def _lock_tenant(self) -> None:
        """Serialize every authorization write that can consume tenant seats."""
        tenant = require_tenant()
        with strict_tenant_filter():
            row = self.session.exec(select(Tenant).where(Tenant.id == tenant).with_for_update()).one_or_none()
        if row is None or row.status != "active":
            raise DshInvalidRequestError()

    def entitled_user_ids(
        self,
        *,
        proposed_subject: tuple[str, int, int, bool, int] | None = None,
        proposed_user: tuple[int, int, bool, int] | None = None,
    ) -> list[int]:
        """Resolve users entitled to at least one positive DSH model grant.

        A proposal replaces the matching persisted row, so capacity is checked
        against the complete post-change state before the write is committed.
        """
        tenant = require_tenant()
        with strict_tenant_filter():
            active_user_ids = {
                int(user_id)
                for user_id in self.session.exec(
                    select(User.user_id)
                    .join(UserTenant, UserTenant.user_id == User.user_id)
                    .join(Tenant, Tenant.id == UserTenant.tenant_id)
                    .where(
                        UserTenant.tenant_id == tenant,
                        UserTenant.is_active == 1,
                        UserTenant.status == "active",
                        Tenant.status == "active",
                        User.delete == 0,
                    )
                ).all()
            }
            direct_rows = list(self.session.exec(select(DshUserPolicy).where(DshUserPolicy.tenant_id == tenant)).all())
            pending_policy_operations = list(
                self.session.exec(
                    select(DshAdminOperation).where(
                        DshAdminOperation.tenant_id == tenant,
                        DshAdminOperation.action == "UPDATE_POLICY",
                        DshAdminOperation.status.in_(("PENDING", "PROCESSING")),
                    )
                ).all()
            )
            subject_rows = list(
                self.session.exec(select(DshSubjectPolicy).where(DshSubjectPolicy.tenant_id == tenant)).all()
            )
            membership_rows = (
                list(
                    self.session.exec(
                        select(UserDepartment.user_id, UserDepartment.department_id)
                        .join(Department, Department.id == UserDepartment.department_id)
                        .where(
                            UserDepartment.user_id.in_(active_user_ids),
                            Department.tenant_id == tenant,
                            Department.status == "active",
                        )
                    ).all()
                )
                if active_user_ids
                else []
            )
            role_rows = (
                list(
                    self.session.exec(
                        select(UserRole.user_id, UserRole.role_id).where(
                            UserRole.tenant_id == tenant,
                            UserRole.user_id.in_(active_user_ids),
                        )
                    ).all()
                )
                if active_user_ids
                else []
            )

        direct = {
            (int(row.user_id), int(row.model_id)): (
                bool(row.enabled),
                int(row.monthly_token_limit),
            )
            for row in direct_rows
        }
        # A durable direct-policy command reserves capacity as soon as it is
        # registered. This keeps two concurrent pending grants from both
        # passing the same seat check before the worker commits either policy.
        for operation in sorted(
            pending_policy_operations,
            key=lambda item: item.operation_id,
        ):
            payload = operation.payload
            model_id = payload.get("model_id") if isinstance(payload, dict) else None
            enabled = payload.get("enabled") if isinstance(payload, dict) else None
            monthly_token_limit = payload.get("monthly_token_limit") if isinstance(payload, dict) else None
            if type(model_id) is not int or type(enabled) is not bool or type(monthly_token_limit) is not int:
                raise DshInvalidRequestError()
            direct[(int(operation.user_id), model_id)] = (enabled, monthly_token_limit)
        if proposed_user is not None:
            user_id, model_id, enabled, monthly_token_limit = proposed_user
            direct[(user_id, model_id)] = (enabled, monthly_token_limit)

        subjects = {
            (row.subject_type, int(row.subject_id), int(row.model_id)): (
                bool(row.enabled),
                int(row.monthly_token_limit),
            )
            for row in subject_rows
        }
        if proposed_subject is not None:
            subject_type, subject_id, model_id, enabled, monthly_token_limit = proposed_subject
            subjects[(subject_type, subject_id, model_id)] = (enabled, monthly_token_limit)

        entitled = {
            user_id
            for (user_id, _model_id), (enabled, monthly_token_limit) in direct.items()
            if user_id in active_user_ids and enabled and monthly_token_limit > 0
        }
        active_subjects = {
            (subject_type, subject_id, model_id)
            for (subject_type, subject_id, model_id), (enabled, monthly_token_limit) in subjects.items()
            if enabled and monthly_token_limit > 0
        }
        if active_subjects and active_user_ids:
            departments = self._departments()
            memberships: dict[int, set[int]] = {user_id: set() for user_id in active_user_ids}
            roles: dict[int, set[int]] = {user_id: set() for user_id in active_user_ids}
            for user_id, department_id in membership_rows:
                memberships[int(user_id)].add(int(department_id))
            for user_id, role_id in role_rows:
                roles[int(user_id)].add(int(role_id))
            for user_id in active_user_ids - entitled:
                ancestors = self._department_ancestor_ids_for(memberships[user_id], departments)
                if any(
                    (
                        (kind == "DEPARTMENT" and subject_id in ancestors)
                        or (kind == "ROLE" and subject_id in roles[user_id])
                    )
                    and not direct.get((user_id, model_id), (False, 0))[0]
                    for kind, subject_id, model_id in active_subjects
                ):
                    entitled.add(user_id)
        return sorted(entitled)

    def ensure_seat_capacity(
        self,
        seat_limit: int,
        *,
        proposed_subject: tuple[str, int, int, bool, int] | None = None,
        proposed_user: tuple[int, int, bool, int] | None = None,
    ) -> None:
        if type(seat_limit) is not int or seat_limit < 0:
            raise DshInvalidRequestError()
        self._lock_tenant()
        if (
            len(
                self.entitled_user_ids(
                    proposed_subject=proposed_subject,
                    proposed_user=proposed_user,
                )
            )
            > seat_limit
        ):
            raise DshSeatLimitReachedError()

    @staticmethod
    def _ordered_department_tree(departments: list[Department]) -> list[tuple[Department, int]]:
        by_id = {int(row.id): row for row in departments}
        children: dict[int | None, list[Department]] = {}
        for row in departments:
            parent_id = int(row.parent_id) if row.parent_id in by_id else None
            children.setdefault(parent_id, []).append(row)
        for rows in children.values():
            rows.sort(key=lambda item: (item.sort_order, int(item.id)))
        ordered: list[tuple[Department, int]] = []
        visited: set[int] = set()

        def append_subtree(root: Department, depth: int):
            stack = [(root, depth)]
            while stack:
                current, current_depth = stack.pop()
                current_id = int(current.id)
                if current_id in visited:
                    continue
                visited.add(current_id)
                ordered.append((current, current_depth))
                stack.extend((child, current_depth + 1) for child in reversed(children.get(current_id, [])))

        for root in children.get(None, []):
            append_subtree(root, 0)
        for row in sorted(departments, key=lambda item: (item.sort_order, int(item.id))):
            if int(row.id) not in visited:
                append_subtree(row, 0)
        return ordered

    def inventory(self, model_id: int) -> dict:
        tenant = require_tenant()
        if type(model_id) is not int or model_id < 1:
            raise DshInvalidRequestError()
        departments, roles = self._departments(), self._roles()
        with strict_tenant_filter():
            policies = list(
                self.session.exec(
                    select(DshSubjectPolicy).where(
                        DshSubjectPolicy.tenant_id == tenant,
                        DshSubjectPolicy.model_id == model_id,
                    )
                ).all()
            )
        by_subject = {(row.subject_type, row.subject_id): row for row in policies}
        ordered_departments = self._ordered_department_tree(departments)

        return {
            "tenant_id": tenant,
            "model_id": model_id,
            "departments": [
                {
                    "subject_type": "DEPARTMENT",
                    "subject_id": int(row.id),
                    "name": row.name,
                    "parent_id": row.parent_id,
                    "depth": depth,
                    **_state(by_subject.get(("DEPARTMENT", int(row.id)))),
                }
                for row, depth in ordered_departments
            ],
            "roles": [
                {
                    "subject_type": "ROLE",
                    "subject_id": int(row.id),
                    "name": row.role_name,
                    "role_type": row.role_type,
                    "department_id": row.department_id,
                    **_state(by_subject.get(("ROLE", int(row.id)))),
                }
                for row in roles
            ],
        }

    def _validate_subject(self, subject_type: str, subject_id: int):
        tenant = require_tenant()
        if subject_type == "DEPARTMENT":
            with strict_tenant_filter():
                row = self.session.exec(
                    select(Department).where(
                        Department.id == subject_id,
                        Department.tenant_id == tenant,
                        Department.status == "active",
                    )
                ).one_or_none()
        elif subject_type == "ROLE":
            with bypass_tenant_filter():
                row = self.session.exec(
                    select(Role).where(
                        Role.id == subject_id,
                        Role.id > AdminRole,
                        or_(
                            Role.role_type == "global",
                            and_(Role.role_type == "tenant", Role.tenant_id == tenant),
                        ),
                    )
                ).one_or_none()
        else:
            row = None
        if row is None:
            raise DshInvalidRequestError()
        return row

    def update(
        self,
        *,
        subject_type: str,
        subject_id: int,
        model_id: int,
        actor_user_id: int,
        expected_version: int,
        monthly_token_limit: int,
        enabled: bool,
        seat_limit: int | None = None,
    ) -> dict:
        tenant = require_tenant()
        if (
            subject_type not in SUBJECT_TYPES
            or any(type(value) is not int or value < 1 for value in (subject_id, model_id, actor_user_id))
            or type(expected_version) is not int
            or expected_version < 0
            or type(monthly_token_limit) is not int
            or not 0 <= monthly_token_limit <= 9223372036854775807
            or type(enabled) is not bool
        ):
            raise DshInvalidRequestError()
        subject = self._validate_subject(subject_type, subject_id)
        if seat_limit is not None:
            self.ensure_seat_capacity(
                seat_limit,
                proposed_subject=(
                    subject_type,
                    subject_id,
                    model_id,
                    enabled,
                    monthly_token_limit,
                ),
            )
        statement = select(DshSubjectPolicy).where(
            DshSubjectPolicy.tenant_id == tenant,
            DshSubjectPolicy.subject_type == subject_type,
            DshSubjectPolicy.subject_id == subject_id,
            DshSubjectPolicy.model_id == model_id,
        )
        with strict_tenant_filter():
            row = self.session.exec(statement.with_for_update().execution_options(populate_existing=True)).one_or_none()
        before = _state(row) if row else None
        if row is None:
            if expected_version != 0:
                raise DshOperationConflictError()
            try:
                with self.session.begin_nested():
                    row = DshSubjectPolicy(
                        tenant_id=tenant,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        model_id=model_id,
                        monthly_token_limit=monthly_token_limit,
                        enabled=int(enabled),
                        version=1,
                        updated_by=actor_user_id,
                    )
                    self.session.add(row)
                    self.session.flush()
            except IntegrityError:
                with strict_tenant_filter():
                    row = self.session.exec(
                        statement.with_for_update().execution_options(populate_existing=True)
                    ).one_or_none()
                if row is None or row.version != expected_version:
                    raise DshOperationConflictError() from None
        else:
            if row.version != expected_version:
                raise DshOperationConflictError()
            row.monthly_token_limit = monthly_token_limit
            row.enabled = int(enabled)
            row.version += 1
            row.updated_by = actor_user_id
            self.session.flush()
        after = _state(row)
        self.session.add(
            DshSubjectPolicyAudit(
                tenant_id=tenant,
                subject_type=subject_type,
                subject_id=subject_id,
                model_id=model_id,
                actor_user_id=actor_user_id,
                before_values=before,
                after_values=after,
            )
        )
        self.session.flush()
        return {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "model_id": model_id,
            "name": subject.name if subject_type == "DEPARTMENT" else subject.role_name,
            **after,
        }

    def _department_ancestor_ids(self, user_id: int, departments: list[Department]) -> set[int]:
        with strict_tenant_filter():
            memberships = list(
                self.session.exec(
                    select(UserDepartment)
                    .join(Department, Department.id == UserDepartment.department_id)
                    .where(
                        UserDepartment.user_id == user_id,
                        Department.status == "active",
                        Department.tenant_id == require_tenant(),
                    )
                ).all()
            )
        return self._department_ancestor_ids_for(
            {int(membership.department_id) for membership in memberships}, departments
        )

    @staticmethod
    def _department_ancestor_ids_for(direct_ids: set[int], departments: list[Department]) -> set[int]:
        by_id = {int(row.id): row for row in departments}
        result: set[int] = set()
        for department_id in direct_ids:
            current = by_id.get(department_id)
            seen: set[int] = set()
            while current is not None and int(current.id) not in seen:
                current_id = int(current.id)
                seen.add(current_id)
                result.add(current_id)
                current = by_id.get(int(current.parent_id)) if current.parent_id is not None else None
        return result

    def department_scope_ids(self, department_id: int, *, include_descendants: bool) -> list[int]:
        if type(department_id) is not int or department_id < 1:
            raise DshInvalidRequestError()
        departments = self._departments()
        by_id = {int(row.id): row for row in departments}
        if department_id not in by_id:
            raise DshInvalidRequestError()
        if not include_descendants:
            return [department_id]
        children: dict[int, list[int]] = {}
        for row in departments:
            if row.parent_id is not None and int(row.parent_id) in by_id:
                children.setdefault(int(row.parent_id), []).append(int(row.id))
        result: list[int] = []
        stack = [department_id]
        while stack:
            current = stack.pop()
            result.append(current)
            stack.extend(reversed(children.get(current, [])))
        return result

    def selected_user_ids(self, subject_type: str, subject_id: int) -> list[int]:
        """Resolve the current selection; history comes from Gateway seats."""
        self._validate_subject(subject_type, subject_id)
        query = (
            select(User.user_id)
            .join(UserTenant, UserTenant.user_id == User.user_id)
            .where(
                UserTenant.tenant_id == require_tenant(),
                UserTenant.is_active == 1,
                UserTenant.status == "active",
                User.delete == 0,
            )
        )
        if subject_type == "DEPARTMENT":
            ids = self.department_scope_ids(subject_id, include_descendants=True)
            query = query.join(UserDepartment, UserDepartment.user_id == User.user_id).where(
                UserDepartment.department_id.in_(ids)
            )
        else:
            query = query.join(UserRole, UserRole.user_id == User.user_id).where(
                UserRole.tenant_id == require_tenant(), UserRole.role_id == subject_id
            )
        with strict_tenant_filter():
            return sorted({int(value) for value in self.session.exec(query).all()})

    def _role_ids(self, user_id: int) -> set[int]:
        tenant = require_tenant()
        with strict_tenant_filter():
            return {
                int(value)
                for value in self.session.exec(
                    select(UserRole.role_id).where(UserRole.tenant_id == tenant, UserRole.user_id == user_id)
                ).all()
            }

    @staticmethod
    def _matching_grants(
        grants: list[DshSubjectPolicy], department_ids: set[int], role_ids: set[int]
    ) -> list[DshSubjectPolicy]:
        return [
            row
            for row in grants
            if (row.subject_type == "DEPARTMENT" and row.subject_id in department_ids)
            or (row.subject_type == "ROLE" and row.subject_id in role_ids)
        ]

    def user_permissions(
        self,
        rows: list[tuple[int, str]],
        *,
        model_id: int,
        limit: int,
        selected_department_id: int | None = None,
    ) -> dict:
        """Explain the effective model permission for one bounded tenant user page."""
        tenant = require_tenant()
        if type(model_id) is not int or model_id < 1 or not 1 <= limit <= 100:
            raise DshInvalidRequestError()
        page_rows = rows[:limit]
        user_ids = [int(user_id) for user_id, _name in page_rows]
        departments = self._departments()
        department_by_id = {int(row.id): row for row in departments}

        memberships_by_user: dict[int, list[tuple[int, bool]]] = {user_id: [] for user_id in user_ids}
        roles_by_user: dict[int, list[tuple[int, str]]] = {user_id: [] for user_id in user_ids}
        direct_by_user: dict[int, list[DshUserPolicy]] = {user_id: [] for user_id in user_ids}
        grants: list[DshSubjectPolicy] = []
        if user_ids:
            with strict_tenant_filter():
                membership_rows = list(
                    self.session.exec(
                        select(
                            UserDepartment.user_id,
                            UserDepartment.department_id,
                            UserDepartment.is_primary,
                        )
                        .join(Department, Department.id == UserDepartment.department_id)
                        .where(
                            UserDepartment.user_id.in_(user_ids),
                            Department.tenant_id == tenant,
                            Department.status == "active",
                        )
                        .order_by(UserDepartment.user_id, UserDepartment.id)
                    ).all()
                )
                direct_rows = list(
                    self.session.exec(
                        select(DshUserPolicy).where(
                            DshUserPolicy.tenant_id == tenant,
                            DshUserPolicy.user_id.in_(user_ids),
                            DshUserPolicy.model_id == model_id,
                        )
                    ).all()
                )
                grants = list(
                    self.session.exec(
                        select(DshSubjectPolicy).where(
                            DshSubjectPolicy.tenant_id == tenant,
                            DshSubjectPolicy.model_id == model_id,
                            DshSubjectPolicy.enabled == 1,
                        )
                    ).all()
                )
            with bypass_tenant_filter():
                role_rows = list(
                    self.session.exec(
                        select(UserRole.user_id, Role.id, Role.role_name)
                        .join(Role, Role.id == UserRole.role_id)
                        .where(
                            UserRole.user_id.in_(user_ids),
                            UserRole.tenant_id == tenant,
                            or_(
                                Role.role_type == "global",
                                and_(Role.role_type == "tenant", Role.tenant_id == tenant),
                            ),
                        )
                        .order_by(UserRole.user_id, Role.role_name, Role.id)
                    ).all()
                )
            for user_id, department_id, is_primary in membership_rows:
                memberships_by_user[int(user_id)].append((int(department_id), bool(is_primary)))
            for user_id, role_id, role_name in role_rows:
                roles_by_user[int(user_id)].append((int(role_id), role_name))
            for row in direct_rows:
                direct_by_user[int(row.user_id)].append(row)

        items = []
        for user_id, user_name in page_rows:
            direct_policy = direct_by_user[user_id][0] if direct_by_user[user_id] else None
            direct_departments = memberships_by_user[user_id]
            direct_department_ids = {department_id for department_id, _primary in direct_departments}
            ancestor_ids = self._department_ancestor_ids_for(direct_department_ids, departments)
            user_roles = roles_by_user[user_id]
            role_ids = {role_id for role_id, _name in user_roles}
            matched = self._matching_grants(grants, ancestor_ids, role_ids)
            sources = [
                {
                    "subject_type": "USER",
                    "subject_id": user_id,
                    "name": user_name,
                    "monthly_token_limit": row.monthly_token_limit,
                    "inherited": False,
                }
                for row in direct_by_user[user_id]
                if row.enabled
            ]
            for row in matched:
                if row.subject_type == "DEPARTMENT":
                    subject = department_by_id.get(int(row.subject_id))
                    name = subject.name if subject is not None else str(row.subject_id)
                    inherited = int(row.subject_id) not in direct_department_ids
                else:
                    name = next(
                        (value for role_id, value in user_roles if role_id == row.subject_id),
                        str(row.subject_id),
                    )
                    inherited = False
                sources.append(
                    {
                        "subject_type": row.subject_type,
                        "subject_id": int(row.subject_id),
                        "name": name,
                        "monthly_token_limit": row.monthly_token_limit,
                        "inherited": inherited,
                    }
                )
            personal = bool(direct_policy and direct_policy.enabled)
            candidates = [source for source in sources if source["subject_type"] == "USER"] if personal else sources
            final_limit = max((source["monthly_token_limit"] for source in candidates), default=0)
            sources = [
                {**source, "winning": source in candidates and source["monthly_token_limit"] == final_limit}
                for source in sorted(
                    sources,
                    key=lambda source: (
                        -source["monthly_token_limit"],
                        source["subject_type"],
                        source["subject_id"],
                    ),
                )
            ]
            department_match = None
            if selected_department_id is not None:
                department_match = "DIRECT" if selected_department_id in direct_department_ids else "DESCENDANT"
            items.append(
                {
                    "user_id": user_id,
                    "user_name": user_name,
                    "direct_version": direct_policy.version if direct_policy else 0,
                    "direct_enabled": bool(direct_policy.enabled) if direct_policy else False,
                    "direct_monthly_token_limit": direct_policy.monthly_token_limit if direct_policy else 0,
                    "direct_pending_operation_id": direct_policy.pending_operation_id if direct_policy else None,
                    "departments": [
                        {
                            "id": department_id,
                            "name": department_by_id[department_id].name,
                            "is_primary": is_primary,
                        }
                        for department_id, is_primary in direct_departments
                        if department_id in department_by_id
                    ],
                    "roles": [{"id": role_id, "name": name} for role_id, name in user_roles],
                    "authorized": bool(sources) and final_limit > 0,
                    "monthly_token_limit": final_limit,
                    "sources": sources,
                    "department_match": department_match,
                }
            )
        has_more = len(rows) > limit
        return {
            "items": items,
            "has_more": has_more,
            "next_cursor": str(page_rows[-1][0]) if has_more and page_rows else None,
        }

    @staticmethod
    def _effective_version(sources: list[tuple[str, int, int, int]]) -> int:
        if len(sources) == 1 and sources[0][0] == "USER":
            return sources[0][2]
        payload = "personal-priority-v1|" + "|".join(
            f"{kind}:{subject_id}:{version}:{limit}" for kind, subject_id, version, limit in sources
        )
        value = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF
        return value or 1

    def effective(self, user_id: int, *, lock: bool = False) -> DshPolicySnapshot | None:
        tenant = require_tenant()
        direct_statement = (
            select(DshUserPolicy).where(DshUserPolicy.user_id == user_id).order_by(DshUserPolicy.model_id)
        )
        if lock:
            direct_statement = direct_statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            direct = [row for row in self.session.exec(direct_statement).all() if row.tenant_id == tenant]
        grant_statement = select(DshSubjectPolicy).where(
            DshSubjectPolicy.tenant_id == tenant,
            DshSubjectPolicy.enabled == 1,
        )
        if lock:
            grant_statement = grant_statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            tenant_grants = list(self.session.exec(grant_statement).all())
        grants: list[DshSubjectPolicy] = []
        if tenant_grants:
            departments = self._departments()
            department_ids = self._department_ancestor_ids(user_id, departments)
            role_ids = self._role_ids(user_id)
            grants = self._matching_grants(tenant_grants, department_ids, role_ids)
        sources_by_model: dict[int, list[tuple[str, int, int, int, str, int, bool]]] = {}
        for row in direct:
            sources_by_model.setdefault(row.model_id, []).append(
                (
                    "USER",
                    row.user_id,
                    row.version,
                    row.monthly_token_limit,
                    row.quota_sync_state,
                    row.quota_epoch,
                    bool(row.enabled),
                )
            )
        for row in grants:
            sources_by_model.setdefault(row.model_id, []).append(
                (row.subject_type, row.subject_id, row.version, row.monthly_token_limit, "READY", 1, True)
            )
        states = []
        direct_epochs = {row.quota_epoch for row in direct}
        if len(direct_epochs) > 1:
            raise ValueError("Direct policy rows disagree on the recovered usage epoch")
        epoch = next(iter(direct_epochs)) if direct_epochs else 1
        for model_id, sources in sorted(sources_by_model.items()):
            personal = [item for item in sources if item[0] == "USER" and item[6]]
            inherited = [item for item in sources if item[0] != "USER" and item[6] and item[3] > 0]
            candidates = personal or inherited or sources
            enabled_sources = [item for item in (personal or inherited) if item[3] > 0]
            limit = max(item[3] for item in (personal or inherited)) if personal or inherited else 0
            winning = [item for item in candidates if item[3] == limit] if personal or inherited else sources
            ready = any(item[4] == "READY" for item in winning)
            version_sources = sorted((item[0], item[1], item[2], item[3]) for item in sources)
            states.append(
                DshModelPolicyState(
                    model_id=model_id,
                    monthly_token_limit=limit,
                    enabled=int(bool(enabled_sources)),
                    version=self._effective_version(version_sources),
                    direct_version=next((row.version for row in direct if row.model_id == model_id), 0),
                    quota_epoch=epoch,
                    quota_sync_state="READY" if ready else "PENDING",
                    pending_operation_id=next(
                        (
                            row.pending_operation_id
                            for row in direct
                            if row.model_id == model_id and row.pending_operation_id is not None
                        ),
                        None,
                    ),
                )
            )
        return DshPolicySnapshot(tenant_id=tenant, user_id=user_id, rows=states) if states else None
