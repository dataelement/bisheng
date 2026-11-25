"""Offline, synthetic negative controls; none of these URLs is connected."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, text

from test.knowledge.f026_ledger_database import dedicated_target, require_empty, verify_target


@pytest.mark.parametrize(
    ("kind", "url"),
    [
        ("mysql", "sqlite+aiosqlite://"),
        ("dm8", "sqlite+aiosqlite://"),
        ("dm8", "mysql+aiomysql://f026_test_ci@localhost/f026_test_ci"),
        ("mysql", "mysql+aiomysql://root@localhost/f026_test_ci"),
        ("mysql", "mysql+aiomysql://business@localhost/business"),
        ("mysql", "mysql+aiomysql://f026_test_ci@localhost/f026_test_ci?read_default_file=test"),
        ("dm8", "dm+dmAsync://SYSDBA@localhost?schema=F026_TEST_CI"),
        ("dm8", "dm+dmAsync://F026_TEST_CI@localhost/OTHER?schema=F026_TEST_CI"),
    ],
)
def test_refuse_ambiguous_or_unsafe_dsn(kind, url):
    with pytest.raises(pytest.fail.Exception):
        dedicated_target(kind, url)


@pytest.mark.parametrize("ddl", ["CREATE TABLE sentinel (id INTEGER)", "CREATE VIEW sentinel AS SELECT 1 AS id"])
def test_refuse_existing_object_without_modifying_it(ddl):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            require_empty(connection, "main")
            connection.execute(text(ddl))
            with pytest.raises(pytest.fail.Exception, match="nonempty"):
                require_empty(connection, "main")
            assert connection.scalar(text("SELECT COUNT(*) FROM sqlite_master WHERE name='sentinel'")) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["mysql", "dm8"])
async def test_reject_sqlite_engine_even_if_dsn_claims_real_db(kind):
    conn = SimpleNamespace(dialect=SimpleNamespace(name="sqlite", is_async=True))
    with pytest.raises(pytest.fail.Exception, match="connected dialect"):
        await verify_target(conn, kind, "f026_test_ci")


@pytest.mark.parametrize(
    ("schema", "login", "version", "vendor"),
    [
        ("other", "f026_test_ci@%", "8.0", "MySQL"),
        ("f026_test_ci", "root@%", "8.0", "MySQL"),
        ("f026_test_ci", "f026_test_ci@%", "10.0-MariaDB", "MySQL compatible"),
    ],
)
async def test_live_identity_must_match(schema, login, version, vendor):
    result = MagicMock()
    result.one.return_value = schema, login, version, vendor
    conn = SimpleNamespace(dialect=SimpleNamespace(name="mysql", is_async=True), execute=AsyncMock(return_value=result))
    with pytest.raises(pytest.fail.Exception, match="server/schema/login mismatch"):
        await verify_target(conn, "mysql", "f026_test_ci")
