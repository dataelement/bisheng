"""Caller-owned preview lifecycle and identity references, without ORM exports."""

from bisheng.app_publish.domain.repositories.preview_runtime_repository import PreviewRuntimeRepository, binding


async def lock_version(session, *, tenant_id, app_id, version_id):
    await PreviewRuntimeRepository.lock_version(session, tenant_id, app_id, version_id)


async def lock_operation_version(session, operation):
    if operation.kind == "preview":
        await lock_version(
            session, tenant_id=operation.tenant_id, app_id=operation.app_id, version_id=operation.version_id
        )


async def find_reusable(session, **key):
    row = await PreviewRuntimeRepository.reuse(session, **key)
    return binding(row) if row else None


async def register(session, values):
    return binding(await PreviewRuntimeRepository.create(session, values))


async def bind_identity(session, session_id, *, operation_id, credential_id):
    return await PreviewRuntimeRepository.bind_identity(
        session, session_id, operation_id=operation_id, credential_id=credential_id
    )


async def by_reference(**reference):
    return await PreviewRuntimeRepository.by_reference(**reference)


async def activate(session, operation):
    return await PreviewRuntimeRepository.activate(
        session,
        session_id=operation.payload.get("session_id"),
        tenant_id=operation.tenant_id,
        app_id=operation.app_id,
        version_id=operation.version_id,
        operation_id=operation.id,
    )


async def close(session, operation, *, reason):
    from bisheng.open_api.application.runtime_credentials import revoke_preview_credential

    identity = await PreviewRuntimeRepository.closing_identity(
        session,
        session_id=operation.payload.get("session_id"),
        tenant_id=operation.tenant_id,
        app_id=operation.app_id,
        version_id=operation.version_id,
        operation_id=operation.id,
    )
    if identity is None:
        return
    row, subject_id = identity
    await revoke_preview_credential(
        session, credential_id=row.credential_id, tenant_id=row.tenant_id, subject_id=subject_id, reason=reason
    )
    await PreviewRuntimeRepository.mark_closed(session, row.session_id, reason=reason)


async def issue_identity(session, *, app_id, operation, scopes, expires_at, session_id):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService

    issued = await AppRuntimeCredentialService.preview_in_transaction(
        app_id, operation=operation, scopes=scopes, session=session, expires_at=expires_at
    )
    await bind_identity(session, session_id, operation_id=operation.id, credential_id=issued.id)
    return issued.plaintext
