"""Real MySQL 8 observations for two HTTP WF writers; never mutate source SQL.

F118_E2E_MYSQL_FIXTURE_FILE is owner-only mode 0600 JSON with exactly
host=127.0.0.1, port=<operator SSH forward>, user, password, database=bisheng.
It is read only during an explicitly enabled test, never at collection time.
The MySQL account must read data_locks/waits, threads, statement history/current
and current transactions. Missing instrumentation/privileges fail, never skip.
"""

from __future__ import annotations

import asyncio
import json
import re
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

from bisheng.resource_reference.application.contracts import reference_set_digest
from bisheng.workflow.domain.services.reference_extractor import extract_workflow_version_references
from test.e2e.helpers.f118_unification import F118Environment, required

FLOW_NAMES = ("wf-same", "wf-versions")
SPACE_NAMES = ("native", "permissions", "rules")


@dataclass(frozen=True, repr=False)
class MysqlFixture:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_environment(cls):
        path = Path(required("F118_E2E_MYSQL_FIXTURE_FILE"))
        if not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ValueError("F118_E2E_MYSQL_FIXTURE_FILE must be a regular mode-0600 private file")
        values = json.loads(path.read_text())
        if not isinstance(values, dict) or set(values) != {"host", "port", "user", "password", "database"}:
            raise ValueError("MySQL fixture must contain exactly the documented five fields")
        if values["host"] != "127.0.0.1" or values["database"] != "bisheng":
            raise ValueError("Only the operator's loopback SSH forward to isolated bisheng is allowed")
        if type(values["port"]) is not int or not 1 <= values["port"] <= 65535:
            raise ValueError("MySQL forward port must be a positive native integer")
        if any(not isinstance(values[key], str) or not values[key] for key in ("user", "password")):
            raise ValueError("MySQL user/password must be supplied in the private fixture")
        return cls(**values)

    def connect(self):
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=DictCursor,
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
        )

    def read(self, sql, params=()):
        assert sql.lstrip().upper().startswith("SELECT ") and ";" not in sql, "observation SQL is SELECT-only"
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    async def preflight(self):
        version = (await asyncio.to_thread(self.read, "SELECT VERSION() AS version, DATABASE() AS db"))[0]
        assert version["version"].startswith("8.") and "MariaDB" not in version["version"], "MySQL 8 is required"
        assert version["db"] == "bisheng"
        probes = (
            "SELECT ENGINE, ENGINE_LOCK_ID, ENGINE_TRANSACTION_ID, THREAD_ID, OBJECT_SCHEMA, OBJECT_NAME, INDEX_NAME, LOCK_TYPE, LOCK_MODE, LOCK_STATUS, LOCK_DATA FROM performance_schema.data_locks LIMIT 0",
            "SELECT ENGINE, REQUESTING_ENGINE_LOCK_ID, BLOCKING_ENGINE_LOCK_ID FROM performance_schema.data_lock_waits LIMIT 0",
            "SELECT THREAD_ID, PROCESSLIST_ID FROM performance_schema.threads LIMIT 0",
            "SELECT THREAD_ID, EVENT_ID, NESTING_EVENT_ID, NESTING_EVENT_TYPE, SQL_TEXT FROM performance_schema.events_statements_history LIMIT 0",
            "SELECT THREAD_ID, NESTING_EVENT_ID, NESTING_EVENT_TYPE, SQL_TEXT FROM performance_schema.events_statements_current LIMIT 0",
            "SELECT THREAD_ID, EVENT_ID, STATE, ISOLATION_LEVEL FROM performance_schema.events_transactions_current LIMIT 0",
        )
        for sql in probes:
            await asyncio.to_thread(self.read, sql)
        return version

    def source_snapshot(self, tenant, flow_id, versions):
        assert type(tenant) is int and tenant > 1 and re.fullmatch(r"[a-f0-9]{32}", flow_id)
        assert 1 <= len(versions) <= 2 and all(type(value) is int and value > 0 for value in versions)
        marks = ",".join(["%s"] * len(versions))
        with self.connect() as connection, connection.cursor() as cursor:
            connection.begin()
            try:
                cursor.execute(
                    "SELECT id, tenant_id, flow_id, user_id, data, is_current, is_delete FROM flowversion "
                    f"WHERE tenant_id=%s AND flow_id=%s AND id IN ({marks}) ORDER BY id",
                    (tenant, flow_id, *versions),
                )
                rows = cursor.fetchall()
                for row in rows:
                    if isinstance(row["data"], (str, bytes)):
                        row["data"] = json.loads(row["data"])
                cursor.execute(
                    "SELECT id, source_version, record_kind, source_revision, extractor_version, digest, effective, ready "
                    "FROM business_reference_set WHERE tenant_id=%s AND source_type='workflow_version' AND source_id=%s "
                    f"AND source_version IN ({marks},%s) ORDER BY source_version",
                    (tenant, flow_id, *map(str, versions), "__root__"),
                )
                sets = cursor.fetchall()
                cursor.execute(
                    "SELECT source_version, slot_key, target_type, target_id, target_tenant_id, target_space_id, "
                    "source_revision, legacy_invalid_reason, legacy_run_id, legacy_evidence_key "
                    "FROM business_resource_reference WHERE tenant_id=%s AND source_type='workflow_version' AND source_id=%s "
                    f"AND source_version IN ({marks}) ORDER BY source_version, slot_key, target_type, target_id",
                    (tenant, flow_id, *map(str, versions)),
                )
                references = cursor.fetchall()
                return {
                    "versions": {row["id"]: row for row in rows},
                    "sets": {row["source_version"]: row for row in sets},
                    "references": references,
                }
            finally:
                connection.rollback()

    async def snapshot(self, tenant, flow_id, versions):
        return await asyncio.to_thread(self.source_snapshot, tenant, flow_id, tuple(versions))

    def waiters(self, gate_id, target_id, flow_id):
        rows = self.read(
            "SELECT w.REQUESTING_THREAD_ID AS thread_id, r.ENGINE_TRANSACTION_ID AS trx_id, "
            "r.LOCK_DATA AS lock_data, t.PROCESSLIST_ID AS connection_id, "
            "x.EVENT_ID AS transaction_event, x.STATE AS transaction_state, x.ISOLATION_LEVEL AS isolation, "
            "s.SQL_TEXT AS statement, s.NESTING_EVENT_ID AS statement_transaction, s.NESTING_EVENT_TYPE AS nesting_type "
            "FROM performance_schema.data_lock_waits w "
            "JOIN performance_schema.data_locks r ON r.ENGINE=w.ENGINE AND r.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID "
            "JOIN performance_schema.data_locks b ON b.ENGINE=w.ENGINE AND b.ENGINE_LOCK_ID=w.BLOCKING_ENGINE_LOCK_ID "
            "JOIN performance_schema.threads t ON t.THREAD_ID=r.THREAD_ID "
            "JOIN performance_schema.threads g ON g.THREAD_ID=b.THREAD_ID "
            "JOIN performance_schema.events_transactions_current x ON x.THREAD_ID=r.THREAD_ID "
            "LEFT JOIN performance_schema.events_statements_current s ON s.THREAD_ID=r.THREAD_ID "
            "WHERE r.OBJECT_SCHEMA=%s AND r.OBJECT_NAME='knowledge' AND r.INDEX_NAME='PRIMARY' "
            "AND r.LOCK_TYPE='RECORD' AND r.LOCK_STATUS='WAITING' AND g.PROCESSLIST_ID=%s",
            (self.database, gate_id),
        )
        result = {}
        for row in rows:
            if row["lock_data"] != str(target_id):
                continue
            statement = row["statement"] or ""
            assert row["transaction_state"] == "ACTIVE" and row["trx_id"]
            assert row["nesting_type"] == "TRANSACTION" and row["statement_transaction"] == row["transaction_event"], (
                "current target lock must belong to the active transaction"
            )
            assert (
                "SELECT" in statement.upper() and "FOR UPDATE" in statement.upper() and "knowledge" in statement.lower()
            )
            history = self.read(
                "SELECT SQL_TEXT AS statement FROM performance_schema.events_statements_history "
                "WHERE THREAD_ID=%s AND NESTING_EVENT_TYPE='TRANSACTION' AND NESTING_EVENT_ID=%s ORDER BY EVENT_ID",
                (row["thread_id"], row["transaction_event"]),
            )
            source_reads = [
                entry["statement"]
                for entry in history
                if entry["statement"]
                and flow_id in entry["statement"]
                and entry["statement"].lstrip().upper().startswith("SELECT")
            ]
            assert all(
                any(table in sql.lower() for sql in source_reads)
                for table in ("business_reference_set", "business_resource_reference")
            ), "statement history must retain actual SourceSet/BRR candidate SELECTs from this active transaction"
            result[row["thread_id"]] = {**row, "source_reads": source_reads}
        return list(result.values())


