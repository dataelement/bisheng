"""覆盖 AC: AC-04, AC-08, AC-17, AC-25, AC-26, AC-29, AC-30, AC-33."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlmodel import Session, select

from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from test.dsh.test_policy_repository import sql_store  # noqa: F401
from test.dsh.test_profile_outbox import user_store  # noqa: F401


async def test_account_disable_does_not_publish_unchanged_name(user_store, monkeypatch):  # noqa: F811
    from bisheng.user.api import user as endpoint
    from bisheng.user.domain.models.user import User, UserUpdate
    from bisheng.user.domain.services.user import UserService

    with Session(user_store) as session:
        original_user = session.get(User, 20)
    monkeypatch.setattr(endpoint.UserDao, "get_user", lambda user_id: original_user)

    @contextmanager
    def role_check():
        yield SimpleNamespace(exec=lambda statement: SimpleNamespace(first=lambda: None))

    monkeypatch.setattr(endpoint, "get_sync_db_session", role_check)
    monkeypatch.setattr(endpoint, "clear_error_password_key", lambda user_id: None)
    monkeypatch.setattr(endpoint, "update_user_delete_hook", lambda *args: None)
    monkeypatch.setattr(UserService, "_dsh_enabled", staticmethod(lambda: True))
    invalidation = AsyncMock()
    monkeypatch.setattr(UserService, "ainvalidate_jwt_after_account_disabled", invalidation)
    original_persist = UserService.persist_profile_update

    @contextmanager
    def transaction():
        with Session(user_store) as session, session.begin():
            yield session

    monkeypatch.setattr(
        UserService, "persist_profile_update", lambda changed: original_persist(changed, session_scope=transaction)
    )
    await endpoint.update(
        request=SimpleNamespace(),
        user=UserUpdate(user_id=20, delete=1),
        login_user=SimpleNamespace(is_admin=lambda: True),
    )
    with Session(user_store) as session:
        assert session.get(User, 20).delete == 1
        assert session.get(User, 20).dsh_profile_version == 0
        assert session.exec(select(DshAdminOperation)).first() is None
    invalidation.assert_awaited_once_with(20)


async def test_actual_sso_rename_persists_profile_intent(user_store, monkeypatch):  # noqa: F811
    from bisheng.sso_sync.domain.services.login_sync_service import LoginSyncService
    from bisheng.user.domain.models.user import User, UserDao
    from bisheng.user.domain.services.user import UserService

    with Session(user_store) as session:
        existing = session.get(User, 20)
    monkeypatch.setattr(UserDao, "aget_by_source_external_id", AsyncMock(return_value=existing))
    monkeypatch.setattr(
        UserDao, "aupdate_user", AsyncMock(side_effect=AssertionError("Legacy independent commit bypassed outbox"))
    )
    monkeypatch.setattr(UserService, "_dsh_enabled", staticmethod(lambda: True))

    @contextmanager
    def transaction():
        with Session(user_store) as session, session.begin():
            yield session

    async def persist(user):
        return UserService.persist_profile_update(user, session_scope=transaction)

    monkeypatch.setattr(UserService, "apersist_profile_update", persist)
    payload = SimpleNamespace(
        external_user_id="external",
        account_disabled=None,
        user_attrs=SimpleNamespace(name="SSO Name", email=None, phone=None),
    )
    result, _override = await LoginSyncService._upsert_user(payload, "127.0.0.1", "generic_api")
    assert result.user_name == "SSO Name"
    with Session(user_store) as session:
        assert session.get(User, 20).dsh_profile_version == 1
        assert session.exec(select(DshAdminOperation)).one().payload["username"] == "SSO Name"


async def test_primary_department_does_not_enqueue_dsh_profile(user_store, monkeypatch):  # noqa: F811
    from contextlib import asynccontextmanager

    from bisheng.database.models.department import Department, UserDepartment
    from bisheng.department.domain.services import department_service
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.services import user_department_service as module
    from bisheng.user.domain.services.user import UserService

    with Session(user_store) as session, session.begin():
        session.add(Department(id=5, dept_id="dept-5", name="Department", parent_id=None))
        session.flush()
        session.add(UserDepartment(id=1, user_id=20, department_id=5, is_primary=0))

    class AsyncSessionFacade:
        def __init__(self, session):
            self.session = session

        async def exec(self, statement):
            return self.session.exec(statement)

        async def run_sync(self, callback):
            return callback(self.session)

        async def commit(self):
            self.session.commit()

    @asynccontextmanager
    async def scope():
        with Session(user_store) as session:
            yield AsyncSessionFacade(session)

    monkeypatch.setattr(module, "get_async_db_session", scope)
    monkeypatch.setattr(UserService, "_dsh_enabled", staticmethod(lambda: True))
    monkeypatch.setattr(module.UserDepartmentDao, "aget_user_primary_department", AsyncMock(return_value=None))
    monkeypatch.setattr(department_service, "_uses_f048_department_projection", lambda: False)
    for name in ("_bind_department_projection", "_execute_department_projection"):
        monkeypatch.setattr(department_service, name, AsyncMock())
    monkeypatch.setattr(module.DepartmentChangeHandler, "on_members_added", lambda *args: [])
    monkeypatch.setattr(module.DepartmentChangeHandler, "execute_async", AsyncMock())

    async def tenant_sync(*args, **kwargs):
        with Session(user_store) as session:
            assert session.get(User, 20).dsh_profile_version == 0
            assert session.exec(select(DshAdminOperation)).all() == []
        return SimpleNamespace(id=2)

    monkeypatch.setattr(module.UserTenantSyncService, "sync_user", tenant_sync)
    await module.UserDepartmentService.change_primary_department(20, 5)


async def test_tenant_relocation_calls_atomic_profile_path(user_store, monkeypatch):  # noqa: F811
    from bisheng.tenant.domain.services import user_tenant_sync_service as module
    from bisheng.user.domain.services.user import UserService

    monkeypatch.setattr(UserService, "_dsh_enabled", staticmethod(lambda: True))
    atomic = AsyncMock()
    monkeypatch.setattr(UserService, "activate_tenant_with_profile", atomic)
    monkeypatch.setattr(
        module.TenantResolver, "resolve_user_leaf_tenant", AsyncMock(return_value=SimpleNamespace(id=3))
    )
    monkeypatch.setattr(
        module.UserTenantDao, "aget_active_user_tenant", AsyncMock(return_value=SimpleNamespace(tenant_id=2))
    )
    monkeypatch.setattr(
        module.UserTenantDao, "aactivate_user_tenant", AsyncMock(side_effect=AssertionError("Independent commit"))
    )
    for name in ("_rewrite_tenant_membership_permissions", "_invalidate_redis_caches", "_write_relocation_audit"):
        monkeypatch.setattr(module.UserTenantSyncService, name, AsyncMock())
    monkeypatch.setattr(module.UserTenantSyncService, "_count_owned_resources", AsyncMock(return_value=0))
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService

    monkeypatch.setattr(TenantScopeService, "clear_on_token_version_bump", AsyncMock())
    await module.UserTenantSyncService.sync_user(20)
    atomic.assert_awaited_once_with(20, 3)
