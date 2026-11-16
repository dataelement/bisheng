"""Opt-in multi-connection MySQL test in a disposable, network-isolated container.

F086_TEST_MYSQL_CONTAINER must name a dedicated codex-f086-lock-test-* instance.
No production endpoint, published port or project configuration is used.
"""

import asyncio
import os
import subprocess
import time
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql
from sqlmodel import select

from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease
from bisheng.permission.domain.repositories.catalog_repository import execute_publication_read


def test_real_mysql_resource_grant_and_department_write_overlap_but_publication_waits():
    container = os.environ.get("F086_TEST_MYSQL_CONTAINER")
    if not container:
        pytest.skip("requires dedicated disposable MySQL container")
    assert container.startswith("codex-f086-lock-test-")
    command = [
        "docker",
        "exec",
        container,
        "mysql",
        "--protocol=socket",
        "-uroot",
        "--batch",
        "--skip-column-names",
        "f086_lock_test",
        "-e",
    ]

    def sql(query, *, check=True):
        return subprocess.run([*command, query], capture_output=True, text=True, check=check, timeout=15)

    statements = []

    class Capture:
        def get_bind(self):
            return SimpleNamespace(dialect=mysql.dialect())

        async def execute(self, statement):
            statements.append(str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})))

    async def compile_reads():
        for model in (PermissionCatalogRelease, AuthorizationModelRelease):
            await execute_publication_read(Capture(), select(model.id).where(model.id == 1), model.__table__)

    asyncio.run(compile_reads())
    assert all("LOCK IN SHARE MODE" in statement for statement in statements)
    catalog, model = statements
    sql(
        "CREATE TABLE permission_catalog_release(id INT PRIMARY KEY, status VARCHAR(16)); "
        "CREATE TABLE authorization_model_release(id INT PRIMARY KEY, status VARCHAR(16)); "
        "CREATE TABLE f086_resources(id INT PRIMARY KEY, value VARCHAR(32)); "
        "INSERT INTO permission_catalog_release VALUES(1,'CURRENT'); "
        "INSERT INTO authorization_model_release VALUES(1,'ACTIVE'); "
        "INSERT INTO f086_resources VALUES(1,'old-A'),(2,'old-B');"
    )
    readers = []
    try:
        for identity, reads in ((1, catalog), (2, catalog + ";" + model)):
            query = (
                f"START TRANSACTION; {reads}; UPDATE f086_resources SET value='updated-{identity}' WHERE id={identity}; "
                f"SELECT SLEEP(3) /* f086-reader-{identity} */; COMMIT;"
            )
            readers.append(
                subprocess.Popen([*command, query], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            )
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            processes = sql("SHOW PROCESSLIST").stdout
            # mysql CLI strips comments by default; this isolated container
            # has exactly our two reader connections executing SLEEP.
            if processes.count("SELECT SLEEP(3)") >= 2:
                break
            time.sleep(0.03)
        else:
            pytest.fail(f"independent A/B writes did not overlap; process list: {processes}")
        blocked = sql(
            "SET innodb_lock_wait_timeout=1; UPDATE permission_catalog_release SET status='FENCED' WHERE id=1;",
            check=False,
        )
        assert blocked.returncode != 0 and "Lock wait timeout" in blocked.stderr, blocked.stderr
        for reader in readers:
            _, errors = reader.communicate(timeout=10)
            assert reader.returncode == 0, errors
        assert sql("SELECT id,value FROM f086_resources ORDER BY id").stdout.splitlines() == [
            "1\tupdated-1",
            "2\tupdated-2",
        ]
        assert sql("SELECT status FROM permission_catalog_release").stdout.strip() == "CURRENT"
        sql("UPDATE permission_catalog_release SET status='FENCED' WHERE id=1")
        assert sql("SELECT status FROM permission_catalog_release").stdout.strip() == "FENCED"
    finally:
        for reader in readers:
            if reader.poll() is None:
                reader.kill()
                reader.communicate(timeout=5)
        sql("DROP TABLE IF EXISTS f086_resources, permission_catalog_release, authorization_model_release")
