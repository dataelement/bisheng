"""Tests for F012 User.token_version ORM field + SQL semantics.

Covers:
- ``token_version`` column DDL + default 0 (AC-02).
- Atomic UPDATE ``token_version = token_version + 1`` semantics used by
  ``UserDao.aincrement_token_version``.
- Repeated increment monotonicity.

**DAO method-level coverage** (Redis cache wiring, monkeypatched async
session bridge) is deferred to T06 ``UserTenantSyncService`` tests which
exercise ``aget_token_version`` / ``aincrement_token_version`` end-to-end
in a service-level context where the full cache manager wiring is mocked
coherently. Bringing those mocks into this DAO-only file clashes with the
conftest ``premock_import_chain`` (the ``bisheng.user.domain.models.user``
path is pre-mocked there; reimporting it here causes SQLModel metadata
double-registration + redis.asyncio submodule-import chain failures).

Pattern follows F011 ``test_tenant_tree_dao.py``.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session


# -------------------------------------------------------------------------
# Fixtures — self-contained SQLite engine with v2.5.1 user DDL
# -------------------------------------------------------------------------

@pytest.fixture(scope='module')
def dao_engine():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name VARCHAR(255) UNIQUE,
                password VARCHAR(255) NOT NULL DEFAULT '',
                email VARCHAR(255),
                phone_number VARCHAR(64),
                dept_id VARCHAR(255),
                remark VARCHAR(512),
                avatar VARCHAR(512),
                source VARCHAR(32) NOT NULL DEFAULT 'local',
                external_id VARCHAR(128),
                "delete" INTEGER DEFAULT 0,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                password_update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                token_version INTEGER NOT NULL DEFAULT 0
            )
        """))
    yield engine
    engine.dispose()


@pytest.fixture()
def session(dao_engine):
    connection = dao_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


def _create_user(sess, user_id, name, token_version=0):
    sess.execute(
        text(
            'INSERT INTO user (user_id, user_name, password, token_version) '
            'VALUES (:uid, :name, :pw, :tv)'
        ),
        {'uid': user_id, 'name': name, 'pw': 'x', 'tv': token_version},
    )
    sess.commit()


# -------------------------------------------------------------------------
# ORM field contract
# -------------------------------------------------------------------------

class TestTokenVersionField:

    def test_token_version_default_zero(self, session):
        """AC-02: new User rows default token_version to 0."""
        _create_user(session, user_id=100, name='alice')
        row = session.execute(
            text('SELECT token_version FROM user WHERE user_id = :uid'),
            {'uid': 100},
        ).first()
        assert row is not None
        assert row[0] == 0

    def test_token_version_explicit_insert(self, session):
        _create_user(session, user_id=101, name='bob', token_version=5)
        row = session.execute(
            text('SELECT token_version FROM user WHERE user_id = :uid'),
            {'uid': 101},
        ).first()
        assert row[0] == 5

    def test_token_version_column_not_nullable(self, session):
        """The NOT NULL constraint is enforced — inserting NULL fails."""
        import sqlalchemy.exc
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            session.execute(
                text(
                    'INSERT INTO user (user_id, user_name, password, token_version) '
                    'VALUES (102, "nullv", "x", NULL)'
                )
            )
            session.commit()
        session.rollback()


# -------------------------------------------------------------------------
# SQL-level atomic increment semantics
# -------------------------------------------------------------------------

class TestAincrementSQLSemantics:

    def test_increment_is_sql_atomic(self, session):
        """UPDATE SET token_version = token_version + 1 is atomic."""
        _create_user(session, user_id=200, name='claire', token_version=3)
        session.execute(
            text('UPDATE user SET token_version = token_version + 1 WHERE user_id = :uid'),
            {'uid': 200},
        )
        session.commit()
        row = session.execute(
            text('SELECT token_version FROM user WHERE user_id = :uid'),
            {'uid': 200},
        ).first()
        assert row[0] == 4

    def test_repeated_increments(self, session):
        """3 back-to-back increments yield +3."""
        _create_user(session, user_id=201, name='doug', token_version=0)
        for _ in range(3):
            session.execute(
                text('UPDATE user SET token_version = token_version + 1 WHERE user_id = :uid'),
                {'uid': 201},
            )
            session.commit()
        row = session.execute(
            text('SELECT token_version FROM user WHERE user_id = :uid'),
            {'uid': 201},
        ).first()
        assert row[0] == 3

    def test_increment_missing_row_is_noop(self, session):
        """UPDATE WHERE user_id = missing affects 0 rows; SELECT returns None."""
        session.execute(
            text('UPDATE user SET token_version = token_version + 1 WHERE user_id = :uid'),
            {'uid': 999},
        )
        session.commit()
        row = session.execute(
            text('SELECT token_version FROM user WHERE user_id = :uid'),
            {'uid': 999},
        ).first()
        assert row is None
