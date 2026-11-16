"""R1: concurrent projection readers share a barrier; publication cannot pass.

The lock scheduler is deterministic, driven by real repository SQL. It is not
a substitute for the MySQL/DM multi-connection acceptance test.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.sql.elements import TextClause

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.application.control_state import SqlPermissionControlState
from bisheng.permission.domain.models import PermissionCatalogRelease
from bisheng.permission.domain.repositories.catalog_repository import CatalogRepository


class PublicationSchedule:
    def __init__(self, backend):
        self.dialect = mysql.dialect() if backend == "mysql" else DefaultDialect()
        self.dialect.name = backend
        self.readers = set()
        self.exclusive = None
        self.empty = asyncio.Event()
        self.empty.set()
        self.sql = []
        self.fenced = False

    @asynccontextmanager
    async def session(self, identity):
        schedule = self

        class Session:
            def get_bind(self):
                return SimpleNamespace(dialect=schedule.dialect)

            async def execute(self, statement):
                schedule.sql.append(str(statement.compile(dialect=schedule.dialect)))
                if isinstance(statement, TextClause):
                    assert " IN SHARE MODE" in str(statement)
                    shared = True
                else:
                    lock = statement._for_update_arg
                    shared = lock is not None and lock.read
                    if lock is None:
                        assert schedule.dialect.name == "dm" and identity in schedule.readers
                        return self.rows(statement)
                if shared:
                    assert schedule.exclusive in (None, identity)
                    schedule.readers.add(identity)
                else:
                    if schedule.readers - {identity} or schedule.exclusive not in (None, identity):
                        raise RuntimeError("unrelated department conflicts on global Catalog")
                    schedule.exclusive = identity
                    schedule.readers.add(identity)
                schedule.empty.clear()
                if isinstance(statement, TextClause):
                    return None
                return self.rows(statement)

            def rows(self, statement):
                entity = statement.column_descriptions[0]["entity"]
                row = (
                    SimpleNamespace(
                        id=1,
                        version=1,
                        checksum="c",
                        write_fenced=schedule.fenced,
                        required_authorization_model_release_id=2,
                    )
                    if entity is PermissionCatalogRelease
                    else SimpleNamespace(id=2, status="ACTIVE", store_id="s", model_id="m", model_checksum="c")
                )

                class Rows:
                    def __iter__(self):
                        return iter([row])

                    def all(self):
                        return [row]

                    def first(self):
                        return row

                return SimpleNamespace(scalars=Rows)

        try:
            yield Session()
        finally:
            self.readers.discard(identity)
            if self.exclusive == identity:
                self.exclusive = None
            if not self.readers:
                self.empty.set()


@pytest.mark.parametrize("backend", ["mysql", "dm"])
async def test_normal_sync_member_change_and_auto_reader_can_overlap_but_publish_waits(backend):
    schedule = PublicationSchedule(backend)
    arrived, all_arrived, release = set(), asyncio.Event(), asyncio.Event()
    publisher_entered = asyncio.Event()

    async def projection(identity):
        async with schedule.session(identity) as session:
            repository = CatalogRepository()
            async with repository.bind_session(session):
                pin = await repository.aget_recovery_environment(lock=True)
                assert (pin["store_id"], pin["model_id"]) == ("s", "m")
                if identity == "resource-A-grant":
                    await SqlPermissionControlState._assert_catalog_writable(session, expected_release_id=1)
                arrived.add(identity)
                if len(arrived) == 4:
                    all_arrived.set()
                # Retain the SQL publication barrier during external writes/readback.
                await release.wait()

    async def publisher():
        await all_arrived.wait()
        await schedule.empty.wait()
        publisher_entered.set()

    async with asyncio.timeout(2):
        async with asyncio.TaskGroup() as tasks:
            for identity in ("normal-sync", "member-change", "automatic-recovery", "resource-A-grant"):
                tasks.create_task(projection(identity))
            tasks.create_task(publisher())
            await all_arrived.wait()
            assert not publisher_entered.is_set()
            assert len(schedule.readers) == 4
            release.set()
    assert publisher_entered.is_set() and not schedule.readers
    if backend == "mysql":
        assert all("LOCK IN SHARE MODE" in sql and "NOWAIT" not in sql for sql in schedule.sql)
    else:
        assert sum("LOCK TABLE" in sql for sql in schedule.sql) == 9
        assert all("FOR UPDATE" not in sql for sql in schedule.sql)


@pytest.mark.parametrize("backend", ["mysql", "dm"])
async def test_published_fence_rejects_new_work_and_releases_reader_locks(backend):
    schedule = PublicationSchedule(backend)
    schedule.fenced = True
    with pytest.raises(PermissionPublishNotReadyError):
        async with schedule.session("new-work") as session:
            repository = CatalogRepository()
            async with repository.bind_session(session):
                await repository.aget_recovery_environment(lock=True)
    assert not schedule.readers and schedule.empty.is_set()
