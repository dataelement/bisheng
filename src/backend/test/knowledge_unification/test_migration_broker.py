"""T827: native read-only Redis shapes plus actual SQL targets, no live IO."""

import asyncio
import base64
import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_broker_codec import BrokerReadConfiguration
from test.knowledge_unification import test_migration_broker_codec as messages
from test.knowledge_unification import test_migration_task_repository as sql
from test.knowledge_unification.test_migration_tasks import NativeRedis

resource_native = sql.resource_native
native = sql.native
P = "b:"


def raw_message(ident=1, *, tenant=101, task=None, args=None, kwargs=None, pad=0):
    value = json.loads(
        messages.message(
            task=task or messages.PREFIX + "file_worker.parse_knowledge_file_celery",
            args=args if args is not None else [1],
            kwargs=kwargs,
            tenant=tenant,
        )
    )
    body = json.loads(base64.b64decode(value["body"]))
    if args is None:
        body[0][0] = ident
    value["body"] = base64.b64encode(json.dumps(body).encode()).decode()
    if pad:
        value["headers"]["argsrepr"] = "private-padding" + "x" * pad
    return json.dumps(value).encode()


def unacked(raw):
    return json.dumps([json.loads(raw), "", "knowledge_celery"]).encode()


class BrokerRedis(NativeRedis):
    def __init__(self):
        super().__init__()
        self.zsets, self.closed, self.pause, self.entered = {}, False, None, asyncio.Event()
        self.close_error, self.scan_types, self.hscan_all = None, [], False

    async def scan(self, cursor=0, *, match, count, _type=None, target_nodes=None):
        self.scan_types.append(_type)
        result = await super().scan(cursor=cursor, match=match, count=count, target_nodes=target_nodes)
        if _type is None or type(result) not in (tuple, list) or len(result) != 2:
            return result
        cursor, keys = result
        return cursor, [key for key in keys if (await self.type(key.decode())).decode() == _type]

    async def type(self, key):
        return b"zset" if key in self.zsets else await super().type(key)

    async def lrange(self, key, start, end):
        assert end == start  # A raw page never retains 200 sixteen-MiB bodies.
        if self.pause:
            self.entered.set()
            await self.pause.wait()
        return await super().lrange(key, start, end)

    async def hscan(self, key, cursor=0, *, count):
        assert count == 1
        if self.hscan_all:
            return 0, deepcopy(self.hashes.get(key, {}))
        return await super().hscan(key, cursor=cursor, count=count)

    async def zscan(self, key, cursor=0, *, count):
        values = sorted(self.zsets.get(key, {}).items())
        return cursor + count if cursor + count < len(values) else 0, values[cursor : cursor + count]

    async def zscore(self, key, member):
        return self.zsets.get(key, {}).get(member.encode() if isinstance(member, str) else member)

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field.encode() if isinstance(field, str) else field)

    async def aclose(self):
        await asyncio.sleep(0)
        self.closed = True
        if self.close_error:
            raise self.close_error

    def snapshot(self):
        return deepcopy((self.lists, self.hashes, self.sets, self.strings, self.zsets))


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_broker")


@pytest.fixture
async def original(native):
    await native.insert(
        sql.resources.Knowledge, [sql.resources.resource(9000), sql.resources.resource(8000, tenant=202)]
    )
    await native.insert(
        sql.resources.KnowledgeFile, [sql.resources.file(1), sql.resources.file(2, tenant=202, knowledge_id=8000)]
    )
    redis = BrokerRedis()
    one = raw_message()
    redis.lists[P + "knowledge_celery"] = [one, one]
    redis.lists[P + "knowledge_celery\x06\x163"] = [raw_message(2, tenant=202)]
    redis.lists[P + "lost-historical-queue"] = [one]
    redis.lists[P + "chat-cache"] = [b"ordinary chat text"]
    redis.hashes[P + "unacked"] = {b"delivery-1": unacked(one)}
    redis.zsets[P + "unacked_index"] = {b"delivery-1": 1234.5}
    redis.strings[P + "unacked_mutex"] = b"private-mutex-token"
    config = BrokerReadConfiguration.from_conf(messages.conf(broker_transport_options={"global_keyprefix": P}))
    return SimpleNamespace(sql=native, redis=redis, config=config)


