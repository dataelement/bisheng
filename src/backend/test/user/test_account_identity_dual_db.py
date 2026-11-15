"""AC-08, AC-09, AC-10, AC-14, AC-32: real two-dialect concurrency in an owned empty test DB."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from sqlalchemy import Column, Index, MetaData, Table, UniqueConstraint, create_engine, inspect
from sqlmodel import Session, select

from bisheng.common.errcode.user import AccountAlreadyExistsError
from bisheng.database.models.user_group import UserGroup
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.account_identity import UserAccountReservation, UserIdentityWriteGuard
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.account_identity_repository import AccountIdentityRepository
from bisheng.user.domain.services.account_identity_service import AccountIdentityService


@pytest.fixture(params=["MYSQL", "DM8"])
def dedicated_identity_database(request, monkeypatch):
    url = os.environ.get(f"F011_{request.param}_TEST_URL")
    if not url:
        pytest.skip(f"F011_{request.param}_TEST_URL is not configured")
    if os.environ.get("F011_OWN_EMPTY_TEST_DATABASE") != "yes":
        pytest.fail("Real-database tests require an explicitly owned empty test database")
    engine = create_engine(url, pool_pre_ping=True)
    assert engine.dialect.name == ("mysql" if request.param == "MYSQL" else "dm")
    assert not inspect(engine).get_table_names(), "The dedicated F011 test database must be empty"
    metadata = MetaData()
    # Preserve production types, keys, indexes and defaults. Cross-feature FKs
    # are omitted because this suite owns only identity storage, not real roles.
    for model in (User, UserAccountReservation, UserIdentityWriteGuard, UserRole, UserGroup):
        original = model.__table__
        table = Table(
            original.name,
            metadata,
            *[
                Column(
                    column.name,
                    column.type.copy(),
                    primary_key=column.primary_key,
                    nullable=column.nullable,
                    autoincrement=column.autoincrement,
                    server_default=column.server_default,
                )
                for column in original.columns
            ],
        )
        for constraint in original.constraints:
            if isinstance(constraint, UniqueConstraint):
                table.append_constraint(
                    UniqueConstraint(*[column.name for column in constraint.columns], name=constraint.name)
                )
        for index in original.indexes:
            Index(index.name, *[table.c[column.name] for column in index.columns], unique=index.unique)
    metadata.create_all(engine)

    @contextmanager
    def scope():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(AccountIdentityRepository, "session_scope", staticmethod(scope))
    try:
        yield engine
    finally:
        # Do not drop tables if another process introduced unrelated state.
        assert set(inspect(engine).get_table_names()) == set(metadata.tables)
        metadata.drop_all(engine)
        engine.dispose()


def test_exact_account_concurrency_and_legacy_occupancy(dedicated_identity_database):
    """AC-08, AC-09, AC-10, AC-14, AC-32: exact creation serializes on both databases."""
    engine = dedicated_identity_database

    def create(account):
        try:
            return AccountIdentityService.create_local(
                User(
                    user_name="e2e-f011-Nickname",
                    external_id=account,
                    password="test-only",
                ),
                role_ids=[],
            ).user_id
        except AccountAlreadyExistsError:
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        same = list(executor.map(create, ["e2e-f011-Same"] * 4))
    assert sum(user_id is not None for user_id in same) == 1
    with ThreadPoolExecutor(max_workers=2) as executor:
        different = list(executor.map(create, ["e2e-f011-Case", "e2e-f011-case"]))
    assert len(set(different)) == 2 and all(different)
    for account, user_id in zip(["e2e-f011-Case", "e2e-f011-case"], different, strict=True):
        assert AccountIdentityService.resolve_login(account).user_id == user_id
    with Session(engine) as session:
        legacy = User(user_name=" old historical name ", external_id="e2e-f011-Legacy", source="generic_api")
        session.add(legacy)
        session.commit()
        legacy_id = legacy.user_id
        expected_comparison = session.exec(select(User.user_id).where(User.external_id == "e2e-f011-LEGACY")).first()
    result = create("e2e-f011-LEGACY")
    assert (result is None) == (expected_comparison == legacy_id)
    with Session(engine) as session:
        original = session.get(User, legacy_id)
        assert original.user_name == " old historical name "
        assert original.external_id == "e2e-f011-Legacy" and original.account_rule_version == 0
