"""T019 覆盖 AC-03, AC-09, AC-18, AC-20, AC-22, AC-23。

使用实际 User SQLModel 声明。旧通用夹具的 user_name UNIQUE 与当前表不一致。
"""

from contextlib import asynccontextmanager
from importlib import import_module

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.external_identity_projection import UserExternalIdentityProjection
from bisheng.user.domain.models.user import User
from test.fixtures.table_definitions import TABLE_USER_ROLE


@pytest.fixture
async def owner():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync: SQLModel.metadata.create_all(
                sync, tables=[User.__table__, UserExternalIdentityProjection.__table__]
            )
        )

        # 角色关联沿用项目 SQLite 夹具。它不证明真实库的复合自增键语义。
        await conn.execute(
            text(
                TABLE_USER_ROLE.replace(
                    "role_id INTEGER NOT NULL,", "role_id INTEGER NOT NULL, tenant_id INTEGER NOT NULL DEFAULT 1,"
                )
            )
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    token = current_tenant_id.set(1)
    try:
        try:
            module = import_module("bisheng.user.application.external_identity")
        except ModuleNotFoundError as exc:
            if exc.name != "bisheng.user.application.external_identity":
                raise
            pytest.fail("T020 user projection application is not implemented", pytrace=False)
        repository = module.UserExternalIdentityProjectionRepository(sessions)
        yield module.KunlianExternalIdentityApplication(repository), sessions, module
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


def identity(module, *, subject="subject-1", tid="tenant-1", name="同名", active=True):
    return module.ExternalShadowIdentity(
        issuer="https://fixture.example",
        subject=subject,
        external_tenant_id=tid,
        member_id="member-" + subject,
        display_name=name,
        active=active,
    )


async def project(app, value, rev):
    operation = await app.reserve_external_shadow(value, rev)
    user_id = await app.ensure_external_shadow(value, rev, operation=operation)
    return user_id, operation


async def test_stable_identity_does_not_claim_names_or_other_sources(owner):
    app, sessions, module = owner
    value = identity(module)
    async with sessions() as session:
        original = User(user_name="同名", password="", source="local", external_id=value.external_id)
        session.add(original)
        await session.commit()
        original_id = original.user_id
    created, op = await project(app, value, "a" * 64)
    assert created != original_id
    assert await app.ensure_external_shadow(value, "a" * 64, operation=op) == created
    renamed, _ = await project(app, identity(module, name="新名称"), "b" * 64)
    other, _ = await project(app, identity(module, tid="tenant-2"), "c" * 64)
    assert renamed == created and other != created
    async with sessions() as session:
        assert (await session.get(User, original_id)).source == "local"
        assert (await session.get(User, created)).user_name == "新名称"
        assert not (await session.exec(select(UserRole))).all()
        assert len((await session.exec(select(User))).all()) == 3


@pytest.mark.parametrize("new_revision", ["a" * 64, "b" * 64])
async def test_old_operation_cannot_write_after_newer_applied_revision(owner, new_revision):
    app, sessions, module = owner
    old_value = identity(module, name="旧名称")
    old = await app.reserve_external_shadow(old_value, "a" * 64)
    new_value = identity(module, name="新名称")
    current, newest = await project(app, new_value, new_revision)
    with pytest.raises(KunlianBindingConflictError):
        await app.ensure_external_shadow(old_value, "a" * 64, operation=old)
    with pytest.raises(KunlianBindingConflictError):
        await app.ensure_external_shadow(new_value, "c" * 64, operation=newest)
    async with sessions() as session:
        assert (await session.get(User, current)).user_name == "新名称"
        state = await session.get(UserExternalIdentityProjection, new_value.identity_key)
        assert state.applied_fence == newest.fence and state.applied_source_revision == new_revision


async def test_disable_restore_preserves_manual_status_and_authorization(owner):
    app, sessions, module = owner
    uid, _ = await project(app, identity(module), "a" * 64)
    async with sessions() as session:
        session.add(UserRole(user_id=uid, role_id=910))
        await session.commit()
    await project(app, identity(module, active=False), "b" * 64)
    async with sessions() as session:
        disabled = await session.get(User, uid)
        assert disabled.delete == 1 and disabled.disable_source == "kunlian"
    await project(app, identity(module), "c" * 64)
    async with sessions() as session:
        manual = await session.get(User, uid)
        assert manual.delete == 0
        manual.delete, manual.disable_source = 1, "manual"
        session.add(manual)
        await session.commit()
    await project(app, identity(module, name="仍可更新资料"), "d" * 64)
    async with sessions() as session:
        kept = await session.get(User, uid)
        assert kept.delete == 1 and kept.disable_source == "manual"
        assert len((await session.exec(select(UserRole))).all()) == 1


async def test_reserved_operation_checks_full_identity_on_digest_collision(owner, monkeypatch):
    app, _, module = owner
    first = identity(module)
    await project(app, first, "a" * 64)
    original_key = first.identity_key
    monkeypatch.setattr(module.ExternalShadowIdentity, "identity_key", property(lambda _: original_key))
    with pytest.raises(KunlianBindingConflictError):
        await project(app, identity(module, subject="another-subject"), "b" * 64)


async def test_user_and_applied_receipt_rollback_together(owner):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from sqlmodel import Session

    from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

    app, sessions, module = owner
    value = identity(module)
    operation = await app.reserve_external_shadow(value, "a" * 64)

    def fail_applied_receipt(session, *_):
        if any(isinstance(row, UserExternalIdentityProjection) and row.applied_fence > 0 for row in session.dirty):
            raise OperationalError("fixture receipt", None, RuntimeError("fixture storage unavailable"))

    event.listen(Session, "before_flush", fail_applied_receipt)
    try:
        with pytest.raises(KunlianDependencyUnavailableError):
            await app.ensure_external_shadow(value, "a" * 64, operation=operation)
    finally:
        event.remove(Session, "before_flush", fail_applied_receipt)
    async with sessions() as session:
        assert not (await session.exec(select(User))).all()
        state = await session.get(UserExternalIdentityProjection, value.identity_key)
        assert state.user_id is None and state.applied_fence == 0
    assert await app.ensure_external_shadow(value, "a" * 64, operation=operation) > 0
    receipt = await app.read_projection_receipt(operation)
    assert receipt.fence == operation.fence


async def test_current_account_qualification_and_frozen_payload_use_live_owner_facts(owner):
    from unittest.mock import AsyncMock

    from pydantic import ValidationError

    from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError

    app, sessions, module = owner
    value = identity(module)
    uid, _ = await project(app, value, "a" * 64)
    async with sessions() as session:
        session.add(UserRole(user_id=uid, role_id=910))
        user = await session.get(User, uid)
        user.token_version = 3
        session.add(user)
        await session.commit()
    if not hasattr(app, "read_current_qualification"):
        pytest.fail("T036 current user qualification is not implemented", pytrace=False)
    current = await app.read_current_qualification(uid, identity_key=value.identity_key)
    assert current.user_id == uid and current.token_version == 3 and current.role_ids == (910,)
    app.global_super_checker = AsyncMock(return_value=False)
    principal = await app.build_admitted_payload(current, local_tenant_id=7)
    assert principal.user_id == uid and principal.tenant_id == 7 and principal.user_role == [910]
    with pytest.raises(ValidationError):
        principal.tenant_id = 8
    async with sessions() as session:
        user = await session.get(User, uid)
        user.delete = 1
        session.add(user)
        await session.commit()
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.read_current_qualification(uid, identity_key=value.identity_key)