async def read(module, original):
    async with AsyncSession(original.sql.engine) as session, session.begin():
        reader = module.RedisBrokerInventoryReader(
            session, configuration=original.config, redis_connection=original.redis
        )
        return [record async for record in reader.aiter_facts(tenant_ids=(1, 101, 202))]


async def test_priority_old_unbound_queue_and_unacked_are_real_distinct_occurrences_with_zero_writes(module, original):
    before = original.redis.snapshot()
    records = await read(module, original)
    assert len(records) == 5 and all(row.record_type == "broker_task" for row in records)
    rows = [row.data for row in records]
    assert sum(row["state"] == "queued" for row in rows) == 4
    assert sum(row["state"] == "unacked" for row in rows) == 1
    assert len({row["task_id"] for row in rows}) == 5
    assert {row["tenant_id"] for row in rows} == {101, 202}
    assert original.redis.snapshot() == before and not original.redis.closed
    assert all("private-" not in repr(row) + row.data_json for row in records)


async def test_known_nonknowledge_is_isolated_without_business_decoding_and_binding_queue_bad_data_blocks(
    module, original
):
    original.redis.lists = {
        P + "celery": [
            messages.message(task="bisheng.worker.workflow.tasks.run", body="notbase64", **{"content-type": "pickle"})
        ],
        P + "ordinary-chat": [b"not-json"],
    }
    original.redis.hashes, original.redis.zsets = {}, {}
    assert await read(module, original) == []
    original.redis.sets[P + "_kombu.binding.old"] = {b"route\x06\x16\x06\x16old-registered"}
    original.redis.lists[P + "old-registered"] = [b"malformed message"]
    with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
        await read(module, original)
    assert failure.value.kwargs["reason"] == "migration_broker_invalid_envelope"


@pytest.mark.parametrize("case", ["missing", "control", "index_orphan"])
async def test_global_evidence_never_guesses_root_or_claims_execution_authority(module, original, case):
    original.redis.lists, original.redis.hashes, original.redis.zsets = {}, {}, {}
    if case == "missing":
        original.redis.lists[P + "knowledge_celery"] = [raw_message(999, tenant=202)]
    elif case == "control":
        original.redis.lists[P + "knowledge_celery"] = [
            raw_message(task=messages.PREFIX + "scheduler.trigger_dispatch_task", args=[])
        ]
    else:
        original.redis.zsets[P + "unacked_index"] = {b"orphaned-tag": 123.5}
    row = (await read(module, original))[0].data
    assert row["tenant_id"] is None
    assert (
        row["state"]
        == {"missing": "target_missing", "control": "global_control", "index_orphan": "unacked_metadata_orphan"}[case]
    )
    assert (row["task_kind"] is None) == (case == "index_orphan")


async def test_original_root_cleanup_is_retained_even_after_its_file_was_formally_deleted(module, original):
    original.redis.lists = {
        P + "knowledge_celery": [
            raw_message(task=messages.PREFIX + "file_worker.delete_knowledge_file_celery", args=[[999], 9000])
        ]
    }
    original.redis.hashes, original.redis.zsets = {}, {}
    row = (await read(module, original))[0].data
    assert row["tenant_id"] == 101 and row["space_id"] == 9000 and row["state"] == "queued"


@pytest.mark.parametrize(
    "proof,state",
    [
        (None, "legacy_requires_reissue"),
        ({"operation_id": "old", "expected_model_config_revision": 99, "expected_index_generation": "old"}, "obsolete"),
    ],
)
async def test_old_rebuild_hint_and_stale_rg_are_preserved_without_restoring_model_bindings(
    module, original, proof, state
):
    original.redis.lists = {
        P + "knowledge_celery": [
            raw_message(
                task=messages.PREFIX + "rebuild_knowledge_worker.rebuild_knowledge_celery",
                args=[9000, 999, 7],
                kwargs=proof,
            )
        ]
    }
    original.redis.hashes, original.redis.zsets = {}, {}
    row = (await read(module, original))[0].data
    assert row["state"] == state and row["space_id"] == 9000 and row["file_id"] is None


