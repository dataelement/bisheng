"""Preserve actual model ownership/sharing checks without a reference index."""

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.domain.repositories.model_selection_repository import ModelSelectionRepository
from bisheng.permission.application import PermissionSubject, get_permission_relation_api
from bisheng.permission.application.relation_api import get_permission_relation_api_sync
from bisheng.resource_reference.application.contracts import TargetType


def _filter(rows, tenant, child, shared):
    return {
        key: row
        for key, row in rows.items()
        if row.tenant_id == tenant or (row.tenant_id == 1 and child and str(row.server_id) in shared)
    }


async def read_models(session, ids):
    tenant = get_current_tenant_id()
    rows, child = await ModelSelectionRepository().aread(session, tenant, tuple(sorted({int(value) for value in ids})))
    shared = ()
    if child and any(row.tenant_id != tenant for row in rows.values()):
        port = await get_permission_relation_api()
        shared = await port.list_resource_ids(
            subject=PermissionSubject("tenant", str(tenant)), relation="shared_with", resource_type="llm_server"
        )
    return _filter(rows, tenant, child, shared)


def read_models_sync(session, ids):
    tenant = get_current_tenant_id()
    rows, child = ModelSelectionRepository().read(session, tenant, tuple(sorted({int(value) for value in ids})))
    shared = ()
    if child and any(row.tenant_id != tenant for row in rows.values()):
        shared = get_permission_relation_api_sync().list_resource_ids_sync(
            subject=PermissionSubject("tenant", str(tenant)), relation="shared_with", resource_type="llm_server"
        )
    return _filter(rows, tenant, child, shared)


async def require_new_models(session, references, old=()):
    keys = {ref.target for ref in set(references) - set(old) if ref.target.target_type == TargetType.MODEL}
    rows = await read_models(session, tuple(key.target_id for key in keys))
    if keys - rows.keys():
        raise ResourceReferenceInvalidError(reason="model_selection_unavailable")
