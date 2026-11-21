from bisheng.common.errcode.role import RolePermissionDeniedError
from bisheng.common.request_scope import get_admitted_request_scope
from bisheng.user.application.policy_bindings import read_management_home


async def require_management_subject(user_id):
    admitted = get_admitted_request_scope()
    if admitted is None or admitted.kind != "tenant":
        return
    home_tenant_id = await read_management_home(user_id)
    if home_tenant_id != admitted.tenant_id:
        raise RolePermissionDeniedError()
