"""Narrow organization-directory contracts for account management consumers."""

from bisheng.department.domain.repositories.directory_repository import DirectoryRepository
from bisheng.department.domain.services.directory_scope import organization_directory_scope


async def management_directory_facts(tenant_id):
    return await DirectoryRepository.scope(tenant_id)


def management_directory_facts_sync(tenant_id):
    return DirectoryRepository.scope_sync(tenant_id)


async def initialize_account_at_mount(user, directory, actor):
    from bisheng.department.domain.services.department_service import DepartmentService

    async with organization_directory_scope():
        department = await DirectoryRepository.root_department(directory)
        return await DepartmentService.ainitialize_local_member(user, department.dept_id, actor)


async def department_display_records(tenant_id, department_ids):
    """Read known references after resource authorization; never a Grant admission decision."""
    return await DirectoryRepository.display_records(tenant_id, department_ids)


async def require_directory_department(department_id):
    """Validate a known department inside the current verified directory scope."""
    await DirectoryRepository.require_department(department_id)
