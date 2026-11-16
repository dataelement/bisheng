from bisheng.common.errcode.role import RolePermissionDeniedError
from bisheng.common.request_scope import get_admitted_request_scope
from bisheng.user.application.policy_bindings import read_policy_subject


async def require_management_subject(user_id):
    admitted = get_admitted_request_scope()
    if admitted is None or admitted.kind != "tenant":
        return
    subject = await read_policy_subject(user_id)
    if subject.home_tenant_id != admitted.tenant_id:
        raise RolePermissionDeniedError()
