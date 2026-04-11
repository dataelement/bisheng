"""Smoke tests for F000 test infrastructure.

Validates that all shared fixtures and utilities work correctly.
Does NOT test business logic — only verifies the infrastructure itself.

Created by F000-test-infrastructure.
"""

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# DB engine & session fixtures
# ---------------------------------------------------------------------------

class TestDbEngine:
    """Verify db_engine fixture creates tables correctly."""

    def test_creates_tenant_table(self, db_engine):
        with db_engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(tenant)")).fetchall()
            col_names = [row[1] for row in result]
            assert 'id' in col_names
            assert 'tenant_code' in col_names
            assert 'tenant_name' in col_names

    def test_creates_all_expected_tables(self, db_engine):
        with db_engine.connect() as conn:
            tables = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )).fetchall()
            table_names = {row[0] for row in tables}
            expected = {'tenant', 'user_tenant', 'user', 'role', 'role_access',
                        'flow', 'knowledge', 'department', 'user_department'}
            assert expected.issubset(table_names), f'Missing: {expected - table_names}'


class TestDbSession:
    """Verify db_session fixture provides CRUD and ROLLBACK isolation."""

    def test_crud(self, db_session):
        db_session.execute(text(
            "INSERT INTO tenant (tenant_code, tenant_name) VALUES ('smoke', 'Smoke Tenant')"
        ))
        db_session.flush()
        row = db_session.execute(
            text("SELECT tenant_code FROM tenant WHERE tenant_code = 'smoke'")
        ).fetchone()
        assert row is not None
        assert row[0] == 'smoke'

    def test_rollback_isolation(self, db_session):
        """Data from test_crud should NOT be visible here (ROLLBACK)."""
        row = db_session.execute(
            text("SELECT * FROM tenant WHERE tenant_code = 'smoke'")
        ).fetchone()
        assert row is None


# ---------------------------------------------------------------------------
# Async DB fixtures
# ---------------------------------------------------------------------------

class TestAsyncDbSession:
    """Verify async_db_session fixture works for async operations."""

    @pytest.mark.asyncio
    async def test_async_crud(self, async_db_session):
        await async_db_session.execute(text(
            "INSERT INTO tenant (tenant_code, tenant_name) VALUES ('async_smoke', 'Async Tenant')"
        ))
        await async_db_session.flush()
        result = await async_db_session.execute(
            text("SELECT tenant_code FROM tenant WHERE tenant_code = 'async_smoke'")
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == 'async_smoke'


# ---------------------------------------------------------------------------
# External service mocks
# ---------------------------------------------------------------------------

class TestMockRedis:
    """Verify mock_redis fixture provides basic Redis operations."""

    def test_basic_ops(self, mock_redis):
        mock_redis.set('key', 'val')
        assert mock_redis.get('key') == b'val'
        mock_redis.delete('key')
        assert mock_redis.get('key') is None


class TestMockMinio:
    """Verify mock_minio fixture is callable."""

    def test_put_object(self, mock_minio):
        mock_minio.put_object('bucket', 'key', b'data', len(b'data'))
        mock_minio.put_object.assert_called_once()

    def test_get_object(self, mock_minio):
        result = mock_minio.get_object('bucket', 'key')
        assert result.read() == b'test-data'


class TestMockOpenFGA:
    """Verify mock_openfga fixture stores and checks tuples."""

    @pytest.mark.asyncio
    async def test_write_and_check(self, mock_openfga):
        await mock_openfga.write_tuples([
            {'object': 'workflow:wf-1', 'relation': 'viewer', 'user': 'user:alice'},
        ])
        assert await mock_openfga.check('user:alice', 'viewer', 'workflow:wf-1') is True
        assert await mock_openfga.check('user:bob', 'viewer', 'workflow:wf-1') is False

    @pytest.mark.asyncio
    async def test_list_objects(self, mock_openfga):
        await mock_openfga.write_tuples([
            {'object': 'workflow:wf-1', 'relation': 'viewer', 'user': 'user:alice'},
            {'object': 'workflow:wf-2', 'relation': 'editor', 'user': 'user:alice'},
            {'object': 'knowledge:ks-1', 'relation': 'viewer', 'user': 'user:alice'},
        ])
        wfs = await mock_openfga.list_objects('user:alice', 'viewer', 'workflow')
        assert wfs == ['workflow:wf-1']

    @pytest.mark.asyncio
    async def test_assert_helpers(self, mock_openfga):
        await mock_openfga.write_tuples([
            {'object': 'workflow:wf-1', 'relation': 'owner', 'user': 'user:admin'},
        ])
        mock_openfga.assert_tuple_exists('user:admin', 'owner', 'workflow:wf-1')
        mock_openfga.assert_tuple_count(1)

        with pytest.raises(AssertionError):
            mock_openfga.assert_tuple_exists('user:nobody', 'owner', 'workflow:wf-1')

    @pytest.mark.asyncio
    async def test_delete_tuples(self, mock_openfga):
        await mock_openfga.write_tuples([
            {'object': 'workflow:wf-1', 'relation': 'viewer', 'user': 'user:alice'},
        ])
        await mock_openfga.delete_tuples([
            {'object': 'workflow:wf-1', 'relation': 'viewer', 'user': 'user:alice'},
        ])
        assert await mock_openfga.check('user:alice', 'viewer', 'workflow:wf-1') is False
        mock_openfga.assert_tuple_count(0)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

class TestFactories:
    """Verify test data factory functions create records correctly."""

    def test_create_tenant(self, db_session):
        from test.fixtures.factories import create_tenant
        tenant = create_tenant(db_session, code='factory_test', name='Factory Tenant')
        assert tenant['tenant_code'] == 'factory_test'
        assert tenant['tenant_name'] == 'Factory Tenant'
        assert tenant['id'] is not None

    def test_create_test_user(self, db_session):
        from test.fixtures.factories import create_test_user
        user = create_test_user(db_session, user_name='smoke_user')
        assert user['user_name'] == 'smoke_user'
        assert user['user_id'] is not None


# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------

class TestTestClient:
    """Verify test_client fixture can serve HTTP requests."""

    def test_health_endpoint(self, test_client):
        response = test_client.get('/health')
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'OK'
