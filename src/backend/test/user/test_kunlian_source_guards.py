"""T021 覆盖 AC-03, AC-14, AC-17, AC-18, AC-23, AC-25。保留来源与人工停用。"""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError
from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding
from bisheng.user.domain.models.user import User, UserCreate
from bisheng.user.domain.services.user import UserService
from test.sso import test_kunlian_directory as directory_tests
from test.user import test_kunlian_external_identity as user_tests

owner = user_tests.owner
directory_store = directory_tests.directory_store


@pytest.mark.parametrize(
    "source,external_id", [("kunlian", "plain"), ("KUNLIAN", "plain"), ("local", "kunlian:reserved")]
)
async def test_self_registration_cannot_create_reserved_identity(source, external_id, monkeypatch):
    from bisheng.user.domain.services import user as service_module

    monkeypatch.setattr(service_module, "settings", SimpleNamespace(get_from_db=lambda _: False))
    monkeypatch.setattr(
        service_module.UserDao,
        "aget_by_external_id",
        AsyncMock(side_effect=AssertionError("reserved registration reached ordinary lookup")),
    )
    with pytest.raises(KunlianBindingConflictError):
        await UserService.user_register(
            UserCreate(user_name="fixture", source=source, external_id=external_id, password="fixture")
        )


@pytest.mark.parametrize("field,value", [("source", "local"), ("external_id", "ordinary"), ("delete", 1)])
async def test_generic_profile_update_cannot_rewrite_reserved_user(owner, monkeypatch, field, value):
    from bisheng.user.domain.services import user as service_module

    app, sessions, module = owner
    uid, _ = await user_tests.project(app, user_tests.identity(module), "a" * 64)
    monkeypatch.setattr(service_module, "get_async_db_session", sessions)
    monkeypatch.setattr(UserService, "_dsh_enabled", lambda: False)
    async with sessions() as session:
        changed = await session.get(User, uid)
        session.expunge(changed)
    setattr(changed, field, value)
    with pytest.raises(KunlianBindingConflictError):
        await UserService.apersist_profile_update(changed)
    async with sessions() as session:
        current = await session.get(User, uid)
        assert current.source == "kunlian" and current.delete == 0 and current.external_id.startswith("kunlian:")


async def test_local_account_cannot_be_relabelled_as_reserved(owner, monkeypatch):
    from bisheng.user.domain.services import user as service_module

    _, sessions, _ = owner
    async with sessions() as session:
        row = User(user_name="local", source="local", external_id="local", password="")
        session.add(row)
        await session.commit()
        session.expunge(row)
    row.source = "kunlian"
    monkeypatch.setattr(service_module, "get_async_db_session", sessions)
    with pytest.raises(KunlianBindingConflictError):
        await UserService.apersist_profile_update(row)


async def test_manual_override_and_owner_disable_restore_are_serialized(owner, directory_store):
    app, sessions, module = owner
    uid, _ = await user_tests.project(app, user_tests.identity(module), "a" * 64)
    repo, control_sessions, _, _ = directory_store
    async with control_sessions() as session:
        value = user_tests.identity(module)
        session.add(
            KunlianIdentityBinding(
                identity_key=value.identity_key,
                connection_id="fixture",
                issuer=value.issuer,
                subject=value.subject,
                external_tenant_id=value.external_tenant_id,
                member_id=value.member_id,
                local_user_id=uid,
                source_revision="a" * 64,
                projected_revision="a" * 64,
                projection_status="SUCCEEDED",
                admission_status="ACTIVE",
            )
        )
        await session.commit()
    entry = import_module("bisheng.sso_sync.application.kunlian")
    if not hasattr(entry, "KunlianManualAccountApplication"):
        pytest.fail("T022 manual override coordinator is not implemented", pytrace=False)
    manual = entry.KunlianManualAccountApplication(repo)
    await manual.set_account_status(uid, disabled=True, user_owner=app)
    async with sessions() as session:
        async with control_sessions() as control:
            binding = await control.get(KunlianIdentityBinding, value.identity_key)
        row = await session.get(User, uid)
        assert binding.local_override is True and binding.auth_epoch == 2
        assert row.delete == 1 and row.disable_source == "manual"
    await user_tests.project(app, user_tests.identity(module, name="同步后仍停用"), "b" * 64)
    async with sessions() as session:
        assert (await session.get(User, uid)).delete == 1
        async with control_sessions() as control:
            binding = await control.get(KunlianIdentityBinding, value.identity_key)
    async with control_sessions() as control:
        binding = await control.get(KunlianIdentityBinding, value.identity_key)
        binding.admission_status = "DISABLED"
        control.add(binding)
        await control.commit()
    await manual.set_account_status(uid, disabled=False, user_owner=app)
    async with sessions() as session:
        async with control_sessions() as control:
            binding = await control.get(KunlianIdentityBinding, value.identity_key)
        row = await session.get(User, uid)
        assert binding.local_override is False and binding.auth_epoch == 3
        assert row.delete == 1 and row.disable_source == "kunlian"
    # Owner 失败时不把未完成的管理操作发布为成功。
    app.set_manual_status = AsyncMock(side_effect=KunlianBindingConflictError())
    with pytest.raises(KunlianBindingConflictError):
        await manual.set_account_status(uid, disabled=True, user_owner=app)
    async with sessions() as session:
        async with control_sessions() as control:
            assert (await control.get(KunlianIdentityBinding, value.identity_key)).local_override is False


