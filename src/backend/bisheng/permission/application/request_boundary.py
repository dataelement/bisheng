"""Negative business-target boundary, independent of action privileges."""

from bisheng.common.request_scope import get_admitted_request_scope
from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_current_tenant_id


def request_business_target():
    target = get_admin_scope_tenant_id()
    if target is not None:
        return target
    admitted = get_admitted_request_scope()
    if admitted is not None and admitted.source == "credential" and admitted.tenant_id == get_current_tenant_id():
        return admitted.tenant_id
    return None