async def test_j1_metadata_kind_and_qa_use_actual_ledger_and_qa_identity(module, original):
    await original.sql.insert(sql.Job, [sql.job() | {"kind": "metadata_schema_change"}])
    await original.sql.insert(
        sql.resources.QAKnowledge,
        [
            {
                "id": 12,
                "tenant_id": 101,
                "knowledge_id": 9000,
                "questions": ["private-question"],
                "answers": "private-answer",
            }
        ],
    )
    original.redis.lists = {
        P + "knowledge_celery": [
            raw_message(task=messages.PREFIX + "processing_jobs.execute_processing_job", args=["job-0000", 0]),
            raw_message(task=messages.PREFIX + "qa.insert_qa_celery", args=[12]),
        ]
    }
    original.redis.hashes, original.redis.zsets = {}, {}
    rows = [row.data for row in await read(module, original)]
    assert len(rows) == 2 and all(row["tenant_id"] == 101 and row["file_id"] is None for row in rows)


async def test_real_header_tenant_conflict_cannot_hide_behind_artifact_codec_failure(module, original):
    original.redis.lists = {P + "knowledge_celery": [raw_message(1, tenant=202)]}
    with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
        await read(module, original)
    assert failure.value.kwargs["reason"] == "migration_broker_header_tenant_mismatch"


async def test_10001_messages_are_decoded_once_with_lightweight_200_target_batches(module, original, monkeypatch):
    await original.sql.insert(sql.resources.KnowledgeFile, [sql.resources.file(i) for i in range(3, 10002)])
    original.redis.lists = {
        P + "knowledge_celery": [raw_message(i, tenant=202 if i == 2 else 101) for i in range(1, 10002)]
    }
    original.redis.hashes, original.redis.zsets = {}, {}
    original.sql.queries.clear()
    decoder = module.decode_broker_message
    calls = []

    def counted(*args, **kwargs):
        calls.append(True)
        return decoder(*args, **kwargs)

    monkeypatch.setattr(module, "decode_broker_message", counted)
    rows = await read(module, original)
    assert len(rows) == len(calls) == 10001
    assert len(original.sql.queries) <= 210
    assert len({row.data["task_id"] for row in rows}) == 10001


async def test_large_raw_pages_do_not_accumulate_full_bodies_and_hscan_hint_overrun_is_budgeted(
    module, original, monkeypatch
):
    large = raw_message(pad=2 * 1024 * 1024)
    original.redis.lists = {P + "knowledge_celery": [large, large]}
    original.redis.hashes, original.redis.zsets = {}, {}
    assert len(await read(module, original)) == 2
    original.redis.lists = {}
    original.redis.hashes[P + "unacked"] = {b"tag-a": unacked(large), b"tag-b": unacked(large)}
    original.redis.hscan_all = True  # Native COUNT is a hint, not a response cap.
    monkeypatch.setattr(module, "MAX_REPLY_BYTES", 3 * 1024 * 1024)
    with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
        await read(module, original)
    assert failure.value.kwargs["reason"] == "migration_broker_reply_budget"


