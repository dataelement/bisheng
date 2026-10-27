"""Credential owner protocol used by runtime projections."""


async def revoke_runtime_binding(session, binding, operation, *, reason):
    from bisheng.open_api.domain.services.credential_service import CredentialService

    return await CredentialService.revoke_runtime_binding(session, binding, operation, reason=reason)
