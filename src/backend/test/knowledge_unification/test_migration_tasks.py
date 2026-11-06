"""T809: actual SQL reader and native Redis command shapes, no live service."""

import fnmatch
import importlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application import unification_inventory_codec as codec
from bisheng.worker.knowledge import scheduler
from test.knowledge_unification import test_migration_task_repository as sql

resource_native = sql.resource_native
native = sql.native
PREFIX = "{bisheng_fs}:"


class ReadPipeline:
    def __init__(self, redis):
        self.redis, self.commands = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.redis.resets += 1

    def hgetall(self, key):
        self.commands.append(("hgetall", key))
        return self

    def get(self, key):
        self.commands.append(("get", key))
        return self

    async def execute(self):
        self.redis.pipeline_sizes.append(len(self.commands))
        return [await getattr(self.redis, method)(key) for method, key in self.commands]


class NativeRedis:
    def __init__(self):
        self.lists, self.hashes, self.sets, self.strings = {}, {}, {}, {}
        self.calls, self.pipeline_sizes, self.resets = [], [], 0
        self.duplicate_keys, self.repeat_cursor, self.malformed, self.cluster = False, False, False, False
        self.error = None

    def pipeline(self, *, transaction):
        assert transaction is False
        return ReadPipeline(self)

    async def scan(self, cursor=0, *, match, count, target_nodes=None):
        self.calls.append(("scan", match, cursor, target_nodes))
        assert count == 200
        if self.error:
            raise self.error
        if self.malformed:
            return b"invalid response"
        keys = sorted(
            key for key in self.lists | self.hashes | self.sets | self.strings if fnmatch.fnmatchcase(key, match)
        )
        if self.repeat_cursor:
            return 1, [key.encode() for key in keys[:1]]
        if self.cluster:
            if target_nodes is None:
                return {"node-a": 1 if keys else 0, "node-b": 0}, [key.encode() for key in keys[:1]]
            assert target_nodes == "node-a"
            return {"node-a": 0}, [key.encode() for key in keys[1:]]
        page = keys[cursor : cursor + count]
        if self.duplicate_keys and page:
            page += page[:1]
        return (cursor + count if cursor + count < len(keys) else 0), [key.encode() for key in page]

    def get_node(self, *, node_name):
        return node_name

    async def type(self, key):
        for name, values in (("list", self.lists), ("hash", self.hashes), ("set", self.sets), ("string", self.strings)):
            if key in values:
                return name.encode()
        return b"none"

    async def lrange(self, key, start, end):
        self.calls.append(("lrange", key, start, end))
        assert end - start + 1 <= 200
        return deepcopy(self.lists[key][start : end + 1])

    async def hgetall(self, key):
        if key in self.lists or key in self.strings or key in self.sets:
            raise RuntimeError("WRONGTYPE")
        return deepcopy(self.hashes.get(key, {}))

    async def hmget(self, key, keys):
        self.calls.append(("hmget", key, len(keys)))
        assert len(keys) <= 200
        values = self.hashes.get(key, {})
        return [values.get(item.encode()) for item in keys]

    async def get(self, key):
        return self.strings.get(key)

    async def sscan(self, key, cursor=0, *, count):
        self.calls.append(("sscan", key, cursor))
        values = sorted(self.sets.get(key, ()))
        page = values[cursor : cursor + count]
        if self.duplicate_keys and page:
            page += page[:1]
        return cursor + count if cursor + count < len(values) else 0, page

    async def hscan(self, key, cursor=0, *, count):
        self.calls.append(("hscan", key, cursor))
        values = sorted(self.hashes.get(key, {}).items())
        return cursor + count if cursor + count < len(values) else 0, dict(values[cursor : cursor + count])


def payload(tenant=101):
    return {
        b"tenant_id": str(tenant).encode(),
        b"user_id": b"7",
        b"file_ext": b"txt",
        b"preview_cache_key": b"private-cache",
        b"callback_url": b"https://private-url/?credential=private-secret",
    }


@pytest.fixture
async def original(native, monkeypatch):
    await native.insert(
        sql.resources.Knowledge, [sql.resources.resource(9000), sql.resources.resource(8000, tenant=202)]
    )
    await native.insert(
        sql.resources.KnowledgeFile, [sql.resources.file(1), sql.resources.file(2, tenant=202, knowledge_id=8000)]
    )
    redis = NativeRedis()
    redis.lists[PREFIX + "queue:7"] = [b"1", b"2", b"1"]
    redis.hashes.update(
        {
            PREFIX + "payload:1": payload(),
            PREFIX + "payload:2": payload(202),
            PREFIX + "inflight_queue": {b"2": b"knowledge_celery"},
        }
    )
    redis.sets[PREFIX + "inflight:7"] = {b"1", b"2"}
    redis.strings[PREFIX + "parse_lock:2"] = b"private-lock-token"
    monkeypatch.setattr(
        scheduler, "FileScheduler", Mock(side_effect=AssertionError("scheduler must never be constructed"))
    )
    return SimpleNamespace(sql=native, redis=redis)


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_tasks")


async def read(module, original, **kwargs):
    async with AsyncSession(original.sql.engine) as session, session.begin():
        reader = module.QueuedTaskInventoryReader(session, redis_connection=original.redis)
        return [row async for row in reader.aiter_facts(**({"tenant_ids": (1, 101, 202)} | kwargs))]