class TargetGate:
    """One connection used only by its own single-thread executor; rollback only."""

    def __init__(self, mysql, *, tenant, owner, target, name):
        self.mysql, self.tenant, self.owner, self.target, self.name = mysql, tenant, owner, target, name
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="f118-target-gate")
        self.connection = None
        self.connection_id = None

    async def call(self, function):
        return await asyncio.get_running_loop().run_in_executor(self.executor, function)

    def acquire(self):
        self.connection = self.mysql.connect()
        self.connection.begin()
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT CONNECTION_ID() AS id")
            self.connection_id = cursor.fetchone()["id"]
            cursor.execute(
                "SELECT id, tenant_id, user_id, name, type FROM knowledge "
                "WHERE tenant_id=%s AND id=%s AND user_id=%s AND type=3 FOR UPDATE",
                (self.tenant, self.target, self.owner),
            )
            row = cursor.fetchone()
            assert row is not None and row["name"] == self.name, "gate target must be this exact API-created fixture"

    def release(self):
        if self.connection is not None:
            connection, self.connection = self.connection, None
            try:
                connection.rollback()
            finally:
                connection.close()

    @asynccontextmanager
    async def held(self):
        try:
            await self.call(self.acquire)
            yield self
        finally:
            try:
                await asyncio.shield(self.call(self.release))
            finally:
                await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=False)


