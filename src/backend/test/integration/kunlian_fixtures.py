"""F118 专用真实存储夹具。默认跳过且从不创建或修改表结构。"""

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def storage_settings(environ):
    """只接受显式指定的独立测试库。不读取应用默认连接。"""
    names = ("F118_TEST_DATABASE_URL", "F118_TEST_REDIS_URL")
    if any(not environ.get(name) for name in names):
        raise ValueError("需要显式设置 F118_TEST_DATABASE_URL 和 F118_TEST_REDIS_URL")
    try:
        database, redis = (make_url(environ[name]) for name in names)
    except ArgumentError:
        raise ValueError("测试连接 URL 格式非法") from None
    if not database.host or not database.username or not redis.host:
        raise ValueError("必须显式指定数据库主机/用户和 Redis 主机")
    schema = database.query.get("schema") or database.database or ""
    if database.drivername not in {"mysql+asyncmy", "dm+dmAsync"} or not schema.lower().startswith("e2e_kunlian_"):
        raise ValueError("只允许 mysql+asyncmy 或 dm+dmAsync 的 e2e_kunlian_ 专用库/schema")
    if redis.drivername not in {"redis", "rediss"} or not (redis.database or "").isdigit():
        raise ValueError("Redis 必须显式指定独立数字 DB")
    if int(redis.database) < 1:
        raise ValueError("测试禁止使用 Redis DB 0")
    if database.drivername == "dm+dmAsync" and database.database:
        raise ValueError("DM8 请用 ?schema=e2e_kunlian_... 并保持 URL path 为空")
    return database, redis


@dataclass(repr=False)
class LiveStorage:
    connection_id: str
    issuer: str
    sessions: tuple
    repositories: tuple
    owners: tuple
    redis: tuple
    identity_keys: set[str] = field(default_factory=set)

    def identity(self, *, name="当前名称", active=True):
        from bisheng.user.domain.repositories.external_identity_projection import ExternalShadowIdentity

        value = ExternalShadowIdentity(self.issuer, self.connection_id, self.connection_id, "member", name, active)
        self.identity_keys.add(value.identity_key)
        return value

    async def publish(self, *, status="ACTIVE"):
        repo = self.repositories[0]
        value = self.identity(active=status == "ACTIVE")
        lease = await repo.claim_or_renew_lease(self.connection_id, "publisher", key_version="test", page_size=20)
        assert lease is not None
        await repo.stage_page(
            lease,
            tenants=[{"external_tenant_id": self.connection_id, "status": "ACTIVE", "summary": {}}],
            members=[
                {
                    "external_tenant_id": self.connection_id,
                    "member_id": value.member_id,
                    "subject": value.subject,
                    "status": status,
                    "deleted": False,
                    "summary": {"display_name": value.display_name},
                }
            ],
            next_cursor_ciphertext=None,
        )
        await repo.publish_directory(lease, issuer=self.issuer)
        return await repo.get_binding(value.identity_key)

    async def prepare_session(self):
        """直接建立仓储测试前提。不声称验证租户 Owner 或真实 OIDC。"""
        repo, owner = self.repositories[0], self.owners[0]
        await repo.bind_tenant(
            self.connection_id, self.connection_id, verified_local_tenant_id=1, expected_revision=None
        )
        binding = await self.publish()
        value = self.identity()
        operation = await owner.reserve(value, binding.source_revision)
        uid = await owner.ensure_shadow(value, binding.source_revision, operation=operation)
        await repo.freeze_projection_mapping(value.identity_key)
        async with repo.projection_scope(value.identity_key) as (_, _, complete):
            await complete(uid)
        return await repo.get_binding(value.identity_key)

    async def cleanup(self):
        """按本次随机连接和已登记身份精确清理。不扫描其他测试或业务数据。"""
        from sqlmodel import select

        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.sso_sync.domain.models.kunlian import (
            KunlianConnectionState,
            KunlianDirectoryMember,
            KunlianDirectoryTenant,
            KunlianHandoffReceipt,
            KunlianIdentityBinding,
            KunlianSyncBatch,
            KunlianTenantBinding,
            KunlianWebSession,
        )
        from bisheng.user.domain.models.external_identity_projection import UserExternalIdentityProjection
        from bisheng.user.domain.models.user import User
        from bisheng.user.domain.models.user_role import UserRole

        async with self.sessions[0]() as session, session.begin():
            batches = (
                await session.exec(
                    select(KunlianSyncBatch).where(
                        KunlianSyncBatch.connection_id == self.connection_id,
                        KunlianSyncBatch.tenant_id == 1,
                    )
                )
            ).all()
            bindings = (
                await session.exec(
                    select(KunlianIdentityBinding).where(
                        KunlianIdentityBinding.connection_id == self.connection_id,
                        KunlianIdentityBinding.tenant_id == 1,
                    )
                )
            ).all()
            for model, condition in [
                (KunlianHandoffReceipt, KunlianHandoffReceipt.connection_id == self.connection_id),
                (KunlianWebSession, KunlianWebSession.binding_id.in_([row.identity_key for row in bindings])),
                (KunlianDirectoryMember, KunlianDirectoryMember.batch_id.in_([row.batch_id for row in batches])),
                (KunlianDirectoryTenant, KunlianDirectoryTenant.batch_id.in_([row.batch_id for row in batches])),
                (KunlianIdentityBinding, KunlianIdentityBinding.connection_id == self.connection_id),
                (KunlianTenantBinding, KunlianTenantBinding.connection_id == self.connection_id),
                (KunlianSyncBatch, KunlianSyncBatch.connection_id == self.connection_id),
                (KunlianConnectionState, KunlianConnectionState.connection_id == self.connection_id),
            ]:
                for row in (await session.exec(select(model).where(condition, model.tenant_id == 1))).all():
                    await session.delete(row)
                await session.flush()
            for key in self.identity_keys:
                state = await session.get(UserExternalIdentityProjection, key)
                if state is None:
                    continue
                assert state.issuer == self.issuer and state.subject == self.connection_id
                user = await session.get(User, state.user_id) if state.user_id is not None else None
                await session.delete(state)
                await session.flush()
                if user is not None:
                    assert user.source == "kunlian" and user.external_id == "kunlian:" + key
                    with bypass_tenant_filter():
                        roles = (await session.exec(select(UserRole).where(UserRole.user_id == user.user_id))).all()
                    # 本夹具不创建授权。发现意外关系时停止清理而不是删除人工记录。
                    assert not roles, "测试用户出现非本套件授权,停止清理"
                    await session.delete(user)


