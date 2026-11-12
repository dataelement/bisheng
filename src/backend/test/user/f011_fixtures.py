"""Isolated F011 store using real user mappings and legacy CI text comparison."""

from contextlib import contextmanager

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from bisheng.database.models.user_group import UserGroup
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.account_identity import UserAccountReservation, UserIdentityWriteGuard
from bisheng.user.domain.models.user import User


@pytest.fixture
def identity_store(monkeypatch):
    from bisheng.user.domain.repositories.account_identity_repository import AccountIdentityRepository

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    metadata = MetaData()
    user_table = User.__table__.to_metadata(metadata)
    user_table.c.external_id.type = String(255, collation="NOCASE")
    user_table.c.user_name.type = String(128, collation="NOCASE")
    user_table.c.legacy_sso_name.type = String(128, collation="NOCASE")
    for model in (UserAccountReservation, UserIdentityWriteGuard):
        model.__table__.to_metadata(metadata)
    # SQLite cannot autoincrement the production composite binding PK. Keep
    # the same mapped columns and generate the ID on its sole integer PK.
    for model in (UserRole, UserGroup):
        columns = []
        for column in model.__table__.columns:
            columns.append(
                Column(
                    column.name,
                    Integer if column.name == "id" else column.type.copy(),
                    primary_key=column.name == "id",
                    nullable=False if column.name == "id" else column.nullable,
                    server_default=column.server_default,
                )
            )
        Table(model.__tablename__, metadata, *columns)
    metadata.create_all(engine)

    @contextmanager
    def scope():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(AccountIdentityRepository, "session_scope", staticmethod(scope))
    yield engine, AccountIdentityRepository
    engine.dispose()


def old_user(engine, account="Legacy01", *, source="local", disabled=0, name="旧昵称"):
    with Session(engine) as session:
        user = User(user_name=name, external_id=account, source=source, delete=disabled, password="test-only")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


@pytest.fixture
def nickname_store(identity_store, monkeypatch):
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.database.models.tenant import UserTenant
    from bisheng.user.domain.repositories.nickname_repository import NicknameRepository

    engine, identities = identity_store
    AuditLog.__table__.create(engine)
    UserTenant.__table__.create(engine)
    monkeypatch.setattr(NicknameRepository, "session_scope", staticmethod(identities.session_scope))

    def stamp(rows):
        # The F003 resolver has its own DB/authorization suite. Inject a known
        # resolved snapshot while still asserting nickname writes invoke it.
        for row in rows:
            row.operator_dept_id, row.operator_dept_path = 0, None

    monkeypatch.setattr(NicknameRepository, "stamp", staticmethod(stamp))
    yield engine, NicknameRepository
