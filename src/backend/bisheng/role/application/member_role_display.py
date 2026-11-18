"""Read-only role names and diagnostics for an authorized organization page."""

from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.constants import AdminRole
from bisheng.department.application.business_scope import membership_policy_facts
from bisheng.role.application.effective_roles import validate_policy_home
from bisheng.role.domain.repositories.effective_role_repository import EffectiveRoleRepository
from bisheng.user.application.policy_bindings import read_directory_policy_subjects


async def read_member_role_display(user_ids: set[int], *, tenant_id: int, include_issues: bool = False) -> dict:
    """The caller verifies directory scope before passing these exact IDs.

    Diagnostics do not repair data or stand in for the strict admission policy.
    An affiliation in this directory never discloses another home's private roles.
    """
    if type(tenant_id) is not int or tenant_id <= 0 or get_current_tenant_id() != tenant_id:
        raise ValueError("The directory business tenant must be current")
    subjects = await read_directory_policy_subjects(user_ids)
    own = {uid: subject for uid, subject in subjects.items() if subject.home_tenant_id == tenant_id}
    role_ids = {row.role_id for subject in own.values() for row in subject.bindings if row.role_id != AdminRole}
    definitions = {row.id: row for row in await EffectiveRoleRepository.definitions(role_ids)}
    department_facts = {}
    result = {uid: {"roles": [], **({"role_binding_issues": []} if include_issues else {})} for uid in user_ids}
    for uid, subject in own.items():
        members = []
        for member in subject.memberships:
            if member.department_id not in department_facts:
                department_facts[member.department_id] = await membership_policy_facts(member.department_id, tenant_id)
            facts = department_facts[member.department_id]
            if facts is None and member.is_primary:
                raise RolePolicyUnavailableError()
            if facts is not None:
                members.append((member, facts))
        validate_policy_home(subject, members, tenant_id)
        visible_roles = {}
        for binding in subject.bindings:
            if binding.role_id == AdminRole:
                continue
            role = definitions.get(binding.role_id)
            # The release line preserves every existing v3.0.0 person grant.
            # Storage tenant and definition scope constrain assignment, not reads.
            reason = "definition_missing" if role is None else None
            if reason is None:
                visible_roles[role.id] = {"id": role.id, "role_name": role.role_name}
            elif include_issues:
                result[uid]["role_binding_issues"].append(
                    {
                        "binding_id": binding.id,
                        "role_id": binding.role_id,
                        "role_name": role.role_name if role else None,
                        "reason": reason,
                    }
                )
        result[uid]["roles"] = sorted(visible_roles.values(), key=lambda row: row["id"])
    return result
