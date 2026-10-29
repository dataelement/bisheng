"""Real transaction coverage. 覆盖 AC: AC-67, AC-68, AC-77, AC-80, AC-81, AC-83."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError
from sqlmodel import select


@pytest.fixture()
async def secret_repository(publish_engine, publish_db):
    from bisheng.app_publish.domain.models.app_secret_config import AppSecretConfig
    from bisheng.app_publish.domain.repositories.app_secret_repository import AppSecretConfigRepository
    from bisheng.app_publish.domain.secret_security import AppSecretCipher

    async with publish_engine.begin() as connection:
        await connection.run_sync(lambda conn: AppSecretConfig.__table__.create(conn, checkfirst=True))
    repo = AppSecretConfigRepository(session_factory=publish_db)
    return repo, AppSecretCipher(Fernet.generate_key().decode())


async def test_audit_failure_rolls_back_configuration(secret_repository, app_factory, owner_user, monkeypatch):
    from bisheng.app_publish.domain.models.app_secret_config import AppSecretConfig
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService

    repo, cipher = secret_repository
    app, _ = await app_factory()

    async def fail(*args, **kwargs):
        raise RuntimeError("audit insertion failed")

    monkeypatch.setattr(repo, "append_audit", fail)
    service = AppSecretService(repository=repo, cipher=cipher)
    with pytest.raises(RuntimeError, match="audit insertion"):
        await service.save(app.id, "TOKEN", value="hidden", expected_revision=0, actor=owner_user.payload)
    async with repo.transaction() as session:
        assert (await session.exec(select(AppSecretConfig))).first() is None


async def test_caller_transaction_rolls_back_and_enforces_binding(secret_repository, app_factory, owner_user):
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService
    from bisheng.common.errcode.app_publish import AppSecretEncryptionUnavailableError

    repo, cipher = secret_repository
    app, version = await app_factory(state="online", terminal_state="online")
    service = AppSecretService(repository=repo, cipher=cipher)
    await service.save(app.id, "TOKEN", value="live-value", expected_revision=0, actor=owner_user.payload)
    version.capabilities = {"secrets": [{"name": "TOKEN"}]}
    async with repo.transaction() as session:
        snapshot = await service.formal_snapshot(app, version, session=session, expected_revision=1)
        assert snapshot.env == {"TOKEN": "live-value"}
        assert snapshot.sensitive_env_names == ["TOKEN"]
    other, _ = await app_factory()
    async with repo.transaction() as session:
        with pytest.raises(AppSecretEncryptionUnavailableError):
            await service.formal_snapshot(other, version, session=session)


async def test_missing_context_cannot_write_tenantless_model(secret_repository, monkeypatch):
    from bisheng.app_publish.domain.models.app_secret_config import AppSecretConfig
    from bisheng.core.context.tenant import set_current_tenant_id

    repo, cipher = secret_repository
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    set_current_tenant_id(None)
    with pytest.raises(IntegrityError):
        async with repo.transaction() as session:
            session.add(
                AppSecretConfig(
                    app_id="no-context",
                    values_ciphertext=cipher.encrypt({}, tenant_id=1, app_id="no-context"),
                    updated_by=1,
                )
            )
            await session.flush()
