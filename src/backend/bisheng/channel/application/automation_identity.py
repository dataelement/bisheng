"""Server-owned channel automation restores a current person, never a JWT."""

from bisheng.channel.domain.repositories.reference_binding_repository import ChannelReferenceBindingRepository
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.user.application.runtime_identity import resolve_preview_person


async def resolve_channel_automation_identity(session, channel_id: str, sync_config_id: str, *, tenant_id: int):
    """Only the real stored configuration selects this delayed-work identity.

    This is internal automation, not restoration of the configuring browser
    session. Its current active membership must still own this exact tenant.
    No ambient principal or permission actor is cleared or replaced.
    """
    if (
        type(tenant_id) is not int
        or tenant_id <= 0
        or get_current_tenant_id() != tenant_id
        or is_tenant_filter_bypassed()
        or get_current_open_api_principal() is not None
        or get_current_public_api_principal() is not None
    ):
        raise PermissionDeniedError(reason="channel_automation_context_invalid")
    repository = ChannelReferenceBindingRepository()
    channel = await repository.aget(session, channel_id)
    if channel is None or channel.tenant_id != tenant_id:
        raise PermissionDeniedError(reason="channel_automation_source_invalid")
    configs = await repository.alist_sync_rows(session, channel.id)
    config = next((row for row in configs if row.id == sync_config_id), None)
    if config is None or type(config.user_id) is not int or config.user_id <= 0:
        raise PermissionDeniedError(reason="channel_automation_configuration_invalid")
    identity = await resolve_preview_person(config.user_id)
    if identity.user_id != config.user_id or identity.tenant_id != tenant_id:
        raise PermissionDeniedError(reason="channel_automation_membership_changed")
    actor = get_current_permission_actor()
    if actor is not None and (
        actor.subject_type != "user" or actor.subject_id != identity.user_id or actor.current_tenant_id != tenant_id
    ):
        raise PermissionDeniedError(reason="channel_automation_actor_mismatch")
    return identity