@pytest.fixture
async def live_storage(record_property):
    if os.environ.get("F118_STORAGE") != "1":
        pytest.skip("待执行:显式设置 F118_STORAGE=1 并提供专用 MySQL/DM8 与 Redis")
    try:
        database, redis_url = storage_settings(os.environ)
    except ValueError as error:
        pytest.fail(str(error), pytrace=False)

    from redis.asyncio import Redis
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.sso_sync.domain.repositories.kunlian import KunlianDirectoryRepository
    from bisheng.user.domain.repositories.external_identity_projection import UserExternalIdentityProjectionRepository

    engines = tuple(create_async_engine(database, echo=False, hide_parameters=True, pool_size=3) for _ in range(2))
    clients = tuple(Redis.from_url(redis_url.render_as_string(hide_password=False)) for _ in range(2))

    def factory(engine):
        @asynccontextmanager
        async def sessions():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

        return sessions

    sessions = tuple(factory(engine) for engine in engines)
    cipher = Fernet(Fernet.generate_key())
    repositories = tuple(
        KunlianDirectoryRepository(
            session,
            encrypt_value=lambda value: cipher.encrypt(value.encode()).decode(),
            decrypt_value=lambda value: cipher.decrypt(value.encode()).decode(),
            key_version="test",
        )
        for session in sessions
    )
    run = "e2e-kunlian-" + uuid4().hex
    storage = LiveStorage(
        run,
        "https://e2e-kunlian.invalid/" + run,
        sessions,
        repositories,
        tuple(UserExternalIdentityProjectionRepository(session) for session in sessions),
        clients,
    )
    initialized = False
    try:
        async with engines[0].connect() as connection:
            tables = await connection.run_sync(lambda conn: {name.lower() for name in inspect(conn).get_table_names()})
            required = {
                "kunlian_connection_state",
                "kunlian_sync_batch",
                "kunlian_directory_tenant",
                "kunlian_directory_member",
                "kunlian_tenant_binding",
                "kunlian_identity_binding",
                "kunlian_web_session",
                "kunlian_handoff_receipt",
                "user_external_identity_projection",
                "user",
                "user_role",
            }
            assert required <= tables, "专用环境缺表;测试不会自动建表"
            record_property("database_dialect", connection.dialect.name)
            record_property("database_version", str(connection.dialect.server_version_info))
        assert all([await client.ping() for client in clients])
        record_property("repository_instances", 2)
        with tenant_execution_scope(1):
            initialized = True
            await repositories[0].apply_connection_policy(run, enabled=True, policy_revision=1)
            yield storage
    finally:
        try:
            if initialized:
                with tenant_execution_scope(1):
                    await storage.cleanup()
        finally:
            for client in clients:
                await client.aclose()
            for engine in engines:
                await engine.dispose()
