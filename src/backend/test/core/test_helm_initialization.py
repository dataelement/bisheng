"""Initializer ordering/schema checks; fake SQL cursor, never company databases."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from initialize_gateway import (  # noqa: E402 - scripts CLI bootstrap.
    expected_schema,
    initialize,
)
from initialize_mysql import (  # noqa: E402 - scripts CLI bootstrap.
    initialize as initialize_mysql,
)


class Connection:
    def __init__(self, schema=None):
        self.schema = schema or {}
        self.calls = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, args=None):
        self.calls.append((sql, args))

    def fetchall(self):
        sql = self.calls[-1][0]
        if sql == "SHOW TABLES":
            return [(name,) for name in self.schema]
        if sql.startswith("SHOW COLUMNS"):
            return list(self.schema[sql.split("`")[1]].items())
        return []


def sql_contract():
    return (Path(__file__).parents[4] / "docker/gateway/init.sql").read_text()


def test_gateway_fresh_contract_and_matching_upgrade_use_no_root_or_database_creation():
    sql = sql_contract()
    schema = expected_schema(sql)
    assert set(schema) == {
        "gt_group_resource",
        "gt_sensitive_words",
        "gt_user_group",
        "gt_block_record",
        "gt_department",
        "gt_department_resource",
    }
    first = Connection()
    assert initialize(first, sql)
    assert all(command.upper().startswith("CREATE TABLE") for command, _ in first.calls[1:])
    second = Connection(schema)
    assert initialize(second, sql, verify_only=True)
    assert not any("CREATE" in command for command, _ in second.calls)
    with pytest.raises(RuntimeError, match="explicit version"):
        initialize(Connection({"foreign": {"id": "INT"}}), sql)
    assert initialize(Connection(), sql, verify_only=True) is False


def test_owned_mysql_scope_and_password_are_driver_parameters(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("quoted'password")
    connection = Connection()
    initialize_mysql(connection, [{"name": "platform_db", "username": "platform", "password_file": str(secret)}])
    assert "platform_db" in connection.calls[0][0]
    assert connection.calls[1][1] == ("platform", "quoted'password")
    assert all("quoted'password" not in command for command, _ in connection.calls)
    with pytest.raises(ValueError):
        initialize_mysql(connection, [{"name": "bad;DROP", "username": "platform", "password_file": str(secret)}])


def test_formal_initializer_orders_actual_dependencies_and_has_no_total_marker(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace

    import httpx
    import standard_helm_bootstrap as bootstrap

    from bisheng.app_runtime.domain.services import system_profile_service
    from bisheng.core import database

    events = []

    class Available:
        async def __aenter__(self):
            events.append("database")
            return self

        async def __aexit__(self, *_):
            return None

    async def manager():
        return SimpleNamespace(async_engine=SimpleNamespace(connect=Available))

    async def permissions(**kwargs):
        assert kwargs == {"allow_create": True}
        events.append("permissions")

    async def catalog(root):
        assert root == tmp_path
        events.append("catalog")

    def migrate(command, **kwargs):
        assert command[1:] == ["-m", "alembic", "upgrade", "head"] and kwargs["check"]
        events.append("alembic")

    def fga(request):
        events.append("openfga")
        return httpx.Response(200, json={"stores": []})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        bootstrap,
        "arguments",
        lambda: SimpleNamespace(timeout=5, runtime=True, catalog=tmp_path, allow_openfga_bootstrap=True),
    )
    monkeypatch.setattr(database, "get_database_connection", manager)
    monkeypatch.setattr(bootstrap, "initialize_permissions", permissions)
    monkeypatch.setattr(system_profile_service, "seed_official_catalog", catalog)
    monkeypatch.setattr(subprocess, "run", migrate)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(fga))
    )
    bootstrap.main()
    assert events == ["database", "alembic", "openfga", "permissions", "catalog"]
