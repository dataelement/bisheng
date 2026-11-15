"""User-owned policy facts and bindings, narrowed to one server-verified person."""

from dataclasses import dataclass

from sqlmodel import select

from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.org_snapshot import astamp_audit_logs
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.user import User


@dataclass(frozen=True)
class PolicySubjectFacts:
    user_id: int
    home_tenant_id: int
    bindings: tuple[UserRole, ...]
    memberships: tuple[UserDepartment, ...]


def _home(user, homes, tenant) -> int:
    if user is None or user.delete or len(homes) > 1:
        raise RolePolicyUnavailableError()
    if not homes:
        if settings.multi_tenant.enabled:
            raise RolePolicyUnavailableError()
        return 1
    if homes[0].status != "active" or tenant is None or tenant.status != "active":
        raise RolePolicyUnavailableError()
    return int(homes[0].tenant_id)


def _memberships(user_id: int):
    return (
        select(UserDepartment)
        .join(Department, Department.id == UserDepartment.department_id)
        .where(UserDepartment.user_id == user_id, Department.status == "active", Department.is_deleted == 0)
    )


class PolicyBindingRepository:
    @staticmethod
    async def subject(user_id: int, *, session=None, cleanup=False, current_read=False) -> PolicySubjectFacts:
        if session is None:
            async with get_async_db_session() as owned_session:
                return await PolicyBindingRepository.subject(
                    user_id, session=owned_session, cleanup=cleanup, current_read=current_read
                )
        with bypass_tenant_filter():
            user = (await session.exec(select(User).where(User.user_id == user_id))).first()
            homes = (
                await session.exec(select(UserTenant).where(UserTenant.user_id == user_id, UserTenant.is_active == 1))
            ).all()
            tenant = await session.get(Tenant, homes[0].tenant_id) if homes else None
            if cleanup:
                if user is None or len(homes) > 1:
                    raise RolePolicyUnavailableError()
                home = int(homes[0].tenant_id) if homes else 1
            else:
                home = _home(user, homes, tenant)
            bindings_query = select(UserRole).where(UserRole.user_id == user_id)
            members_query = _memberships(user_id)
            if current_read:
                bindings_query = bindings_query.with_for_update().execution_options(populate_existing=True)
                members_query = members_query.with_for_update().execution_options(populate_existing=True)
            bindings = (await session.exec(bindings_query)).all()
            members = (await session.exec(members_query)).all()
        return PolicySubjectFacts(user_id, home, tuple(bindings), tuple(members))

    @staticmethod
    def subject_sync(user_id: int, *, session=None) -> PolicySubjectFacts:
        if session is None:
            with get_sync_db_session() as owned_session:
                return PolicyBindingRepository.subject_sync(user_id, session=owned_session)
        with bypass_tenant_filter():
            user = session.exec(select(User).where(User.user_id == user_id)).first()
            homes = session.exec(
                select(UserTenant).where(UserTenant.user_id == user_id, UserTenant.is_active == 1)
            ).all()
            tenant = session.get(Tenant, homes[0].tenant_id) if homes else None
            home = _home(user, homes, tenant)
            bindings = session.exec(select(UserRole).where(UserRole.user_id == user_id)).all()
            members = session.exec(_memberships(user_id)).all()
        return PolicySubjectFacts(user_id, home, tuple(bindings), tuple(members))

    @staticmethod
    async def affected_users(*, session, department_ids=None, role_ids=None, subtree_path=None):
        with bypass_tenant_filter():
            if subtree_path is not None:
                statement = (
                    select(UserDepartment.user_id)
                    .join(Department, Department.id == UserDepartment.department_id)
                    .where(Department.path.like(f"{subtree_path}%"))
                )
            elif department_ids is not None:
                statement = select(UserDepartment.user_id).where(UserDepartment.department_id.in_(department_ids))
            elif role_ids is not None:
                statement = select(UserRole.user_id).where(UserRole.role_id.in_(role_ids))
            else:
                raise ValueError("An exact affected set is required")
            return sorted(set((await session.exec(statement)).all()))

    @staticmethod
    async def _supported(subject, session, *, derive_primary_home=False, for_retirement=False):
        from bisheng.department.application.business_scope import (
            binding_cleanup_department_facts,
            department_policy_facts,
            membership_policy_facts,
        )

        primaries = [row for row in subject.memberships if row.is_primary]
        if len(primaries) > 1:
            raise RolePolicyUnavailableError()
        facts = None
        if primaries:
            facts = await (
                binding_cleanup_department_facts(primaries[0].department_id, session=session)
                if for_retirement
                else department_policy_facts(primaries[0].department_id, session=session)
            )
            if facts is None:
                raise RolePolicyUnavailableError()
        primary_home = facts.business_tenant_id if facts else 1
        home = (
            (primary_home if primaries else subject.home_tenant_id) if derive_primary_home else subject.home_tenant_id
        )
        if not derive_primary_home and home != primary_home:
            raise RolePolicyUnavailableError()
        supported = set()
        for member in subject.memberships:
            facts = await (
                binding_cleanup_department_facts(member.department_id, home_tenant_id=home, session=session)
                if for_retirement
                else membership_policy_facts(member.department_id, home, session=session)
            )
            if facts:
                supported.update(facts.ancestor_ids)
        return home, supported

    @staticmethod
    async def _audit(session, subject, removed, added, *, operator_id=None, reason="EXPLICIT_BINDING_CHANGE"):
        if not removed and not added:
            return
        row = AuditLog(
            operator_id=operator_id if operator_id is not None else -1,
            operator_name=None,
            group_ids=None,
            system_id="system",
            event_type="update_user",
            object_type="user_conf",
            object_id=str(subject.user_id),
            object_name=None,
            note="Managed tenant role bindings changed",
            ip_address=None,
            tenant_id=subject.home_tenant_id,
            action="user.role_bindings_changed",
            target_type="user",
            target_id=str(subject.user_id),
            audit_metadata={"removed": sorted(removed), "added": sorted(added), "reason": reason},
        )
        await astamp_audit_logs([row])
        session.add(row)

    @classmethod
    async def replace(cls, user_id, expected_home, replace_ids, picked, *, operator_id=None):
        from bisheng.role.application.effective_roles import eligible_role, lock_binding_definitions

        if AdminRole in picked or AdminRole in replace_ids:
            raise RolePolicyUnavailableError()
        async with get_async_db_session() as session:
            definitions = await lock_binding_definitions(session, set(picked) | set(replace_ids))
            with bypass_tenant_filter():
                await session.exec(select(User).where(User.user_id == user_id).with_for_update())
                subject = await cls.subject(user_id, session=session)
                home, supported = await cls._supported(subject, session)
                if home != expected_home:
                    raise RolePolicyUnavailableError()
                legal = {role.id for role in definitions if eligible_role(role, home, supported)}
                if not set(picked).issubset(legal):
                    raise RolePolicyUnavailableError()
                existing = {row.role_id for row in subject.bindings if row.tenant_id == home}
                removed = set()
                for row in subject.bindings:
                    if row.tenant_id == home and row.role_id in replace_ids and row.role_id not in picked:
                        removed.add(row.role_id)
                        await session.delete(row)
                added = set(picked) - existing
                session.add_all([UserRole(user_id=user_id, role_id=rid, tenant_id=home) for rid in sorted(added)])
                await cls._audit(session, subject, removed, added, operator_id=operator_id)
                await session.commit()

    @classmethod
    async def retire_invalid(
        cls, user_ids, *, session, derive_primary_home=False, operator_id=None, restrict_role_ids=None
    ):
        from bisheng.role.application.effective_roles import eligible_role, lock_binding_definitions

        await session.flush()
        for uid in sorted(set(user_ids)):
            subject = await cls.subject(uid, session=session, cleanup=True)
            initial_bindings = {
                (row.role_id, row.tenant_id, row.id)
                for row in subject.bindings
                if row.role_id != AdminRole and (restrict_role_ids is None or row.role_id in restrict_role_ids)
            }
            ids = {
                row.role_id
                for row in subject.bindings
                if row.role_id != AdminRole and (restrict_role_ids is None or row.role_id in restrict_role_ids)
            }
            definitions = {row.id: row for row in await lock_binding_definitions(session, ids)}
            with bypass_tenant_filter():
                await session.exec(select(User).where(User.user_id == uid).with_for_update())
                subject = await cls.subject(uid, session=session, cleanup=True, current_read=True)
                observed = {
                    row.role_id
                    for row in subject.bindings
                    if row.role_id != AdminRole and (restrict_role_ids is None or row.role_id in restrict_role_ids)
                }
                current_bindings = {
                    (row.role_id, row.tenant_id, row.id)
                    for row in subject.bindings
                    if row.role_id != AdminRole and (restrict_role_ids is None or row.role_id in restrict_role_ids)
                }
                if not observed.issubset(ids) or not current_bindings.issubset(initial_bindings):
                    # A concurrent grant committed after the first read. Roll back this UoW and retry
                    # from fresh facts instead of taking definition locks in a different order.
                    raise RolePolicyUnavailableError()
                home, supported = await cls._supported(
                    subject, session, derive_primary_home=derive_primary_home, for_retirement=True
                )
                removed = set()
                for row in subject.bindings:
                    if row.role_id == AdminRole or (
                        restrict_role_ids is not None and row.role_id not in restrict_role_ids
                    ):
                        continue
                    definition = definitions.get(row.role_id)
                    if row.tenant_id != home or definition is None or not eligible_role(definition, home, supported):
                        removed.add(row.role_id)
                        await session.delete(row)
                await cls._audit(
                    session, subject, removed, set(), operator_id=operator_id, reason="SCOPE_OR_HOME_INVALID"
                )

    @classmethod
    async def retire_owned(cls, user_id):
        async with get_async_db_session() as session:
            await cls.retire_invalid([user_id], session=session, derive_primary_home=True)
            await session.commit()

    @classmethod
    async def retire_role(cls, role_id, *, session, operator_id=None):
        if role_id == AdminRole:
            raise RolePolicyUnavailableError()
        users = await cls.affected_users(session=session, role_ids=[role_id])
        with bypass_tenant_filter():
            for uid in users:
                await session.exec(select(User).where(User.user_id == uid).with_for_update())
                subject = await cls.subject(uid, session=session, cleanup=True)
                removed = set()
                for row in subject.bindings:
                    if row.role_id == role_id:
                        removed.add(row.role_id)
                        await session.delete(row)
                await cls._audit(session, subject, removed, set(), operator_id=operator_id, reason="ROLE_DELETED")

    @staticmethod
    async def membership_ids(user_id):
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return set(
                    (
                        await session.exec(
                            select(UserDepartment.department_id).where(UserDepartment.user_id == user_id)
                        )
                    ).all()
                )

    @staticmethod
    async def initial_account_default(user_id):
        from bisheng.database.constants import DefaultRole

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return (
                    await session.exec(
                        select(UserRole.id)
                        .where(UserRole.user_id == user_id, UserRole.role_id == DefaultRole, UserRole.tenant_id == 1)
                        .limit(1)
                    )
                ).first() is not None

    @classmethod
    async def verify_resolved_home(cls, user_id, resolved_home):
        from bisheng.department.application.business_scope import department_policy_facts

        subject = await cls.subject(user_id, cleanup=True)
        primaries = [row for row in subject.memberships if row.is_primary]
        if len(primaries) > 1:
            raise RolePolicyUnavailableError()
        expected = (await department_policy_facts(primaries[0].department_id)).business_tenant_id if primaries else 1
        if expected != resolved_home:
            raise RolePolicyUnavailableError()

    @classmethod
    async def terminate_for_relocation(cls, user_id):
        from bisheng.role.application.effective_roles import lock_binding_definitions

        async with get_async_db_session() as session:
            subject = await cls.subject(user_id, session=session, cleanup=True)
            original = {(row.role_id, row.tenant_id, row.id) for row in subject.bindings if row.role_id != AdminRole}
            await lock_binding_definitions(
                session, {row.role_id for row in subject.bindings if row.role_id != AdminRole}
            )
            with bypass_tenant_filter():
                await session.exec(select(User).where(User.user_id == user_id).with_for_update())
                subject = await cls.subject(user_id, session=session, cleanup=True, current_read=True)
                current = {(row.role_id, row.tenant_id, row.id) for row in subject.bindings if row.role_id != AdminRole}
                if not current.issubset(original):
                    raise RolePolicyUnavailableError()
                removed = set()
                for row in subject.bindings:
                    if row.role_id != AdminRole:
                        removed.add(row.role_id)
                        await session.delete(row)
                await cls._audit(session, subject, removed, set(), reason="HOME_RELOCATION")
                await session.commit()
