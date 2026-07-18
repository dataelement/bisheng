"""Tests for retained F015 OrgSyncLog schema semantics.

Pattern follows F014 ``test_department_sso_dao.py`` — spin a local SQLite
engine and exercise SQL semantics directly, keeping the async
``get_async_db_session`` wrapper out of the way. The batch-summary vs
event-row distinction (AC-11 / AC-12) is expressed purely as WHERE-clause
behaviour, so direct SQL is sufficient.

Specifically this file proves:

- F015 columns (``event_type`` / ``level`` / ``external_id`` /
  ``source_ts``) exist with their documented defaults — batch-summary
  rows keep ``event_type=''`` without any caller changes.
- ``idx_conflict_lookup`` composite index remains present for compatibility
  with already-deployed F015 schema.
- Event rows co-exist with F009 batch-summary rows inside the same table;
  WHERE-based queries can distinguish them (AC-11 persistence dimension).
"""

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


@pytest.fixture(scope="module")
def dao_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
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


def _insert_summary_row(
    sess, *, config_id=9999, status="success", dept_created=0, dept_updated=0, dept_archived=0, create_time=None
):
    """F009-style batch-summary row: counters non-zero, event_type empty."""
    params = {
        "config_id": config_id,
        "status": status,
        "dept_created": dept_created,
        "dept_updated": dept_updated,
        "dept_archived": dept_archived,
    }
    sql = (
        "INSERT INTO org_sync_log "
        "(config_id, trigger_type, status, dept_created, dept_updated, "
        " dept_archived, event_type, level"
    )
    values = ") VALUES (:config_id, :trigger, :status, :dept_created, :dept_updated,  :dept_archived, '', 'info'"
    params["trigger"] = "scheduled"
    if create_time is not None:
        sql += ", create_time"
        values += ", :ct"
        params["ct"] = create_time
    sess.execute(text(sql + values + ")"), params)
    sess.commit()


def _insert_event_row(
    sess, *, event_type, level, external_id, source_ts, config_id=9999, error_details=None, create_time=None
):
    """F015 event-scoped row."""
    params = {
        "config_id": config_id,
        "event_type": event_type,
        "level": level,
        "external_id": external_id,
        "source_ts": source_ts,
        "error_details": error_details,
    }
    sql = (
        "INSERT INTO org_sync_log "
        "(config_id, trigger_type, status, event_type, level, "
        " external_id, source_ts, error_details"
    )
    values = ") VALUES (:config_id, 'event', 'success', :event_type, :level,  :external_id, :source_ts, :error_details"
    if create_time is not None:
        sql += ", create_time"
        values += ", :ct"
        params["ct"] = create_time
    sess.execute(text(sql + values + ")"), params)
    sess.commit()


# -------------------------------------------------------------------------
# Column defaults & co-existence
# -------------------------------------------------------------------------


class TestSchemaDefaults:
    def test_summary_row_defaults_event_type_to_empty(self, session):
        _insert_summary_row(session, dept_created=3, dept_updated=2)
        row = session.execute(
            text("SELECT event_type, level, external_id, source_ts FROM org_sync_log WHERE dept_created = 3")
        ).one()
        assert row.event_type == ""
        assert row.level == "info"
        assert row.external_id is None
        assert row.source_ts is None

    def test_event_row_persists_event_fields(self, session):
        _insert_event_row(
            session,
            event_type="ts_conflict",
            level="warn",
            external_id="DEPT-A",
            source_ts=100,
            error_details='{"resolution":"remove_wins"}',
        )
        row = session.execute(
            text(
                "SELECT event_type, level, external_id, source_ts, "
                "dept_created, dept_updated, dept_archived "
                "FROM org_sync_log WHERE event_type = 'ts_conflict'"
            )
        ).one()
        assert row.event_type == "ts_conflict"
        assert row.level == "warn"
        assert row.external_id == "DEPT-A"
        assert row.source_ts == 100
        # Counter columns stay zero for event rows so F009 readers ignore them.
        assert row.dept_created == 0
        assert row.dept_updated == 0
        assert row.dept_archived == 0

    def test_summary_and_event_rows_distinguishable(self, session):
        _insert_summary_row(session, dept_created=10)
        _insert_event_row(
            session,
            event_type="stale_ts",
            level="warn",
            external_id="DEPT-B",
            source_ts=50,
        )
        summary = session.execute(text("SELECT COUNT(*) AS c FROM org_sync_log WHERE event_type = ''")).scalar()
        events = session.execute(text("SELECT COUNT(*) AS c FROM org_sync_log WHERE event_type != ''")).scalar()
        assert summary == 1
        assert events == 1


# -------------------------------------------------------------------------
# Composite index presence
# -------------------------------------------------------------------------


class TestConflictLookupIndex:
    def test_idx_conflict_lookup_is_created(self, session):
        rows = session.execute(text("PRAGMA index_list('org_sync_log')")).all()
        names = {r.name for r in rows}
        assert "idx_conflict_lookup" in names

    def test_idx_covers_expected_columns(self, session):
        cols = session.execute(text("PRAGMA index_info('idx_conflict_lookup')")).all()
        assert [c.name for c in cols] == [
            "level",
            "event_type",
            "external_id",
            "create_time",
        ]