async def test_profile_guard_also_blocks_attached_session_autoflush(owner, monkeypatch):
    app, sessions, module = owner
    uid, _ = await user_tests.project(app, user_tests.identity(module), "a" * 64)
    monkeypatch.setattr(UserService, "_dsh_enabled", lambda: False)
    with pytest.raises(KunlianBindingConflictError):
        async with sessions() as session, session.begin():
            row = await session.get(User, uid)
            row.source = "local"
            await session.run_sync(lambda sync: UserService._persist_profile_in_session(sync, row))
    async with sessions() as session:
        assert (await session.get(User, uid)).source == "kunlian"


async def test_delayed_manual_operation_cannot_overwrite_newer_owner_state(owner):
    app, sessions, module = owner
    value = user_tests.identity(module)
    uid, _ = await user_tests.project(app, value, "a" * 64)
    if not hasattr(app, "reserve_manual_status"):
        pytest.fail("T022 manual owner fencing is not implemented", pytrace=False)
    operation = await app.reserve_manual_status(
        uid, identity_key=value.identity_key, source_revision="a" * 64, disabled=False, source_active=True
    )
    await user_tests.project(app, user_tests.identity(module, active=False), "b" * 64)
    with pytest.raises(KunlianBindingConflictError):
        await app.set_manual_status(
            uid, identity_key=value.identity_key, disabled=False, source_active=True, operation=operation
        )
    async with sessions() as session:
        assert (await session.get(User, uid)).delete == 1


@pytest.mark.parametrize("case", ["authorized", "denied", "invalid"])
async def test_management_endpoint_keeps_existing_permission_gate_and_uses_owner(monkeypatch, case):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from fastapi import HTTPException
    from starlette.requests import Request

    from bisheng.user.api import user as endpoint
    from bisheng.user.domain.models.user import UserUpdate

    current = SimpleNamespace(user_id=17, source="kunlian", delete=1, disable_source="manual")
    monkeypatch.setattr(endpoint.UserDao, "get_user", lambda _: current)
    monkeypatch.setattr(endpoint.UserGroupDao, "get_user_group", lambda _: [])
    monkeypatch.setattr(endpoint, "_can_manage_member_account_status", AsyncMock(return_value=False))

    @contextmanager
    def session_scope():
        yield SimpleNamespace(exec=lambda _: SimpleNamespace(first=lambda: None))

    monkeypatch.setattr(endpoint, "get_sync_db_session", session_scope)
    write = AsyncMock(return_value=current)
    monkeypatch.setattr(UserService, "aset_kunlian_account_status", write)
    monkeypatch.setattr(UserService, "ainvalidate_jwt_after_account_disabled", AsyncMock())
    monkeypatch.setattr(endpoint, "update_user_delete_hook", MagicMock())
    actor = SimpleNamespace(is_admin=lambda: case != "denied", check_groups_admin=lambda _: False)
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/user/update", "headers": []})
    req = UserUpdate(user_id=17, delete=2 if case == "invalid" else 1)
    if case == "authorized":
        await endpoint.update(request=request, user=req, login_user=actor)
        write.assert_awaited_once_with(17, disabled=True)
    else:
        with pytest.raises(HTTPException):
            await endpoint.update(request=request, user=req, login_user=actor)
        write.assert_not_awaited()
