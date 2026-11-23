"""Current operator qualification shared by model picking and invocation."""


async def require_model_operator(user_id: int) -> bool:
    """Require an active model operator; return whether global authority applies."""
    from bisheng.common.errcode.dsh import DshUserDisabledError
    from bisheng.dsh.domain.repositories.admin_operation import require_tenant
    from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
    from bisheng.utils.http_middleware import _check_is_global_super

    # A selected tenant is a resource boundary, never an administrator grant.
    # HTTP admission supplies the verified identity; workers recheck it fresh.
    tenant = require_tenant()
    administrator = await _check_is_global_super(user_id, force_refresh=True)
    identities = CurrentIdentityRecords()
    identity = (
        await identities.get_model_administrator(str(tenant), str(user_id))
        if administrator
        else await identities.get(str(tenant), str(user_id))
    )
    if not identity or not identity.active or not identity.tenant_active or not identity.natural_person:
        raise DshUserDisabledError()
    return administrator
