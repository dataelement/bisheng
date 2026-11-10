"""Credential owner protocol used by runtime projections."""


async def revoke_runtime_binding(session, binding, operation, *, reason):
    from bisheng.open_api.domain.services.credential_service import CredentialService

    return await CredentialService.revoke_runtime_binding(session, binding, operation, reason=reason)


async def revoke_preview_credential(session, **binding):
    from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository

    return await CredentialRepository.revoke_preview_credential(session, **binding)


async def preview_credential_is_live(credential_id, tenant_id, app_id):
    from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository

    return await CredentialRepository.preview_credential_is_live(credential_id, tenant_id, app_id)
