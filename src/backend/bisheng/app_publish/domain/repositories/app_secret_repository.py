"""Short App → configuration transactions. Never calls the runtime manager."""

from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlmodel import select, update

from bisheng.app_publish.domain.models.app_secret_config import AppSecretConfig
from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError, AppSecretRevisionConflictError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.database.models.audit_log import AuditLog


class AppSecretConfigRepository:
    def __init__(self, session_factory=get_async_db_session):
        self._factory = session_factory

    @asynccontextmanager
    async def transaction(self):
        async with self._factory() as session:
            try:
                with strict_tenant_filter():
                    yield session
                    await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def app(self, session, app_id, *, lock=False):
        statement = select(App).where(App.id == app_id)
        if lock:
            statement = statement.with_for_update()
        app = (await session.exec(statement)).first()
        if app is None or app.tenant_id != get_current_tenant_id():
            raise AppPublishOwnerOnlyError()
        return app

    async def config(self, session, app_id, *, lock=False):
        statement = select(AppSecretConfig).where(AppSecretConfig.app_id == app_id)
        if lock:
            statement = statement.with_for_update()
        return (await session.exec(statement)).first()

    async def read_config(self, app_id):
        async with self.transaction() as session:
            await self.app(session, app_id)
            return await self.config(session, app_id)

    async def version(self, session, app_id, version_id):
        if not version_id:
            return None
        return (
            await session.exec(select(AppVersion).where(AppVersion.app_id == app_id, AppVersion.id == version_id))
        ).first()

    async def store(self, session, app, previous, *, ciphertext, actor_id, expected_revision, now):
        if (previous.revision if previous else 0) != expected_revision:
            raise AppSecretRevisionConflictError()
        if previous is None:
            row = AppSecretConfig(
                app_id=app.id,
                tenant_id=app.tenant_id,
                revision=1,
                values_ciphertext=ciphertext,
                updated_by=actor_id,
                update_time=now,
            )
            try:
                session.add(row)
                await session.flush()
            except IntegrityError:
                raise AppSecretRevisionConflictError() from None
        else:
            result = await session.exec(
                update(AppSecretConfig)
                .where(
                    AppSecretConfig.app_id == app.id,
                    AppSecretConfig.tenant_id == app.tenant_id,
                    AppSecretConfig.revision == expected_revision,
                )
                .values(
                    revision=expected_revision + 1, values_ciphertext=ciphertext, updated_by=actor_id, update_time=now
                )
            )
            if result.rowcount != 1:
                raise AppSecretRevisionConflictError()
        return expected_revision + 1

    async def append_audit(self, session, app, actor, *, name, action, revision, present):
        session.add(
            AuditLog(
                tenant_id=app.tenant_id,
                operator_tenant_id=actor.tenant_id,
                operator_id=actor.user_id,
                operator_name=actor.user_name,
                action=action,
                target_type="app",
                target_id=app.id,
                object_name=app.name,
                audit_metadata={"app_id": app.id, "name": name, "revision": revision, "present": present},
            )
        )
        await session.flush()

    async def delete_asset(self, session, app_id):
        row = await self.config(session, app_id, lock=True)
        if row is not None:
            await session.delete(row)
            await session.flush()
