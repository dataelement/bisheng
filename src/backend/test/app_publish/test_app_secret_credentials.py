"""Candidate issuance atomicity. 覆盖 AC: AC-68, AC-70, AC-77, AC-81, AC-82."""

from types import SimpleNamespace

import pytest
from sqlmodel import select


async def test_candidate_and_issue_audit_rollback_with_caller(publish_engine, publish_db, app_factory):
    from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.open_api.domain.models.api_credential import ApiCredential

    async with publish_engine.begin() as connection:
        await connection.run_sync(lambda conn: RuntimeCredentialBinding.__table__.create(conn, checkfirst=True))
    app, version = await app_factory()
    operation = SimpleNamespace(id="candidate-op", app_id=app.id, tenant_id=app.tenant_id, version_id=version.id)
    with pytest.raises(RuntimeError, match="seal failed"):
        async with publish_db() as session:
            plaintext = await AppRuntimeCredentialService.stage_in_transaction(
                app.id, operation=operation, session=session
            )
            assert plaintext.startswith("bs-app-")
            assert (await session.exec(select(HostedAppSubject))).first()
            assert (await session.exec(select(ApiCredential))).first()
            assert (await session.exec(select(RuntimeCredentialBinding))).first()
            assert (await session.exec(select(AuditLog).where(AuditLog.action == "open_api.api_key.issue"))).first()
            await session.rollback()
            raise RuntimeError("seal failed")
    async with publish_db() as session:
        for model in [HostedAppSubject, ApiCredential, RuntimeCredentialBinding]:
            assert (await session.exec(select(model))).first() is None
        assert (await session.exec(select(AuditLog).where(AuditLog.action == "open_api.api_key.issue"))).first() is None


async def test_candidate_is_returned_from_flushed_rows_without_new_session(
    publish_engine, publish_db, app_factory, monkeypatch
):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding
    from bisheng.open_api.domain.services.credential_service import CredentialService

    async with publish_engine.begin() as connection:
        await connection.run_sync(lambda conn: RuntimeCredentialBinding.__table__.create(conn, checkfirst=True))
    app, version = await app_factory()

    async def forbidden(*args, **kwargs):
        pytest.fail("candidate opened an independent response lookup")

    monkeypatch.setattr(CredentialService, "_to_item", forbidden)
    op = SimpleNamespace(id="candidate-op", app_id=app.id, tenant_id=app.tenant_id, version_id=version.id)
    async with publish_db() as session:
        value = await AppRuntimeCredentialService.stage_in_transaction(app.id, operation=op, session=session)
        assert value
        await session.commit()
    async with publish_db() as session:
        assert (await session.exec(select(RuntimeCredentialBinding))).one().operation_id == op.id
