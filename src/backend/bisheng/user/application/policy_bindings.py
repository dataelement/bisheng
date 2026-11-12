"""User policy facts for trusted application callers; not a directory endpoint."""

from bisheng.user.domain.repositories.policy_binding_repository import PolicyBindingRepository, PolicySubjectFacts


async def read_policy_subject(user_id: int, *, session=None) -> PolicySubjectFacts:
    return await PolicyBindingRepository.subject(user_id, session=session)


def read_policy_subject_sync(user_id: int, *, session=None) -> PolicySubjectFacts:
    return PolicyBindingRepository.subject_sync(user_id, session=session)


async def replace_policy_bindings(user_id, expected_home, replace_ids, picked, *, operator_id=None):
    return await PolicyBindingRepository.replace(
        user_id, expected_home, set(replace_ids), set(picked), operator_id=operator_id
    )


async def grant_policy_bindings(user_id, expected_home, picked, *, operator_id=None):
    return await replace_policy_bindings(user_id, expected_home, set(), picked, operator_id=operator_id)


async def retire_invalid_policy_bindings(
    user_ids, *, session, derive_primary_home=False, operator_id=None, restrict_role_ids=None
):
    return await PolicyBindingRepository.retire_invalid(
        user_ids,
        session=session,
        derive_primary_home=derive_primary_home,
        operator_id=operator_id,
        restrict_role_ids=restrict_role_ids,
    )


async def affected_policy_users(*, session, department_ids=None, role_ids=None, subtree_path=None):
    return await PolicyBindingRepository.affected_users(
        session=session, department_ids=department_ids, role_ids=role_ids, subtree_path=subtree_path
    )


async def seed_policy_defaults(user_id, department_ids=None):
    """Only call for actual new membership or a new home activation, never snapshot replay."""
    from bisheng.department.application.business_scope import membership_policy_facts, policy_default_role_ids
    from bisheng.role.application.effective_roles import assignable_role_catalog

    subject = await read_policy_subject(user_id)
    facts = []
    for row in subject.memberships:
        if department_ids is not None and row.department_id not in department_ids:
            continue
        fact = await membership_policy_facts(row.department_id, subject.home_tenant_id)
        if fact:
            facts.append(fact)
    catalog = await assignable_role_catalog(facts)
    defaults = await policy_default_role_ids([fact.department_id for fact in facts])
    picked = {role.id for did, roles in catalog.items() for role in roles if role.id in defaults.get(did, [])}
    if picked:
        await grant_policy_bindings(user_id, subject.home_tenant_id, picked)


async def retire_current_policy_bindings(user_id):
    return await PolicyBindingRepository.retire_owned(user_id)


def policy_department_ids_sync(user_id, expected_home, *, session=None):
    from bisheng.common.errcode.role import RolePolicyUnavailableError
    from bisheng.department.application.business_scope import membership_policy_facts_sync

    subject = read_policy_subject_sync(user_id, session=session)
    if subject.home_tenant_id != expected_home:
        raise RolePolicyUnavailableError()
    result = set()
    for member in subject.memberships:
        facts = membership_policy_facts_sync(member.department_id, expected_home, session=session)
        if facts:
            result.update(facts.ancestor_ids)
        elif member.is_primary:
            raise RolePolicyUnavailableError()
    return result


async def retire_role_bindings(role_id, *, session, operator_id=None):
    return await PolicyBindingRepository.retire_role(role_id, session=session, operator_id=operator_id)


async def policy_membership_ids(user_id):
    return await PolicyBindingRepository.membership_ids(user_id)


async def initial_account_default_binding(user_id):
    return await PolicyBindingRepository.initial_account_default(user_id)


async def verify_resolved_policy_home(user_id, resolved_home):
    return await PolicyBindingRepository.verify_resolved_home(user_id, resolved_home)


async def terminate_policy_for_relocation(user_id):
    return await PolicyBindingRepository.terminate_for_relocation(user_id)
