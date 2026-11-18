"""Writers are stopped by operations; a new migration never inspects Celery."""

import json

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession
from test.knowledge_unification import test_migration_inventory_application as inventory

from bisheng.knowledge.application.unification_inventory_codec import record_from_values

resource_native = inventory.resource_native
native = inventory.native
module = inventory.module
complete = inventory.complete
transport = inventory.transport
DIGEST = "a" * 64


def fact(**changes):
    return record_from_values(
        "broker_task",
        **(
            {
                "tenant_id": 101,
                "task_kind": "bisheng.worker.knowledge.file_worker.parse_knowledge_file_celery",
                "task_id": "broker-message:occurrence-1",
                "space_id": 9000,
                "file_id": 1,
                "document_id": None,
                "version_id": None,
                "state": "queued",
                "configuration_digest": DIGEST,
                "record_digest": DIGEST,
                "header_tenant_id": None,
            }
            | changes
        ),
    )


class Broker:
    def __init__(self, records=(), error=None):
        self.records, self.error, self.calls, self.closed = records, error, [], 0

    async def aiter_facts(self, *, tenant_ids):
        self.calls.append(tenant_ids)
        try:
            for record in self.records:
                yield record
            if self.error:
                raise self.error
        finally:
            self.closed += 1


async def test_new_inventory_does_not_require_a_broker_probe(module, complete, transport):
    app = inventory.application(module, transport, broker_reader=None)
    async with AsyncSession(complete.engine) as session, session.begin():
        await app.arun(session, **transport.inputs)
    assert await inventory.count_runs(complete.engine) == 3


async def test_new_inventory_and_replay_never_consume_or_freeze_broker_facts(module, complete, transport):
    broker = Broker((fact(),))
    app = inventory.application(module, transport, broker_reader=broker)
    async with AsyncSession(complete.engine) as session, session.begin():
        result = await app.arun(session, **transport.inputs)
    assert not broker.calls and broker.closed == 0
    records = [row for content in transport.objects.values() for row in json.loads(content)["records"]]
    assert not any(row.get("record_type") in {"broker_task", "queued_task"} for row in records)
    replay = inventory.application(
        module,
        transport,
        broker_reader=None,
        physical_reader=None,
        queued_task_reader=None,
        sharing_reader_factory=None,
    )
    async with AsyncSession(complete.engine) as session, session.begin():
        assert await replay.arun(session, **transport.inputs) == result
    assert not broker.calls


@pytest.mark.parametrize("mode", ["foreign", "wrong_record", "partial_error"])
async def test_unneeded_broker_adapter_is_not_invoked_even_when_it_would_fail(module, complete, transport, mode):
    record = fact(tenant_id=909) if mode == "foreign" else fact()
    if mode == "wrong_record":
        record = record_from_values(
            "queued_task", **{key: value for key, value in record.data.items() if key != "header_tenant_id"}
        )
    broker = Broker((record,), RuntimeError("transport unavailable") if mode == "partial_error" else None)
    async with AsyncSession(complete.engine) as session, session.begin():
        await inventory.application(module, transport, broker_reader=broker).arun(session, **transport.inputs)
    assert not broker.calls and broker.closed == 0
    assert await inventory.count_runs(complete.engine) == 3


async def test_backlog_does_not_change_new_inventory_or_produce_queue_artifacts(module, complete, transport):
    broker = Broker(tuple(fact(task_id=f"message:{i}") for i in range(401)))
    async with AsyncSession(complete.engine) as session, session.begin():
        await inventory.application(module, transport, broker_reader=broker).arun(session, **transport.inputs)
    records = [row for content in transport.objects.values() for row in json.loads(content)["records"]]
    assert not any(row.get("record_type") in {"broker_task", "queued_task"} for row in records)
    assert not broker.calls and broker.closed == 0
