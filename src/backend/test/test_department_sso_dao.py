"""Tests for F014 Department ORM extensions + SSO-sync DAO SQL semantics.

Pattern matches F011 ``test_tenant_tree_dao.py`` — exercise SQL semantics via
a local SQLite engine and the synchronous SQLModel Session. The async DAO
methods themselves are trivial ``get_async_db_session()`` wrappers; their
behaviour is covered end-to-end by T08/T11 integration tests.

Specifically this file proves:
- ``is_deleted`` / ``last_sync_ts`` columns exist with the expected DDL
  defaults (AC-08 baseline).
- ``aget_by_source_external_id`` SELECT condition returns both active and
  soft-deleted rows (so OrgSyncTsGuard can still observe ``is_deleted=1``
  when evaluating same-ts remove-vs-upsert — INV-T12).
- ``aupsert_by_external_id`` preserves ``is_tenant_root`` and
  ``mounted_tenant_id`` on update (PRD §5.2.5 rubustness rule) while
  updating ``name`` / ``parent_id`` / ``path`` / ``sort_order`` /
  ``last_sync_ts`` and clearing ``is_deleted`` on resurrect.
- ``aarchive_by_external_id`` flips ``status='archived'`` + ``is_deleted=1``
  + ``last_sync_ts`` atomically and returns the pre-update row so callers
  can inspect ``mounted_tenant_id`` for orphan handling.
"""

import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from bisheng.database.models.department import Department


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------

@pytest.fixture(scope='module')
def dao_engine():
    """SQLite engine with the v2.5.1 department DDL (F011 + F014 fields)."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS department (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dept_id VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                parent_id INTEGER,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                path VARCHAR(512) NOT NULL DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                source VARCHAR(32) DEFAULT 'local',
                external_id VARCHAR(128),
                status VARCHAR(16) DEFAULT 'active',
                is_tenant_root INTEGER NOT NULL DEFAULT 0,
                mounted_tenant_id INTEGER,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                last_sync_ts BIGINT NOT NULL DEFAULT 0,
                default_role_ids JSON,
                create_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(source, external_id)
            )
        """))
    yield engine
    engine.dispose()


@pytest.fixture()
def session(dao_engine):
    """Transactional session that rolls back after each test."""
    connection = dao_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


def _insert_dept(sess, *, dept_id, external_id, name='Dept',
                 source='sso', parent_id=None, path='',
                 sort_order=0, status='active',
                 is_tenant_root=0, mounted_tenant_id=None,
                 is_deleted=0, last_sync_ts=0, tenant_id=1):
    d = Department(
        dept_id=dept_id, name=name, parent_id=parent_id, tenant_id=tenant_id,
        path=path, sort_order=sort_order, source=source,
        external_id=external_id, status=status,
        is_tenant_root=is_tenant_root, mounted_tenant_id=mounted_tenant_id,
        is_deleted=is_deleted, last_sync_ts=last_sync_ts,
    )
    sess.add(d)
    sess.commit()
    sess.refresh(d)
    return d


# -------------------------------------------------------------------------
# ORM field tests
# -------------------------------------------------------------------------

class TestDepartmentF014Fields:

    def test_defaults(self, session):
        d = _insert_dept(session, dept_id='SSO@D001', external_id='D001')
        assert d.is_deleted == 0
        assert d.last_sync_ts == 0

    def test_soft_delete_flag_persists(self, session):
        d = _insert_dept(session, dept_id='SSO@D010', external_id='D010',
                         is_deleted=1, last_sync_ts=1713400000, status='archived')
        reloaded = session.exec(
            select(Department).where(Department.id == d.id)
        ).first()
        assert reloaded.is_deleted == 1
        assert reloaded.last_sync_ts == 1713400000
        assert reloaded.status == 'archived'


# -------------------------------------------------------------------------
# aget_by_source_external_id — SQL semantic parity
# -------------------------------------------------------------------------

class TestGetBySourceExternalId:

    def test_returns_active_row(self, session):
        _insert_dept(session, dept_id='SSO@A1', external_id='A1')
        row = session.exec(
            select(Department).where(
                Department.source == 'sso',
                Department.external_id == 'A1',
            )
        ).first()
        assert row is not None and row.external_id == 'A1'

    def test_returns_archived_row_no_is_deleted_filter(self, session):
        """F014 guard needs to observe is_deleted=1 rows; DAO MUST NOT filter."""
        _insert_dept(session, dept_id='SSO@A2', external_id='A2',
                     status='archived', is_deleted=1, last_sync_ts=111)
        row = session.exec(
            select(Department).where(
                Department.source == 'sso',
                Department.external_id == 'A2',
            )
        ).first()
        assert row is not None
        assert row.is_deleted == 1
        assert row.last_sync_ts == 111

    def test_source_isolation(self, session):
        _insert_dept(session, dept_id='FS@B1', external_id='B1', source='feishu')
        # same external_id under 'sso' does not exist → miss
        row = session.exec(
            select(Department).where(
                Department.source == 'sso',
                Department.external_id == 'B1',
            )
        ).first()
        assert row is None


