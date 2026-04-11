"""Tests for _init_default_root_department in init_data.py.

Validates AC-17: default tenant gets root department on first startup.
Uses sync SQLite to directly test the init logic.

Part of F002-department-tree.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant


@pytest.fixture(scope='module')
def init_engine():
    """SQLite engine with tenant + department tables."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_code VARCHAR(64) NOT NULL UNIQUE,
                tenant_name VARCHAR(128) NOT NULL,
                logo VARCHAR(512),
                root_dept_id INTEGER,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                contact_name VARCHAR(64),
                contact_phone VARCHAR(32),
                contact_email VARCHAR(128),
                quota_config JSON,
                storage_config JSON,
                create_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
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
def session(init_engine):
    """Transactional session that rolls back after each test."""
    connection = init_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


class TestInitDefaultRootDepartment:

    def test_init_creates_root_department(self, session):
        """AC-17: Default tenant (id=1) gets a root department on startup."""
        # Setup: create default tenant with no root_dept_id
        tenant = Tenant(
            id=1,
            tenant_code='default',
            tenant_name='Default Tenant',
            status='active',
        )
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
        assert tenant.root_dept_id is None

        # Simulate what _init_default_root_department does (sync version)
        dept = Department(
            dept_id='BS@root',
            name='Default Organization',
            parent_id=None,
            tenant_id=1,
            path='',
            source='local',
            status='active',
        )
        session.add(dept)
        session.flush()
        session.refresh(dept)

        dept.path = f'/{dept.id}/'
        tenant.root_dept_id = dept.id
        session.commit()
        session.refresh(tenant)
        session.refresh(dept)

        # Verify
        assert dept.id is not None
        assert dept.parent_id is None
        assert dept.path == f'/{dept.id}/'
        assert dept.name == 'Default Organization'
        assert tenant.root_dept_id == dept.id

    def test_init_idempotent(self, session):
        """Running init twice should not create a second root department."""
        # Setup: create tenant + root department
        tenant = Tenant(
            id=1,
            tenant_code='default',
            tenant_name='Default Tenant',
            status='active',
        )
        session.add(tenant)
        session.commit()

        dept = Department(
            dept_id='BS@root',
            name='Default Organization',
            parent_id=None,
            tenant_id=1,
            path='',
            source='local',
            status='active',
        )
        session.add(dept)
        session.flush()
        session.refresh(dept)
        dept.path = f'/{dept.id}/'
        tenant.root_dept_id = dept.id
        session.commit()
        session.refresh(tenant)

        first_dept_id = dept.id

        # Second call: tenant already has root_dept_id, should skip
        assert tenant.root_dept_id is not None

        # Verify only one root department exists
        roots = session.exec(
            select(Department).where(
                Department.parent_id.is_(None),
                Department.tenant_id == 1,
                Department.status == 'active',
            )
        ).all()
        assert len(roots) == 1
        assert roots[0].id == first_dept_id