class CasEnvironment(F118Environment):
    """Separate Child and prefix; infrastructure owner never writes the WF."""

    uncertain_requests = False

    @property
    def prefix(self):
        return f"e2e-f118-{self.run_id}-mysql-cas-"

    @property
    def writer(self):
        return {**self.reader, "X-Management-Tenant": str(self.tenant_id)}

    async def prepare_cas(self):
        await self.prepare()
        identity = await self.ok("GET", "/user/info", actor=self.writer)
        assert (
            identity["role"] != "admin"
            and not identity["is_child_admin"]
            and identity["leaf_tenant_id"] == self.tenant_id
        )
        self.spaces = [await self.space(suffix) for suffix in SPACE_NAMES]
        assert [row["id"] for row in self.spaces] == sorted(row["id"] for row in self.spaces)
        catalog = await self.ok("GET", "/permissions/catalog", actor=self.root)
        by_key = {row["key"]: row for row in catalog["models"]}
        for space in self.spaces:
            sid = space["id"]
            available = await self.ok("GET", f"/permissions/resources/knowledge_space/{sid}/grantable-models")
            choices = sorted(
                row["key"]
                for row in available
                if row["active"]
                and row["visibility_only"]
                and "knowledge_space" in by_key[row["key"]]["visibility_only_resource_types"]
                and not by_key[row["key"]]["action_codes"]
            )
            assert choices, "actual Catalog must supply a pure-visible grantable model"
            context = await self.ok("GET", f"/permissions/resources/knowledge_space/{sid}/context")
            await self.ok(
                "POST",
                f"/permissions/resources/knowledge_space/{sid}/grants:mutate",
                json={
                    "idempotency_key": self.prefix + f"visible-{sid}",
                    "expected_resource_version": context["resource_version"],
                    "expected_catalog_release_id": context["catalog_release_id"],
                    "changes": [
                        {"op": "ADD", "model_key": choices[0], "subject": {"type": "user", "id": str(self.reader_id)}}
                    ],
                },
            )
            actions = await self.ok(
                "GET", f"/permissions/resources/knowledge_space/{sid}/my-permissions", actor=self.writer
            )
            # The unchanged F048 explanation reports model action_codes; a
            # pure-visible model has none. Verify visibility independently.
            assert actions["actions"] == [] and actions["projection_degraded"] is False
            visible = await self.info(sid, actor=self.writer)
            assert visible["id"] == sid and visible["tenant_id"] == self.tenant_id
            for action, allowed in (("visible", True), ("edit", False), ("delete", False)):
                decision = await self.ok(
                    "POST",
                    "/permissions/check",
                    actor=self.writer,
                    json={"resource_type": "knowledge_space", "resource_id": str(sid), "action": action},
                )
                assert decision["allowed"] is allowed

    async def clean_business_resources(self):
        if not self.owner:
            return
        assert not self.uncertain_requests, (
            "unsettled API requests: exact prefix retained for operator, gate already released"
        )
        if self.reader:
            page = await self.ok(
                "GET",
                "/workflow/list",
                actor=self.writer,
                params={"name": self.prefix, "flow_type": 10, "action": "visible", "page_size": 200},
            )
            assert not page["has_more"], "unexpected source pagination: no source cleanup was attempted"
            exact = {self.prefix + name for name in FLOW_NAMES}
            for name in reversed(FLOW_NAMES):
                matches = [row for row in page["data"] if row["name"] == self.prefix + name]
                assert len(matches) <= 1
                for row in matches:
                    facts = await self.ok("GET", f"/workflow/get_one_flow/{row['id']}", actor=self.writer)
                    assert (
                        facts["name"] in exact
                        and facts["tenant_id"] == self.tenant_id
                        and facts["user_id"] == self.reader_id
                        and facts["flow_type"] == 10
                    )
                    await self.ok("DELETE", f"/flows/{row['id']}", actor=self.writer)
            remaining = await self.ok(
                "GET",
                "/workflow/list",
                actor=self.writer,
                params={"name": self.prefix, "flow_type": 10, "action": "visible", "page_size": 200},
            )
            assert not remaining["has_more"] and not any(row["name"] in exact for row in remaining["data"])
        page = await self.ok("GET", "/knowledge/space/list", params={"keyword": self.prefix, "page_size": 200})
        assert not page["has_more"], "unexpected target pagination: no target cleanup was attempted"
        for name in reversed(SPACE_NAMES):
            matches = [row for row in page["data"] if row["name"] == self.name(name)]
            assert len(matches) <= 1
            for row in matches:
                facts = await self.info(row["id"])
                assert (
                    facts["name"] == self.name(name)
                    and facts["tenant_id"] == self.tenant_id
                    and facts["user_id"] == self.owner_id
                )
                await self.delete(row["id"])
                await self.error("GET", f"/knowledge/space/{row['id']}/info", 18000)

    async def create_workflow(self, suffix):
        assert suffix in FLOW_NAMES
        response = await self.request(
            "POST",
            "/workflow/create",
            actor=self.writer,
            json={"name": self.prefix + suffix, "data": graph(), "status": 1},
        )
        assert response.status_code == 201 and response.json()["status_code"] == 200
        root = response.json()["data"]
        assert (
            root["name"] == self.prefix + suffix
            and root["tenant_id"] == self.tenant_id
            and root["user_id"] == self.reader_id
            and root["status"] == 1
        )
        return root