async def test_real_sql_and_redis_keep_queue_occurrences_and_native_tenants_without_secrets(module, original):
    await original.sql.insert(sql.Job, [sql.job()])
    await original.sql.insert(sql.Item, [sql.item()])
    await original.sql.insert(sql.DeleteJob, [sql.deletion()])
    original.redis.duplicate_keys = True
    records = await read(module, original)
    rows = [record.data for record in records]
    assert len(rows) == 12
    assert {row["task_kind"] for row in rows} == {
        "scheduler_queue",
        "payload",
        "inflight",
        "dispatch",
        "parse_lock",
        "processing_job",
        "item",
        "delete_job",
    }
    queued = [row for row in rows if row["task_kind"] == "scheduler_queue"]
    assert [(row["file_id"], row["tenant_id"]) for row in queued] == [(1, 101), (2, 202), (1, 101)]
    assert len({row["task_id"] for row in queued}) == 3
    assert all("private-" not in repr(record) + record.data_json for record in records)
    assert original.redis.resets == len(original.redis.pipeline_sizes)


@pytest.mark.parametrize("case", ["queued_missing", "confirmed_missing", "ghost_with_claim", "ghost_without_claim"])
async def test_three_missing_payload_conditions_never_recover_or_guess_root(module, original, case):
    original.redis.lists, original.redis.hashes, original.redis.sets, original.redis.strings = {}, {}, {}, {}
    if case == "confirmed_missing":
        original.redis.sets[PREFIX + "inflight:7"] = {b"1"}
        original.redis.hashes[PREFIX + "inflight_queue"] = {b"1": b"knowledge_celery"}
    else:
        ident = 1 if case == "queued_missing" else 999
        original.redis.lists[PREFIX + "queue:7"] = [str(ident).encode()]
        if case == "ghost_with_claim":
            original.redis.hashes[PREFIX + "payload:999"] = payload()
    rows = await read(module, original)
    if case.startswith("ghost"):
        row = next(record for record in rows if record.data["task_kind"] == "scheduler_queue")
        assert row.record_type == "queued_task_orphan"
        assert "tenant_id" not in row.data and row.data["reason"] == "file_missing"
        assert row.data["payload_tenant_id"] == (101 if case == "ghost_with_claim" else None)
        content = codec.encode_inventory_page(
            run_id="m2", section="tasks", scope="global", tenant_id=None, page_index=0, records=(row,)
        )
        assert codec.decode_inventory_page(
            content, run_id="m2", section="tasks", scope="global", tenant_id=None, page_index=0
        ).records == (row,)
    else:
        row = next(
            record.data
            for record in rows
            if record.data["task_kind"] == ("inflight" if case == "confirmed_missing" else "scheduler_queue")
        )
        assert row["tenant_id"] == 101
        assert row["state"] == ("inflight_confirmed" if case == "confirmed_missing" else "queued_payload_missing")
    assert not hasattr(original.redis, "hset") and not hasattr(original.redis, "lpop")


@pytest.mark.parametrize(
    "problem", ["tenant_claim", "foreign_file_space", "wrong_type", "network", "malformed", "cursor_loop"]
)
async def test_contradictions_and_transport_errors_are_not_reported_as_empty_or_missing(module, original, problem):
    if problem == "tenant_claim":
        original.redis.hashes[PREFIX + "payload:1"] = payload(202)
    elif problem == "foreign_file_space":
        async with original.sql.engine.begin() as connection:
            await connection.execute(
                sql.resources.KnowledgeFile.__table__.update()
                .where(sql.resources.KnowledgeFile.id == 1)
                .values(knowledge_id=8000)
            )
    elif problem == "wrong_type":
        original.redis.lists[PREFIX + "payload:1"] = []
        del original.redis.hashes[PREFIX + "payload:1"]
    elif problem == "network":
        original.redis.error = ConnectionError("offline transport unavailable")
    elif problem == "malformed":
        original.redis.malformed = True
    else:
        original.redis.repeat_cursor = True
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await read(module, original)


async def test_10001_native_queue_and_payload_records_keep_bounded_batches_and_no_per_file_sql(module, original):
    await original.sql.insert(sql.resources.KnowledgeFile, [sql.resources.file(i) for i in range(3, 10002)])
    original.redis.lists = {PREFIX + "queue:7": [str(i).encode() for i in range(1, 10002)]}
    original.redis.hashes = {PREFIX + f"payload:{i}": payload(202 if i == 2 else 101) for i in range(1, 10002)}
    original.redis.sets, original.redis.strings = {}, {}
    original.sql.queries.clear()
    records = await read(module, original)
    assert len(records) == 20002
    assert max(original.redis.pipeline_sizes) <= 200
    assert len(original.sql.queries) <= 215
    assert sum(row.data["task_kind"] == "scheduler_queue" for row in records) == 10001
    assert all(row.data["file_id"] >= 1 for row in records)


async def test_native_cluster_scan_cursor_map_is_consumed_without_repeating_facts(module, original):
    original.redis.cluster = True
    records = await read(module, original)
    assert len(records) == 9
    assert any(call[0] == "scan" and call[-1] == "node-a" for call in original.redis.calls)


@pytest.mark.parametrize("ids", [(), (True,), (202, 101), (101, 101), [101, 202]])
async def test_invalid_complete_tenant_set_is_refused_before_transport(module, original, ids):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await read(module, original, tenant_ids=ids)
    assert not original.redis.calls


async def test_default_native_connection_is_resolved_once_and_one_reader_cannot_scan_the_run_twice(
    module, original, monkeypatch
):
    getter = AsyncMock(return_value=SimpleNamespace(async_connection=original.redis))
    monkeypatch.setattr(module, "get_redis_client", getter)
    async with AsyncSession(original.sql.engine) as session, session.begin():
        reader = module.QueuedTaskInventoryReader(session)
        assert len([record async for record in reader.aiter_facts(tenant_ids=(1, 101, 202))]) == 9
        with pytest.raises(KnowledgeOperationPlanConflictError):
            _ = [record async for record in reader.aiter_facts(tenant_ids=(1, 101, 202))]
    getter.assert_awaited_once()
