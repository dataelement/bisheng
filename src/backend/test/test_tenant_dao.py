"""Tests for Tenant and UserTenant ORM models.

Uses a self-contained SQLite engine with only Tenant/UserTenant tables.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from bisheng.database.models.tenant import Tenant, UserTenant


@pytest.fixture(scope='module')
def dao_engine():
    """SQLite engine with Tenant/UserTenant tables (SQLite-compatible DDL)."""
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
                parent_tenant_id INTEGER,
                share_default_to_children INTEGER NOT NULL DEFAULT 1,
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
            CREATE TABLE IF NOT EXISTS user_tenant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                is_active INTEGER,
                last_access_time DATETIME,
                join_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(user_id, tenant_id)
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


class TestTenantModel:

    def test_create_tenant(self, session):
        tenant = Tenant(tenant_code='test_corp', tenant_name='Test Corporation', status='active')
        session.add(tenant)
        session.commit()
        session.refresh(tenant)

        assert tenant.id is not None
        assert tenant.tenant_code == 'test_corp'
        assert tenant.tenant_name == 'Test Corporation'

    def test_get_by_code(self, session):
        tenant = Tenant(tenant_code='cofco', tenant_name='COFCO Group')
        session.add(tenant)
        session.commit()

        result = session.exec(select(Tenant).where(Tenant.tenant_code == 'cofco')).first()
        assert result is not None
        assert result.tenant_name == 'COFCO Group'

    def test_tenant_code_unique(self, session):
        session.add(Tenant(tenant_code='dup_code', tenant_name='First'))
        session.commit()

        session.add(Tenant(tenant_code='dup_code', tenant_name='Second'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_tenant_optional_fields(self, session):
        tenant = Tenant(
            tenant_code='minimal', tenant_name='Minimal Tenant',
            logo='https://example.com/logo.png',
            contact_name='Zhang San', contact_phone='13800138000',
            quota_config={'max_knowledge': 100},
            storage_config={'minio_bucket': 'custom'},
        )
        session.add(tenant)
        session.commit()
        session.refresh(tenant)

        assert tenant.logo == 'https://example.com/logo.png'
        assert tenant.quota_config == {'max_knowledge': 100}


class TestUserTenantModel:

    def test_create_user_tenant(self, session):
        tenant = Tenant(tenant_code='ut_test', tenant_name='UT Test')
        session.add(tenant)
        session.commit()

        ut = UserTenant(user_id=1, tenant_id=tenant.id, is_default=1)
        session.add(ut)
        session.commit()
        session.refresh(ut)

        assert ut.id is not None
        assert ut.user_id == 1
        assert ut.is_default == 1

    def test_unique_constraint(self, session):
        tenant = Tenant(tenant_code='uk_test', tenant_name='UK Test')
        session.add(tenant)
        session.commit()

        session.add(UserTenant(user_id=10, tenant_id=tenant.id))
        session.commit()

        session.add(UserTenant(user_id=10, tenant_id=tenant.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_get_user_tenants(self, session):
        t1 = Tenant(tenant_code='multi_a', tenant_name='Tenant A')
        t2 = Tenant(tenant_code='multi_b', tenant_name='Tenant B')
        session.add_all([t1, t2])
        session.commit()

        session.add_all([
            UserTenant(user_id=99, tenant_id=t1.id, is_default=1),
            UserTenant(user_id=99, tenant_id=t2.id, is_default=0),
        ])
        session.commit()

        results = session.exec(
            select(UserTenant).where(UserTenant.user_id == 99, UserTenant.status == 'active')
        ).all()

        assert len(results) == 2
        assert {r.tenant_id for r in results} == {t1.id, t2.id}
