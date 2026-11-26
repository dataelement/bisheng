"""Department-owner facts; callers authorize management or a verified subject."""

from bisheng.department.domain.repositories.policy_scope_repository import (
    DepartmentPolicyFacts,
    PolicyScopeRepository,
)


async def department_policy_facts(department_id: int, *, session=None) -> DepartmentPolicyFacts:
    """Internal fact reader, not an HTTP authorization or arbitrary directory API."""
    return await PolicyScopeRepository.department(department_id, session=session)


def department_policy_facts_sync(department_id: int, *, session=None) -> DepartmentPolicyFacts:
    return PolicyScopeRepository.department_sync(department_id, session=session)


async def resolve_verified_department_scope(department_id: int, actor) -> DepartmentPolicyFacts:
    from bisheng.department.domain.services.department_service import _check_permission

    await _check_permission(actor, department_id)
    return await department_policy_facts(department_id)


async def membership_policy_facts(department_id: int, home_tenant_id: int, *, session=None):
    """A known foreign affiliation is inapplicable; uncertain home facts fail."""
    return await PolicyScopeRepository.department(department_id, home_tenant_id=home_tenant_id, session=session)


def membership_policy_facts_sync(department_id: int, home_tenant_id: int, *, session=None):
    return PolicyScopeRepository.department_sync(department_id, home_tenant_id=home_tenant_id, session=session)


async def binding_cleanup_department_facts(department_id, *, session, home_tenant_id=None):
    """Same-UoW topology facts for retiring grants; never used to grant or authorize."""
    return await PolicyScopeRepository.department(
        department_id, session=session, home_tenant_id=home_tenant_id, for_binding_cleanup=True
    )


async def policy_default_role_ids(department_ids):
    return await PolicyScopeRepository.defaults(department_ids)


def business_departments_sync(business_tenant_id, *, session=None):
    return PolicyScopeRepository.business_departments_sync(business_tenant_id, session=session)


async def load_policy_edit_department(department_id):
    return await PolicyScopeRepository.edit_department(department_id)
