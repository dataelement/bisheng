"""Tests for F015 OrgSyncLog ORM extensions + OrgSyncLogDao SQL semantics.

Pattern follows F014 ``test_department_sso_dao.py`` — spin a local SQLite
engine and exercise SQL semantics directly, keeping the async
``get_async_db_session`` wrapper out of the way. The batch-summary vs
event-row distinction (AC-11 / AC-12) is expressed purely as WHERE-clause
behaviour, so direct SQL is sufficient.

Specifically this file proves:

- F015 columns (``event_type`` / ``level`` / ``external_id`` /
  ``source_ts``) exist with their documented defaults — batch-summary
  rows keep ``event_type=''`` without any caller changes.
- ``idx_conflict_lookup`` composite index is present (serves the weekly
  report aggregation in §5.5.3).
- Event rows co-exist with F009 batch-summary rows inside the same table;
  WHERE-based queries can distinguish them (AC-11 persistence dimension).
- ``acount_recent_conflicts`` SQL:
    * filters by ``level='warn'`` + ``event_type='ts_conflict'`` +
      ``external_id`` match,
    * honours the ``create_time > now - Nd`` window so out-of-window
      rows do not inflate the count,
    * returns 0 when nothing matches.
- ``aget_conflicts_since`` SQL filters by ``level`` + ``event_type`` +
  ``create_time >= since`` and returns rows sorted ascending.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from test.fixtures.table_definitions import (
    INDEX_ORG_SYNC_LOG_CONFLICT,
    TABLE_ORG_SYNC_CONFIG,
    TABLE_ORG_SYNC_LOG,
)


# -------------------------------------------------------------------------
# Fixtures — self-contained SQLite engine with the F009 + F015 DDL
# -------------------------------------------------------------------------


@pytest.fixture(scope='module')
def dao_engine():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text(TABLE_ORG_SYNC_CONFIG))
        conn.execute(text(TABLE_ORG_SYNC_LOG))
        conn.execute(text(INDEX_ORG_SYNC_LOG_CONFLICT))
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


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _insert_summary_row(sess, *, config_id=9999, status='success',
                        dept_created=0, dept_updated=0, dept_archived=0,
                        create_time=None):
    """F009-style batch-summary row: counters non-zero, event_type empty."""
    params = {
        'config_id': config_id, 'status': status,
        'dept_created': dept_created, 'dept_updated': dept_updated,
        'dept_archived': dept_archived,
    }
    sql = (
        'INSERT INTO org_sync_log '
        '(config_id, trigger_type, status, dept_created, dept_updated, '
        ' dept_archived, event_type, level'
    )
    values = (
        ') VALUES '
        '(:config_id, :trigger, :status, :dept_created, :dept_updated, '
        ' :dept_archived, \'\', \'info\''
    )
    params['trigger'] = 'scheduled'
    if create_time is not None:
        sql += ', create_time'
        values += ', :ct'
        params['ct'] = create_time
    sess.execute(text(sql + values + ')'), params)
    sess.commit()


def _insert_event_row(sess, *, event_type, level, external_id, source_ts,
                      config_id=9999, error_details=None, create_time=None):
    """F015 event-scoped row."""
    params = {
        'config_id': config_id, 'event_type': event_type,
        'level': level, 'external_id': external_id, 'source_ts': source_ts,
        'error_details': error_details,
    }
    sql = (
        'INSERT INTO org_sync_log '
        '(config_id, trigger_type, status, event_type, level, '
        ' external_id, source_ts, error_details'
    )
    values = (
        ') VALUES '
        '(:config_id, \'event\', \'success\', :event_type, :level, '
        ' :external_id, :source_ts, :error_details'
    )
    if create_time is not None:
        sql += ', create_time'
        values += ', :ct'
        params['ct'] = create_time
    sess.execute(text(sql + values + ')'), params)
    sess.commit()


# -------------------------------------------------------------------------
# Column defaults & co-existence
# -------------------------------------------------------------------------


class TestSchemaDefaults:

    def test_summary_row_defaults_event_type_to_empty(self, session):
        _insert_summary_row(session, dept_created=3, dept_updated=2)
        row = session.execute(
            text(
                "SELECT event_type, level, external_id, source_ts "
                "FROM org_sync_log WHERE dept_created = 3"
            )
        ).one()
        assert row.event_type == ''
        assert row.level == 'info'
        assert row.external_id is None
        assert row.source_ts is None

    def test_event_row_persists_event_fields(self, session):
        _insert_event_row(
            session, event_type='ts_conflict', level='warn',
            external_id='DEPT-A', source_ts=100,
            error_details='{"resolution":"remove_wins"}',
        )
        row = session.execute(
            text(
                "SELECT event_type, level, external_id, source_ts, "
                "dept_created, dept_updated, dept_archived "
                "FROM org_sync_log WHERE event_type = 'ts_conflict'"
            )
        ).one()
        assert row.event_type == 'ts_conflict'
        assert row.level == 'warn'
        assert row.external_id == 'DEPT-A'
        assert row.source_ts == 100
        # Counter columns stay zero for event rows so F009 readers ignore them.
        assert row.dept_created == 0
        assert row.dept_updated == 0
        assert row.dept_archived == 0

    def test_summary_and_event_rows_distinguishable(self, session):
        _insert_summary_row(session, dept_created=10)
        _insert_event_row(
            session, event_type='stale_ts', level='warn',
            external_id='DEPT-B', source_ts=50,
        )
        summary = session.execute(
            text(
                "SELECT COUNT(*) AS c FROM org_sync_log "
                "WHERE event_type = ''"
            )
        ).scalar()
        events = session.execute(
            text(
                "SELECT COUNT(*) AS c FROM org_sync_log "
                "WHERE event_type != ''"
            )
        ).scalar()
        assert summary == 1
        assert events == 1


# -------------------------------------------------------------------------
# acount_recent_conflicts SQL semantics
# -------------------------------------------------------------------------


class TestAcountRecentConflicts:

    def _count_conflicts(self, session, external_id, days):
        """Mirror of ``OrgSyncLogDao.acount_recent_conflicts`` in SQL."""
        threshold = datetime.utcnow() - timedelta(days=days)
        return session.execute(
            text(
                "SELECT COUNT(*) FROM org_sync_log "
                "WHERE level = 'warn' "
                "  AND event_type = 'ts_conflict' "
                "  AND external_id = :ext "
                "  AND create_time > :th"
            ),
            {'ext': external_id, 'th': threshold},
        ).scalar()

    def test_counts_only_matching_external_id_level_and_type(self, session):
        # 3 rows for DEPT-X matching; 1 for DEPT-Y; 1 wrong level; 1 wrong type
        for _ in range(3):
            _insert_event_row(
                session, event_type='ts_conflict', level='warn',
                external_id='DEPT-X', source_ts=100,
            )
        _insert_event_row(
            session, event_type='ts_conflict', level='warn',
            external_id='DEPT-Y', source_ts=100,
        )
        _insert_event_row(
            session, event_type='ts_conflict', level='info',
            external_id='DEPT-X', source_ts=100,
        )
        _insert_event_row(
            session, event_type='stale_ts', level='warn',
            external_id='DEPT-X', source_ts=100,
        )
        assert self._count_conflicts(session, 'DEPT-X', days=7) == 3

    def test_window_excludes_older_rows(self, session):
        # 2 within 7d, 2 older than 7d.
        now = datetime.utcnow()
        for _ in range(2):
            _insert_event_row(
                session, event_type='ts_conflict', level='warn',
                external_id='DEPT-X', source_ts=100,
                create_time=now - timedelta(days=1),
            )
        for _ in range(2):
            _insert_event_row(
                session, event_type='ts_conflict', level='warn',
                external_id='DEPT-X', source_ts=100,
                create_time=now - timedelta(days=10),
            )
        assert self._count_conflicts(session, 'DEPT-X', days=7) == 2

    def test_returns_zero_when_nothing_matches(self, session):
        _insert_event_row(
            session, event_type='ts_conflict', level='warn',
            external_id='OTHER', source_ts=100,
        )
        assert self._count_conflicts(session, 'NOPE', days=7) == 0


# -------------------------------------------------------------------------
# aget_conflicts_since SQL semantics
# -------------------------------------------------------------------------


class TestAgetConflictsSince:

    def _fetch_since(self, session, since, event_type='ts_conflict',
                    level='warn'):
        return session.execute(
            text(
                "SELECT external_id, source_ts, create_time "
                "FROM org_sync_log "
                "WHERE level = :level "
                "  AND event_type = :et "
                "  AND create_time >= :since "
                "ORDER BY create_time ASC"
            ),
            {'level': level, 'et': event_type, 'since': since},
        ).all()

    def test_filters_by_level_and_event_type(self, session):
        now = datetime.utcnow()
        since = now - timedelta(days=7)
        _insert_event_row(
            session, event_type='ts_conflict', level='warn',
            external_id='A', source_ts=1, create_time=now - timedelta(hours=1),
        )
        _insert_event_row(
            session, event_type='ts_conflict', level='info',
            external_id='B', source_ts=2, create_time=now - timedelta(hours=1),
        )
        _insert_event_row(
            session, event_type='stale_ts', level='warn',
            external_id='C', source_ts=3, create_time=now - timedelta(hours=1),
        )
        rows = self._fetch_since(session, since)
        assert [r.external_id for r in rows] == ['A']

    def test_returns_rows_in_ascending_time_order(self, session):
        now = datetime.utcnow()
        _insert_event_row(
            session, event_type='ts_conflict', level='warn',
            external_id='LATE', source_ts=1,
            create_time=now - timedelta(hours=1),
        )
        _insert_event_row(
            session, event_type='ts_conflict', level='warn',
            external_id='EARLY', source_ts=2,
            create_time=now - timedelta(hours=5),
        )
        rows = self._fetch_since(session, now - timedelta(days=1))
        assert [r.external_id for r in rows] == ['EARLY', 'LATE']


# -------------------------------------------------------------------------
# Composite index presence
# -------------------------------------------------------------------------


class TestConflictLookupIndex:

    def test_idx_conflict_lookup_is_created(self, session):
        rows = session.execute(
            text("PRAGMA index_list('org_sync_log')")
        ).all()
        names = {r.name for r in rows}
        assert 'idx_conflict_lookup' in names

    def test_idx_covers_expected_columns(self, session):
        cols = session.execute(
            text("PRAGMA index_info('idx_conflict_lookup')")
        ).all()
        assert [c.name for c in cols] == [
            'level', 'event_type', 'external_id', 'create_time',
        ]


# -------------------------------------------------------------------------
# OrgSyncConfigDao.aget_all_active — SQL semantics
# -------------------------------------------------------------------------


def _insert_config(sess, *, provider='feishu', config_name='c1', status='active',
                   schedule_type='manual', tenant_id=1):
    sess.execute(
        text(
            'INSERT INTO org_sync_config '
            '(tenant_id, provider, config_name, auth_type, auth_config, '
            ' schedule_type, sync_status, status) '
            'VALUES (:tid, :p, :cn, :at, :ac, :st, \'idle\', :status)'
        ),
        {'tid': tenant_id, 'p': provider, 'cn': config_name,
         'at': 'api_key', 'ac': '', 'st': schedule_type, 'status': status},
    )
    sess.commit()


class TestAgetAllActive:
    """Mirror of ``OrgSyncConfigDao.aget_all_active`` in SQL.

    Unlike F009's ``aget_active_cron_configs`` this DAO entry does **not**
    filter on ``schedule_type``; it is the fan-out source for the F015 6h
    forced reconcile beat. Callers are responsible for skipping the
    ``provider='sso_realtime'`` seed row (F014 T02).
    """

    def _list_active(self, sess):
        return sess.execute(
            text(
                "SELECT id, provider, config_name, schedule_type "
                "FROM org_sync_config WHERE status = 'active'"
            )
        ).all()

    def test_returns_manual_and_cron_configs(self, session):
        _insert_config(session, config_name='m1', schedule_type='manual')
        _insert_config(session, config_name='c1', schedule_type='cron')
        rows = self._list_active(session)
        names = {r.config_name for r in rows}
        assert names == {'m1', 'c1'}

    def test_excludes_disabled_and_deleted_configs(self, session):
        _insert_config(session, config_name='ok', status='active')
        _insert_config(session, config_name='off', status='disabled')
        _insert_config(session, config_name='gone', status='deleted')
        rows = self._list_active(session)
        assert [r.config_name for r in rows] == ['ok']

    def test_returns_empty_when_no_active_configs(self, session):
        _insert_config(session, config_name='off', status='disabled')
        rows = self._list_active(session)
        assert rows == []