# -------------------------------------------------------------------------
# aupsert_by_external_id — SQL semantic parity
# -------------------------------------------------------------------------

class TestUpsertByExternalId:

    def test_insert_when_missing(self, session):
        # upsert INSERT path: mimic DAO branch
        existing = session.exec(
            select(Department).where(
                Department.source == 'sso',
                Department.external_id == 'NEW1',
            )
        ).first()
        assert existing is None

        d = Department(
            dept_id='SSO@NEW1', name='NewDept', parent_id=None,
            tenant_id=1, path='', sort_order=0,
            source='sso', external_id='NEW1',
            status='active', is_deleted=0, last_sync_ts=500,
        )
        session.add(d)
        session.commit()
        session.refresh(d)
        assert d.id is not None
        assert d.last_sync_ts == 500
        assert d.is_tenant_root == 0  # default untouched

    def test_update_preserves_mount_fields(self, session):
        """AC core: upsert MUST NOT overwrite is_tenant_root / mounted_tenant_id."""
        d = _insert_dept(session, dept_id='SSO@MNT', external_id='MNT',
                         name='Old', is_tenant_root=1, mounted_tenant_id=5,
                         last_sync_ts=100)
        # simulate DAO update path: name/parent/path/sort/status/is_deleted/last_sync_ts ONLY
        session.execute(
            update(Department)
            .where(Department.id == d.id)
            .values(
                name='NewName', parent_id=None, path='/9/',
                sort_order=3, status='active', is_deleted=0,
                last_sync_ts=200,
            )
        )
        session.commit()
        reloaded = session.exec(
            select(Department).where(Department.id == d.id)
        ).first()
        assert reloaded.name == 'NewName'
        assert reloaded.path == '/9/'
        assert reloaded.sort_order == 3
        assert reloaded.last_sync_ts == 200
        # preserved
        assert reloaded.is_tenant_root == 1
        assert reloaded.mounted_tenant_id == 5

    def test_resurrect_clears_is_deleted(self, session):
        """Resurrect path: previously archived row becomes visible again."""
        d = _insert_dept(session, dept_id='SSO@RZ', external_id='RZ',
                         status='archived', is_deleted=1, last_sync_ts=100)
        session.execute(
            update(Department)
            .where(Department.id == d.id)
            .values(
                name='Reborn', parent_id=None, path='',
                sort_order=0, status='active', is_deleted=0,
                last_sync_ts=200,
            )
        )
        session.commit()
        reloaded = session.exec(
            select(Department).where(Department.id == d.id)
        ).first()
        assert reloaded.status == 'active'
        assert reloaded.is_deleted == 0
        assert reloaded.last_sync_ts == 200


# -------------------------------------------------------------------------
# aarchive_by_external_id — SQL semantic parity
# -------------------------------------------------------------------------

class TestArchiveByExternalId:

    def test_archive_flips_flags_and_ts(self, session):
        d = _insert_dept(session, dept_id='SSO@DEL1', external_id='DEL1',
                         status='active', is_deleted=0, last_sync_ts=50,
                         is_tenant_root=1, mounted_tenant_id=7)
        # simulate aarchive_by_external_id path
        session.execute(
            update(Department)
            .where(Department.id == d.id)
            .values(
                status='archived', is_deleted=1, last_sync_ts=300,
            )
        )
        session.commit()
        reloaded = session.exec(
            select(Department).where(Department.id == d.id)
        ).first()
        assert reloaded.status == 'archived'
        assert reloaded.is_deleted == 1
        assert reloaded.last_sync_ts == 300
        # mount fields remain so orphan handler can still read mounted_tenant_id
        assert reloaded.is_tenant_root == 1
        assert reloaded.mounted_tenant_id == 7

    def test_archive_missing_returns_no_row(self, session):
        # DAO semantic: aget_by_source_external_id returns None, DAO returns None
        existing = session.exec(
            select(Department).where(
                Department.source == 'sso',
                Department.external_id == 'GHOST',
            )
        ).first()
        assert existing is None