def graph(*spaces):
    return (
        {
            "nodes": [
                {
                    "id": "canvas-r",
                    "data": {
                        "id": "r",
                        "type": "knowledge_retriever",
                        "group_params": [
                            {
                                "name": "settings",
                                "params": [
                                    {
                                        "key": "knowledge",
                                        "value": {"type": "space", "value": [{"key": sid} for sid in spaces]},
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
            "edges": [],
        }
        if spaces
        else {"nodes": [], "edges": []}
    )


def assert_snapshot(snapshot, expected, *, tenant, owner):
    assert set(snapshot["versions"]) == set(expected) and set(snapshot["sets"]) == {"__root__", *map(str, expected)}
    root = snapshot["sets"]["__root__"]
    assert root["record_kind"] == "root_guard" and not root["ready"] and not root["effective"]
    for version, data in expected.items():
        row, source = snapshot["versions"][version], snapshot["sets"][str(version)]
        assert row["tenant_id"] == tenant and row["user_id"] == owner and row["is_delete"] == 0 and row["data"] == data
        assert (
            source["record_kind"] == "source"
            and source["ready"]
            and source["effective"]
            and source["extractor_version"] == "workflow-version-v1"
        )
        references = extract_workflow_version_references(data)
        assert source["digest"] == reference_set_digest(references)
        actual = [row for row in snapshot["references"] if row["source_version"] == str(version)]
        assert {(row["slot_key"], row["target_type"], row["target_id"]) for row in actual} == {
            (ref.slot_key, ref.target.target_type.value, ref.target.target_id) for ref in references
        }
        assert all(
            row["source_revision"] == source["source_revision"]
            and row["target_tenant_id"] == tenant
            and row["legacy_invalid_reason"] is row["legacy_run_id"] is row["legacy_evidence_key"] is None
            for row in actual
        )


async def race(target, mysql, flow_id, versions, bodies):
    gate = TargetGate(
        mysql, tenant=target.tenant_id, owner=target.owner_id, target=target.spaces[0]["id"], name=target.name("native")
    )
    tasks, observed, results = [], [], []
    try:
        async with gate.held():
            tasks = [
                asyncio.create_task(
                    target.request("PUT", f"/workflow/versions/{version}", actor=target.writer, json={"data": body})
                )
                for version, body in zip(versions, bodies, strict=True)
            ]
            deadline = time.monotonic() + min(target.timeout, 15)
            while time.monotonic() < deadline:
                if any(task.done() for task in tasks):
                    codes = [
                        task.result().json()["status_code"]
                        for task in tasks
                        if task.done() and not task.cancelled() and task.exception() is None
                    ]
                    raise AssertionError(f"CAS API completed before two real target waiters; completed codes={codes}")
                observed = await asyncio.to_thread(mysql.waiters, gate.connection_id, gate.target, flow_id)
                if len(observed) == 2:
                    assert len({row["connection_id"] for row in observed}) == 2
                    assert len({row["trx_id"] for row in observed}) == 2
                    assert all(row["connection_id"] != gate.connection_id for row in observed)
                    break
                assert len(observed) < 2, "unexpected extra target waiters"
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("two instrumented MySQL target waiters not observed; no CAS concurrency proof")
    finally:
        # Gate rollback/close completes before this drain. A cancelled HTTP
        # client alone never proves that its server transaction has stopped.
        if tasks:
            drained = asyncio.gather(*tasks, return_exceptions=True)
            try:
                results = await asyncio.wait_for(asyncio.shield(drained), timeout=target.timeout)
            except (TimeoutError, asyncio.CancelledError) as error:
                target.uncertain_requests = True
                for task in tasks:
                    task.cancel()
                states = await drained
                error.add_note(
                    f"target gate released; namespace retained; terminal client states={[type(row).__name__ for row in states]}"
                )
                raise
            errors = [row for row in results if isinstance(row, BaseException)]
            if errors:
                target.uncertain_requests = True
                raise BaseExceptionGroup("CAS HTTP completion uncertain; namespace retained, gate released", errors)
    return results, observed