async def test_owned_cancellation_settles_clients_borrowed_clients_stay_open(module, original, monkeypatch):
    original.redis.pause = asyncio.Event()

    async def opened(reader):
        reader._owned_clients = [original.redis]
        return original.redis

    monkeypatch.setattr(module.RedisBrokerInventoryReader, "_open", opened)
    async with AsyncSession(original.sql.engine) as session, session.begin():
        reader = module.RedisBrokerInventoryReader(session, configuration=original.config)

        async def consume():
            return [record async for record in reader.aiter_facts(tenant_ids=(1, 101, 202))]

        task = asyncio.create_task(consume())
        await asyncio.wait_for(original.redis.entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert original.redis.closed
    await reader.aclose()


async def test_failure_closes_all_owned_clients_and_preserves_the_original_cause(module, original, monkeypatch):
    other = BrokerRedis()
    original.redis.error = ConnectionError("offline read unavailable")
    original.redis.close_error = RuntimeError("cleanup failed")

    async def opened(reader):
        reader._owned_clients = [original.redis, other]
        return original.redis

    monkeypatch.setattr(module.RedisBrokerInventoryReader, "_open", opened)
    async with AsyncSession(original.sql.engine) as session, session.begin():
        reader = module.RedisBrokerInventoryReader(session, configuration=original.config)
        with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
            _ = [record async for record in reader.aiter_facts(tenant_ids=(1, 101, 202))]
        assert failure.value.__cause__ is original.redis.error
    assert original.redis.closed and other.closed


async def test_unacked_body_is_hashed_once_before_lightweight_packet_batching(module, original, monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.resource_reference.application.contracts import TransactionIdentity

    original.redis.lists = {}
    raw = next(iter(original.redis.hashes[P + "unacked"].values()))
    sha256, calls = module.hashlib.sha256, []

    def counted(value=b"", *args, **kwargs):
        if value == raw:
            calls.append(True)
        return sha256(value, *args, **kwargs)

    monkeypatch.setattr(module.hashlib, "sha256", counted)
    async with AsyncSession(original.sql.engine) as session, session.begin():
        reader = module.RedisBrokerInventoryReader(
            session, configuration=original.config, redis_connection=original.redis
        )
        reader._tenant, reader._transaction = get_current_tenant_id(), TransactionIdentity.capture(session)
        packets = [packet async for packet in reader._packets()]
    assert len(packets) == 1 and len(calls) == 1
    assert packets[0][0].target_ids == (1,) and not hasattr(packets[0][0], "body")


@pytest.mark.parametrize("case", ["wrong_type", "cursor", "malformed", "foreign_chain"])
async def test_bad_native_facts_cannot_be_converted_to_empty_broker_evidence(module, original, case):
    if case == "wrong_type":
        original.redis.strings[P + "unacked"] = b"bad-type"
        original.redis.hashes = {}
    elif case == "cursor":
        original.redis.repeat_cursor = True
    elif case == "malformed":
        original.redis.malformed = True
    else:
        async with original.sql.engine.begin() as connection:
            await connection.execute(
                sql.resources.KnowledgeFile.__table__.update()
                .where(sql.resources.KnowledgeFile.id == 1)
                .values(knowledge_id=8000)
            )
    with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
        await read(module, original)
    assert failure.value.kwargs["reason"] != "migration_inventory_codec_invalid"


async def test_one_large_message_uses_bounded_target_sql_without_rehashing_or_fake_file_slot(module, original):
    await original.sql.insert(sql.resources.KnowledgeFile, [sql.resources.file(i) for i in range(3, 10002)])
    # File 2 belongs to another tenant and is deliberately outside this one-scope task.
    targets = [i for i in range(1, 10002) if i != 2]
    original.redis.lists = {
        P + "knowledge_celery": [
            raw_message(task=messages.PREFIX + "file_worker.delete_knowledge_file_celery", args=[targets, 9000])
        ]
    }
    original.redis.hashes, original.redis.zsets = {}, {}
    original.sql.queries.clear()
    rows = await read(module, original)
    assert len(rows) == 1 and rows[0].data["tenant_id"] == 101 and rows[0].data["file_id"] is None
    assert len(original.sql.queries) <= 155


async def test_original_native_scope_and_transaction_are_required_and_pending_business_is_not_flushed(module, original):
    from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id

    original.redis.lists, original.redis.hashes, original.redis.zsets = {}, {}, {}
    async with AsyncSession(original.sql.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            _ = [
                row
                async for row in module.RedisBrokerInventoryReader(
                    session, configuration=original.config, redis_connection=original.redis
                ).aiter_facts(tenant_ids=(1, 101, 202))
            ]
        async with session.begin():
            reader = module.RedisBrokerInventoryReader(
                session, configuration=original.config, redis_connection=original.redis
            )
            pending = sql.resources.KnowledgeFile(**sql.resources.file(999))
            session.add(pending)
            assert [row async for row in reader.aiter_facts(tenant_ids=(1, 101, 202))] == []
            assert pending in session.new
            with pytest.raises(KnowledgeOperationPlanConflictError):
                _ = [row async for row in reader.aiter_facts(tenant_ids=(1, 101, 202))]
            prior = get_current_tenant_id()
            try:
                set_current_tenant_id(202 if prior != 202 else 101)
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    reader._current()
            finally:
                set_current_tenant_id(prior)
            session.expunge(pending)
        async with session.begin():
            with pytest.raises(KnowledgeOperationPlanConflictError):
                reader._current()
