"""Synthetic probes for the fixed beta1 migration source.

Use the target checkout on PYTHONPATH and an empty offline YAML config.
No service connections are allowed. Existence-query counts use a fake Session;
CPU measurements run the real business.build over complete synthetic snapshots.
Run in a fresh process: the query-count probe replaces module functions locally.
"""

# Block transport before importing application modules in this offline probe.
# ruff: noqa: E402

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from time import perf_counter


def deny_network(*args, **kwargs):
    raise RuntimeError("Synthetic performance probe must not access services")


socket.socket.connect = deny_network
socket.create_connection = deny_network

from scripts import f118_history_business as business
from scripts import prepare_f118_history as history
from bisheng.permission.domain.models import ResourcePermissionMode
from sqlalchemy.dialects import mysql
from sqlalchemy.sql import FROM_LINTING

TABLES = (
    "knowledge",
    "knowledgefile",
    "qaknowledge",
    "knowledge_document",
    "knowledge_document_version",
    "tag",
    "taglink",
    "space_channel_member",
    "flow",
    "flowversion",
    "business_reference_set",
    "business_resource_reference",
    "knowledge_space_delete_job",
)


def snapshot():
    return {name: [] for name in TABLES}


class RootId(int):
    conversions = 0

    def __str__(self):
        type(self).conversions += 1
        return super().__str__()


results = {
    "basis": "c3319b055033da7a2f4466cb2a0c9f6e94db63d3",
    "cpu": [],
    "id_conversions": [],
    "existence_sql": [],
}
for n in (1000, 2000, 4000, 8000):
    data = snapshot()
    data["knowledge"] = [
        {"id": i + 1, "tenant_id": 1, "type": 3, "model": "1"} for i in range(n)
    ]
    data["space_channel_member"] = [
        {"id": i + 1, "business_type": "space", "business_id": str(i + 1)}
        for i in range(n)
    ]
    start = perf_counter()
    plan, _ = business.build(data)
    elapsed = perf_counter() - start
    assert not plan["blocked"] and not plan["updates"] and not plan["deletes"]
    results["cpu"].append({"spaces": n, "members": n, "seconds": round(elapsed, 4)})
for n in (100, 200):
    data = snapshot()
    data["knowledge"] = [
        {"id": RootId(i + 1), "tenant_id": 1, "type": 3, "model": "1"} for i in range(n)
    ]
    data["space_channel_member"] = [
        {"id": i + 1, "business_type": "space", "business_id": str(i + 1)}
        for i in range(n)
    ]
    RootId.conversions = 0
    business.build(data)
    results["id_conversions"].append(
        {"spaces": n, "members": n, "str_calls": RootId.conversions}
    )


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


async def existence(n):
    data = snapshot()
    data["knowledge"] = [{"id": 1, "tenant_id": 1, "type": 3, "model": "1"}]
    data["knowledgefile"] = [
        {
            "id": i + 1,
            "tenant_id": 1,
            "knowledge_id": 1,
            "file_type": 1,
            "file_level_path": "",
            "level": 0,
        }
        for i in range(n)
    ]
    modes = [
        ResourcePermissionMode(
            id=i + 1,
            tenant_id=1,
            resource_type="knowledge_file",
            resource_id=str(i + 1),
            mode="PRIVATE",
            parent_type="knowledge_space",
            parent_id="1",
            projection_state="CURRENT",
            version=1,
        )
        for i in range(n)
    ]
    counts = {"all_modes": 0, "existence": 0}

    class Session:
        async def exec(self, query):
            sql = str(query.compile(dialect=mysql.dialect(), linting=FROM_LINTING))
            if "FROM resource_permission_mode" in sql:
                counts["all_modes"] += 1
                return Rows(modes)
            assert "FROM knowledgefile" in sql, sql
            counts["existence"] += 1
            return Rows([1])

    @asynccontextmanager
    async def sessions(_):
        yield Session()

    async def pin(_):
        return {"store_id": "synthetic", "model_id": "synthetic"}

    async def unfrozen(_):
        return None

    async def read(_):
        return data

    history.global_session, history.read_pin, history.unfrozen, business.read = (
        sessions,
        pin,
        unfrozen,
        read,
    )

    class Client:
        async def iter_tuples(self, **kwargs):
            for i in range(n):
                yield {
                    "user": "knowledge_space:1",
                    "relation": "parent",
                    "object": "knowledge_file:" + str(i + 1),
                }

    plan = await history.capture(None, Client())
    assert not plan["blocked"] and not plan["parents"] and not plan["purges"]
    return {"healthy_modes": n, "sql_count": sum(counts.values()), **counts}


for n in (100, 1000):
    results["existence_sql"].append(asyncio.run(existence(n)))
print(json.dumps(results, indent=2))
