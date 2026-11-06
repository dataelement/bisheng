"""Credential owner transaction guarantees. 覆盖 AC: AC-59, AC-58."""

import pytest

from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo
from test.app_runtime.test_secret_runtime_snapshot import secret_runtime as secret_runtime


async def candidate(env):
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding

    repo, app, _ = env
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation

    op = await repo.get(RuntimeOperation, "origin")
    async with repo.transaction() as session:
        await AppRuntimeCredentialService.stage_in_transaction(app.id, operation=op, session=session)
        rows = await repo.find(RuntimeCredentialBinding, operation_id=op.id)
    return rows[0]


async def audits(repo):
    from sqlmodel import select

    from bisheng.database.models.audit_log import AuditLog

    async with repo.transaction() as session:
        return list((await session.exec(select(AuditLog))).all())


async def test_issue_and_revoke_are_app_associated_and_replay_once(secret_runtime):
    from bisheng.open_api.domain.services.credential_service import CredentialService

    repo, app, _ = secret_runtime
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation

    op = await repo.get(RuntimeOperation, "origin")
    binding = await candidate(secret_runtime)
    rows = await audits(repo)
    assert len(rows) == 1
    assert rows[0].audit_metadata["app_id"] == app.id
    async with repo.transaction() as session:
        assert await CredentialService.revoke_runtime_binding(session, binding, op, reason="replaced") is True
        assert await CredentialService.revoke_runtime_binding(session, binding, op, reason="replaced") is False
    rows = await audits(repo)
    assert [r.action for r in rows] == ["open_api.api_key.issue", "open_api.api_key.revoke"]
    assert rows[-1].audit_metadata["operation_id"] == op.id


async def test_foreign_binding_cannot_forge_app_association(secret_runtime):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding
    from bisheng.open_api.domain.services.credential_service import CredentialService

    repo, _, _ = secret_runtime
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation

    op = await repo.get(RuntimeOperation, "origin")
    binding = await candidate(secret_runtime)
    async with repo.transaction():
        row = await repo.get(RuntimeCredentialBinding, binding.id, lock=True)
        row.app_id = "foreign-app"
        await repo.save(row)
    with pytest.raises(ValueError, match="binding"):
        async with repo.transaction() as session:
            await CredentialService.revoke_runtime_binding(session, binding, op, reason="replaced")
    assert len(await audits(repo)) == 1


async def test_audit_failure_rolls_back_revocation(secret_runtime, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding
    from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
    from bisheng.open_api.domain.services.credential_service import CredentialService

    repo, _, _ = secret_runtime
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation

    op = await repo.get(RuntimeOperation, "origin")
    binding = await candidate(secret_runtime)

    async def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(CredentialRepository, "append_runtime_revoke_audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        async with repo.transaction() as session:
            await CredentialService.revoke_runtime_binding(session, binding, op, reason="failed")
    row = await repo.get(RuntimeCredentialBinding, binding.id)
    assert row.state == "staged"
    assert len(await audits(repo)) == 1


async def test_terminal_stop_revokes_serving_binding(secret_runtime):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding, RuntimeOperation
    from bisheng.app_runtime.domain.services.runtime_projection_service import RuntimeProjectionService

    repo, _, _ = secret_runtime
    origin = await repo.get(RuntimeOperation, "origin")
    binding = await candidate(secret_runtime)
    async with repo.transaction():
        row = await repo.get(RuntimeCredentialBinding, binding.id, lock=True)
        row.state = "active"
        await repo.save(row)
    stop = RuntimeOperation(**{k: getattr(origin, k) for k in RuntimeOperation.model_fields})
    stop.id = "stop"
    stop.kind = "stop"
    stop.idempotency_key = "stop"
    await repo.save(stop)
    await RuntimeProjectionService(repo).terminal(stop, {"stopped": True})
    await RuntimeProjectionService(repo).terminal(stop, {"stopped": True})
    row = await repo.get(RuntimeCredentialBinding, binding.id)
    assert row.state == "revoked"
    assert len(await audits(repo)) == 2
