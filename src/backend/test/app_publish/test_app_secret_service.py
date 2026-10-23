"""Owner environment save behavior. 覆盖 AC: AC-66, AC-67, AC-68, AC-73, AC-74, AC-75, AC-77, AC-79, AC-80, AC-81, AC-83, AC-85, AC-89, AC-90."""

import json
from types import SimpleNamespace

import pytest
from sqlmodel import select

from test.app_publish.test_app_secret_repository import secret_repository as secret_repository


async def test_save_is_encrypted_and_has_no_runtime_side_effects(secret_repository, app_factory, owner_user):
    from bisheng.app_publish.domain.models.app_secret_config import AppSecretConfig
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService
    from bisheng.common.errcode.app_publish import AppSecretRevisionConflictError
    from bisheng.database.models.audit_log import AuditLog

    repo, cipher = secret_repository
    app, _ = await app_factory()
    service = AppSecretService(repository=repo, cipher=cipher)
    saved = await service.save(app.id, "TOKEN", value="秘密\n raw ", expected_revision=0, actor=owner_user.payload)
    assert saved["revision"] == 1 and saved["present"]
    assert "operation_id" not in saved
    async with repo.transaction() as session:
        row = (await session.exec(select(AppSecretConfig))).one()
        assert row.revision == 1 and "秘密" not in row.values_ciphertext
        events = (await session.exec(select(AuditLog).where(AuditLog.action == "app.secret.set"))).all()
        assert len(events) == 1
        assert "秘密" not in str(events[0].model_dump())
    with pytest.raises(AppSecretRevisionConflictError):
        await service.save(app.id, "TOKEN", value="stale", expected_revision=0, actor=owner_user.payload)
    response = await service.get(app.id, actor=owner_user.payload)
    assert response["items"][0]["mask"] == "••••••"
    assert response["runtime"]["comparison"] == "not_running"
    assert "秘密" not in json.dumps(response, ensure_ascii=False, default=str)
    deleted = await service.delete(app.id, "TOKEN", expected_revision=1, actor=owner_user.payload)
    assert deleted["revision"] == 2
    assert (await service.get(app.id, actor=owner_user.payload))["revision"] == 2
    async with repo.transaction() as session:
        assert (await session.exec(select(AppSecretConfig))).one().revision == 2


async def test_owner_only_and_cross_tenant_denial(secret_repository, app_factory, owner_user, monkeypatch):
    from bisheng.app_publish.domain.services import app_secret_service as module
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError

    repo, cipher = secret_repository
    app, _ = await app_factory()
    service = module.AppSecretService(repository=repo, cipher=cipher)
    for actor in [
        UserPayload(user_id=123, user_name="admin", user_role=[], tenant_id=1, is_global_super=True),
        UserPayload(user_id=owner_user.user_id, user_name="owner", user_role=[], tenant_id=2),
        SimpleNamespace(user_id=owner_user.user_id, tenant_id=1),
    ]:
        with pytest.raises(AppPublishOwnerOnlyError):
            await service.save(app.id, "TOKEN", value="x", expected_revision=0, actor=actor)

    async def admin(*args):
        return True

    monkeypatch.setattr(module, "check_tenant_admin", admin)
    await service.save(app.id, "PRIVATE", value="hidden", expected_revision=0, actor=owner_user.payload)
    admin_actor = UserPayload(user_id=123, user_name="admin", user_role=[], tenant_id=1)
    assert (await service.get(app.id, actor=admin_actor))["items"] == []


async def test_delete_online_reference_requires_confirmation_and_deleted_app_cannot_save(
    secret_repository, app_factory, owner_user
):
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService
    from bisheng.common.errcode.app_publish import AppPublishStateConflictError, AppSecretInvalidError

    repo, cipher = secret_repository
    app, version = await app_factory(state="online", terminal_state="online")
    async with repo.transaction() as session:
        version.capabilities = {"secrets": [{"name": "TOKEN"}]}
        session.add(version)
    service = AppSecretService(repository=repo, cipher=cipher)
    await service.save(app.id, "TOKEN", value="x", expected_revision=0, actor=owner_user.payload)
    with pytest.raises(AppSecretInvalidError):
        await service.delete(app.id, "TOKEN", expected_revision=1, actor=owner_user.payload)
    await service.delete(app.id, "TOKEN", expected_revision=1, actor=owner_user.payload, confirm_online_impact=True)
    async with repo.transaction() as session:
        app.state = "deleted"
        session.add(app)
    with pytest.raises(AppPublishStateConflictError):
        await service.save(app.id, "TOKEN", value="x", expected_revision=2, actor=owner_user.payload)
    await service.delete_for_app(app.id)
    assert await repo.read_config(app.id) is None
