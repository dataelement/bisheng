"""覆盖 AC: AC-04, AC-08, AC-25, AC-26, AC-29, AC-30, AC-33."""

from contextlib import contextmanager

import pytest
from sqlmodel import Session, select

from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from test.dsh.test_policy_repository import sql_store  # noqa: F401


@pytest.fixture
def user_store(sql_store):  # noqa: F811
    from bisheng.database.models.department import Department, UserDepartment
    from bisheng.database.models.tenant import UserTenant
    from bisheng.user.domain.models.user import User

    for model in (UserDepartment, UserTenant, User, Department):
        model.__table__.drop(sql_store, checkfirst=True)
    for model in (User, UserTenant, Department, UserDepartment):
        model.__table__.create(sql_store)
    with Session(sql_store) as session, session.begin():
        session.add(User(user_id=20, user_name="Before", password="test-only"))
        session.add(UserTenant(user_id=20, tenant_id=2, is_active=1))
    return sql_store


async def test_user_update_version_and_outbox_commit_together(user_store, monkeypatch):
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.services.user import UserService

    @contextmanager
    def scope():
        with Session(user_store) as session, session.begin():
            yield session

    monkeypatch.setattr(UserService, "_dsh_enabled", staticmethod(lambda: True))
    with Session(user_store) as session:
        user = session.get(User, 20)
    user.user_name = "After"
    saved = UserService.persist_profile_update(user, session_scope=scope)
    assert saved.user_name == "After"
    with Session(user_store) as session:
        row = session.get(User, 20)
        operations = session.exec(select(DshAdminOperation)).all()
        assert row.dsh_profile_version == 1
        assert len(operations) == 1
        assert operations[0].payload["username"] == "After"
        assert operations[0].payload["profile_version"] == 1
        assert operations[0].action == "SYNC_PROFILE"


async def test_rollback_leaves_neither_profile_version_nor_intent(user_store, monkeypatch):
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.services.user import UserService

    @contextmanager
    def scope():
        with Session(user_store) as session, session.begin():
            yield session
            raise RuntimeError("transaction rejected")

    monkeypatch.setattr(UserService, "_dsh_enabled", staticmethod(lambda: True))
    with Session(user_store) as session:
        user = session.get(User, 20)
    user.user_name = "After"
    with pytest.raises(RuntimeError):
        UserService.persist_profile_update(user, session_scope=scope)
    with Session(user_store) as session:
        assert session.get(User, 20).user_name == "Before"
        assert session.get(User, 20).dsh_profile_version == 0
        assert session.exec(select(DshAdminOperation)).all() == []


async def test_same_snapshot_is_idempotent_and_disabled_dsh_has_no_outbox(user_store, monkeypatch):
    from bisheng.dsh.domain.services.profile import DshProfileService
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository
    from bisheng.user.domain.services.user import UserService

    with Session(user_store) as session, session.begin():
        snapshot = UserDshProfileRepository.batch_snapshot(session, [20])[20]
        first = DshProfileService.record_change(session, snapshot)
        repeated = DshProfileService.record_change(session, snapshot)
        assert first.operation_id == repeated.operation_id
        assert len(session.exec(select(DshAdminOperation)).all()) == 1

    @contextmanager
    def scope():
        with Session(user_store) as session, session.begin():
            yield session

    monkeypatch.setattr(UserService, "_dsh_enabled", staticmethod(lambda: False))
    with Session(user_store) as session:
        user = session.get(User, 20)
    user.delete = 1
    UserService.persist_profile_update(user, session_scope=scope)
    with Session(user_store) as session:
        assert session.get(User, 20).delete == 1
        assert session.get(User, 20).dsh_profile_version == 0
        assert len(session.exec(select(DshAdminOperation)).all()) == 1


async def test_profile_sweep_uses_bounded_cursor_without_incrementing_versions(user_store, monkeypatch):
    from contextlib import asynccontextmanager

    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.services import user as module

    class Facade:
        def __init__(self, session):
            self.session = session

        async def run_sync(self, callback):
            return callback(self.session)

        async def commit(self):
            self.session.commit()

    @asynccontextmanager
    async def scope():
        with Session(user_store) as session:
            yield Facade(session)

    monkeypatch.setattr(module, "get_async_db_session", scope)
    monkeypatch.setattr(module.UserService, "_dsh_enabled", staticmethod(lambda: True))
    result = await module.UserService.scan_dsh_profiles(after_user_id=0, limit=1)
    assert result["next_user_id"] == 20 and result["has_more"] is True
    assert result["items"][0]["profile_version"] == 0
    assert await module.UserService.scan_dsh_profiles(after_user_id=20, limit=1) == {
        "next_user_id": 20,
        "has_more": False,
        "items": [],
    }
    with Session(user_store) as session:
        assert session.get(User, 20).dsh_profile_version == 0
        assert session.exec(select(DshAdminOperation)).all() == []


@pytest.mark.parametrize("rollback", [False, True])
async def test_membership_jwt_version_and_profile_intent_are_atomic(user_store, monkeypatch, rollback):
    from contextlib import asynccontextmanager

    from bisheng.database.models.tenant import UserTenant
    from bisheng.dsh.domain.services.profile import profile_scope
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.services import user as module

    class Facade:
        def __init__(self, session):
            self.session = session

        async def run_sync(self, callback):
            return callback(self.session)

        async def commit(self):
            if rollback:
                raise RuntimeError("Rejected commit")
            self.session.commit()

    @asynccontextmanager
    async def scope():
        with Session(user_store) as session:
            yield Facade(session)

    monkeypatch.setattr(module, "get_async_db_session", scope)
    monkeypatch.setattr(module.UserService, "_dsh_enabled", staticmethod(lambda: True))
    if rollback:
        with pytest.raises(RuntimeError):
            await module.UserService.activate_tenant_with_profile(20, 3)
    else:
        await module.UserService.activate_tenant_with_profile(20, 3)
    with Session(user_store) as session:
        user = session.get(User, 20)
        assert user.token_version == (0 if rollback else 1)
        assert user.dsh_profile_version == (0 if rollback else 1)
        membership = session.exec(select(UserTenant).where(UserTenant.is_active == 1)).one()
        assert membership.tenant_id == (2 if rollback else 3)
        with profile_scope(3):
            operations = session.exec(select(DshAdminOperation)).all()
            assert len(operations) == (0 if rollback else 1)
            if operations:
                assert operations[0].payload["tenant_id"] == "3"
