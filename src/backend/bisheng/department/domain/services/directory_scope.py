"""Translate only the organization request to its proven storage owner."""

from contextlib import asynccontextmanager, contextmanager

from bisheng.common.request_scope import get_admitted_request_scope
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.department.domain.repositories.directory_repository import DirectoryRepository
from bisheng.department.domain.schemas.directory_scope import current_directory_scope


@asynccontextmanager
async def organization_directory_scope():
    admitted = get_admitted_request_scope()
    if admitted is None or admitted.kind != "tenant":
        yield  # Trusted domain callers retain their established explicit context.
        return
    scope = await DirectoryRepository.scope(admitted.tenant_id)
    token = current_directory_scope.set(scope)
    try:
        # Department and membership storage stays unchanged; this scope is local to this API group.
        with tenant_execution_scope(scope.storage_tenant_id):
            yield
    finally:
        current_directory_scope.reset(token)


@contextmanager
def directory_business_data_scope():
    scope = current_directory_scope.get()
    if scope is None:
        yield
    else:
        with tenant_execution_scope(scope.tenant_id):
            yield


async def own_primary_department(user_id, user):
    from bisheng.common.errcode.http_error import UnAuthorizedError

    if user_id != user.user_id:
        raise UnAuthorizedError()
    return await DirectoryRepository.primary_for_identity(user_id, user.tenant_id)
