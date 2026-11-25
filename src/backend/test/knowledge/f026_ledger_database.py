"""Isolated ledger test engines, never the application's database manager.

Real targets must be empty, dedicated f026_test_* schemas, operated exclusively
by this job, with a same-name schema-scoped login and no production privileges.
The fixture creates only its two tables; a leftover from an interrupted job is
an error, not permission to drop it. This is not an Alembic migration test.
"""

import os
import re
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import create_async_engine

from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance, KnowledgeProviderOperation

_DRIVERS = {"mysql": "mysql+aiomysql", "dm8": "dm+dmAsync"}
_TABLES = (KnowledgeProviderInstance.__table__, KnowledgeProviderOperation.__table__)


def dedicated_target(kind, value):
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        pytest.fail(f"invalid dedicated {kind} test URL", pytrace=False)
    if url.drivername != _DRIVERS[kind]:
        pytest.fail(f"test URL does not select the expected {kind} async dialect", pytrace=False)
    schema = url.database if kind == "mysql" else url.query.get("schema", url.username)
    if not (
        url.host
        and isinstance(schema, str)
        and re.fullmatch(r"f026_test_[a-z0-9_]{1,20}", schema, re.ASCII | re.IGNORECASE)
        and schema.lower() == (url.username or "").lower()
        and (kind == "mysql" or not url.database)
        # Do not forward arbitrary driver options (e.g. init_command).
        and not (url.query.keys() - ({"schema"} if kind == "dm8" else set()))
    ):
        pytest.fail(f"refusing non-disposable or ambiguous {kind} ledger target", pytrace=False)
    return url, schema


async def verify_target(conn, kind, schema):
    if conn.dialect.name != _DRIVERS[kind].split("+")[0] or not conn.dialect.is_async:
        pytest.fail(f"connected dialect is not the expected async {kind}", pytrace=False)
    if kind == "mysql":
        actual, login, version, vendor = (
            await conn.execute(text("SELECT DATABASE(), CURRENT_USER(), VERSION(), @@version_comment"))
        ).one()
        genuine = "mysql" in str(vendor).lower() and "mariadb" not in str(version).lower()
        login = str(login).split("@", 1)[0]
    else:
        actual, login = (
            await conn.execute(text("SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA'), USER FROM DUAL"))
        ).one()
        banners = (await conn.scalars(text("SELECT BANNER FROM V$VERSION"))).all()
        genuine = any(re.search(r"\bDM\b.*\bV8\b|\bDM8\b", str(row), re.I) for row in banners)
    if not genuine or str(actual) != schema or str(login).lower() != schema.lower():
        pytest.fail(f"live {kind} server/schema/login mismatch before ledger DDL", pytrace=False)


def require_empty(connection, schema):
    inspector = inspect(connection)
    if inspector.get_table_names(schema=schema) or inspector.get_view_names(schema=schema):
        pytest.fail("refusing nonempty dedicated ledger schema", pytrace=False)


@asynccontextmanager
async def ledger_engine(kind, sqlite_path):
    schema = None
    if kind == "sqlite":
        url = f"sqlite+aiosqlite:///{sqlite_path}"
    else:
        value = os.environ.get(f"F026_TEST_{kind.upper()}_URL")
        if not value:
            if os.environ.get("F026_REQUIRE_REAL_DBS") == "1":
                pytest.fail(f"required dedicated {kind} test URL is missing", pytrace=False)
            pytest.skip(f"no dedicated {kind} test URL configured")
        url, schema = dedicated_target(kind, value)
    # Schema-qualify DDL *and* ORM DML on every connection, also across restart.
    engine = create_async_engine(url, hide_parameters=True, execution_options={"schema_translate_map": {None: schema}})
    created = []
    try:
        async with engine.begin() as conn:
            if schema is not None:
                await verify_target(conn, kind, schema)
                await conn.run_sync(require_empty, schema)
            for table in _TABLES:
                # Never adopt an existing table, even after a competing CREATE.
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=False))
                created.append(table)
        yield engine
    finally:
        try:
            if created:
                async with engine.begin() as conn:
                    if schema is not None:
                        await verify_target(conn, kind, schema)
                    for table in reversed(created):
                        await conn.run_sync(lambda c, t=table: t.drop(c, checkfirst=False))
        finally:
            await engine.dispose()
