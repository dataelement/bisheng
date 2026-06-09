# test/evaluation/conftest.py
import contextlib

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

_EVALUATION_DDL = """
CREATE TABLE IF NOT EXISTS evaluation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    file_name VARCHAR(255) DEFAULT '',
    file_path VARCHAR(255) DEFAULT '',
    exec_type VARCHAR(255),
    unique_id VARCHAR(255),
    version INTEGER,
    status INTEGER DEFAULT 1,
    prompt TEXT,
    result_file_path VARCHAR(255) DEFAULT '',
    result_score JSON,
    description TEXT,
    is_delete INTEGER DEFAULT 0,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)
"""


@pytest.fixture()
def sqlite_session_patch(monkeypatch):
    """In-memory sqlite with the evaluation table; patches the repository's
    get_sync_db_session to use it. Yields a seed Session for the test to insert data."""
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text(_EVALUATION_DDL))

    @contextlib.contextmanager
    def _fake_session():
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    monkeypatch.setattr(
        'bisheng.evaluation.domain.repositories.evaluation_repository.get_sync_db_session',
        _fake_session)

    # The Evaluation table is tenant-aware, so once any test in the process
    # registers the tenant-filter ORM events they intercept every session —
    # including this in-memory sqlite one. Bypass keeps the test deterministic
    # and independent of suite ordering.
    from bisheng.core.context.tenant import bypass_tenant_filter

    seed = Session(bind=engine)
    with bypass_tenant_filter():
        yield seed
    seed.close()
    engine.dispose()
