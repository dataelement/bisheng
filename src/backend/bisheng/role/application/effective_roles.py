"""One current ordinary policy for trusted identity / budget / menu consumers."""

from dataclasses import dataclass

from loguru import logger

from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.database.constants import AdminRole
from bisheng.department.application.business_scope import membership_policy_facts, membership_policy_facts_sync
from bisheng.role.domain.repositories.effective_role_repository import EffectiveRoleRepository
from bisheng.user.application.policy_bindings import read_policy_subject, read_policy_subject_sync


@dataclass(frozen=True)
class EffectiveRoles:
    user_id: int
    home_tenant_id: int
    role_ids: tuple[int, ...]
    roles: tuple
    web_menu: frozenset[str]
    is_identity_admin: bool


def _binding_ids(subject) -> set[int]:
    return {
        int(row.role_id)
        for row in subject.bindings
        if row.role_id != AdminRole and row.tenant_id == subject.home_tenant_id
    }


def eligible_role(role, home_tenant_id: int, supported_department_ids: set[int]) -> bool:
    """Shared by reads and synchronous binding producers; no grant-source fiction."""
    definition_allowed = role.role_type == "global" or (
        role.role_type in ("tenant", "", None) and role.tenant_id == home_tenant_id
    )
    return bool(definition_allowed and (role.department_id is None or role.department_id in supported_department_ids))


async def assignable_role_catalog(department_facts) -> dict[int, list]:
    """Only department-owner verified business facts can define this catalog."""
    facts = list(department_facts)
    roles = await EffectiveRoleRepository.assignable_definitions(
        {row.business_tenant_id for row in facts}, {did for row in facts for did in row.ancestor_ids}
    )
    return {
        row.department_id: [
            role for role in roles if eligible_role(role, row.business_tenant_id, set(row.ancestor_ids))
        ]
        for row in facts
    }


def _resolve(subject, definitions, member_facts, expected_home):
    home = subject.home_tenant_id
    if expected_home is not None and home != expected_home:
        raise RolePolicyUnavailableError()
    primaries = [facts.business_tenant_id for member, facts in member_facts if member.is_primary]
    if len(primaries) > 1 or (primaries[0] if primaries else 1) != home:
        raise RolePolicyUnavailableError()
    bound = _binding_ids(subject)
    if bound - {int(row.id) for row in definitions}:
        raise RolePolicyUnavailableError()
    supported = {did for _, facts in member_facts if facts.business_tenant_id == home for did in facts.ancestor_ids}
    return tuple(sorted((row for row in definitions if eligible_role(row, home, supported)), key=lambda row: row.id))


async def load_effective_roles(user_id: int, *, expected_home_tenant_id: int | None = None) -> EffectiveRoles:
    try:
        subject = await read_policy_subject(user_id)
        definitions = await EffectiveRoleRepository.definitions(_binding_ids(subject))
        members = []
        for member in subject.memberships:
            facts = await membership_policy_facts(member.department_id, subject.home_tenant_id)
            if facts is None and member.is_primary:
                raise RolePolicyUnavailableError()
            if facts is not None:
                members.append((member, facts))
        roles = _resolve(subject, definitions, members, expected_home_tenant_id)
        return EffectiveRoles(
            user_id,
            subject.home_tenant_id,
            tuple(int(row.id) for row in roles),
            roles,
            await EffectiveRoleRepository.menu(roles),
            any(row.role_id == AdminRole for row in subject.bindings),
        )
    except RolePolicyUnavailableError:
        raise
    except Exception as exc:
        logger.exception("Unable to verify current role policy for user={}", user_id)
        raise RolePolicyUnavailableError() from exc


def load_effective_roles_sync(
    user_id: int, *, expected_home_tenant_id: int | None = None, session=None
) -> EffectiveRoles:
    try:
        subject = read_policy_subject_sync(user_id, session=session)
        definitions = EffectiveRoleRepository.definitions_sync(_binding_ids(subject), session=session)
        members = []
        for member in subject.memberships:
            facts = membership_policy_facts_sync(member.department_id, subject.home_tenant_id, session=session)
            if facts is None and member.is_primary:
                raise RolePolicyUnavailableError()
            if facts is not None:
                members.append((member, facts))
        roles = _resolve(subject, definitions, members, expected_home_tenant_id)
        return EffectiveRoles(
            user_id,
            subject.home_tenant_id,
            tuple(int(row.id) for row in roles),
            roles,
            EffectiveRoleRepository.menu_sync(roles, session=session),
            any(row.role_id == AdminRole for row in subject.bindings),
        )
    except RolePolicyUnavailableError:
        raise
    except Exception as exc:
        logger.exception("Unable to verify current role policy for user={}", user_id)
        raise RolePolicyUnavailableError() from exc


async def lock_binding_definitions(session, role_ids: set[int]):
    """User binding writer locks definitions before subjects, matching role-scope updates."""
    return await EffectiveRoleRepository.locked_definitions(session, role_ids)


async def validate_policy_role_ids(home_tenant_id, role_ids, supported_department_ids=()):
    from bisheng.common.errcode.role import RolePermissionDeniedError

    ids = set(role_ids)
    definitions = await EffectiveRoleRepository.definitions(ids)
    if (
        AdminRole in ids
        or {row.id for row in definitions} != ids
        or any(not eligible_role(row, home_tenant_id, set(supported_department_ids)) for row in definitions)
    ):
        raise RolePermissionDeniedError(msg="Role is not eligible for the user's home tenant")
