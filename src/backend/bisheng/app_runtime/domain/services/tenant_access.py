"""Tenant eligibility is independent from each action's original permission rules."""

from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.open_api.application.access_context import get_current_open_api_principal


def require_app_request_tenant(app_tenant_id: int, actor, *, allow_global_super: bool = False) -> None:
    if actor is None:
        raise AppNotFoundError()
    principal = get_current_open_api_principal()
    if principal is not None:
        caller_tenant = principal.tenant_id
        is_super = principal.actor_kind == "natural_person" and bool(getattr(actor, "is_global_super", False))
    else:
        caller_tenant = getattr(actor, "tenant_id", None)
        is_super = bool(getattr(actor, "is_global_super", False))
    if allow_global_super and is_super:
        return
    if caller_tenant is None or int(caller_tenant) != int(app_tenant_id):
        raise AppNotFoundError()
