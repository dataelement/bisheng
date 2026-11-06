"""A separate broker inventory is required before the real global freeze."""

import json

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.knowledge.application.unification_inventory_codec import record_from_values
from test.knowledge_unification import test_migration_inventory_application as inventory

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


async def test_scheduler_presence_does_not_replace_missing_broker_even_on_outer_commit(module, complete, transport):
    error = None
    app = inventory.application(module, transport, broker_reader=None)
    async with AsyncSession(complete.engine) as session, session.begin():
        try:
            await app.arun(session, **transport.inputs)
        except ReferenceCoverageNotReadyError as caught:
            error = caught
    assert error is not None
    assert await inventory.count_runs(complete.engine) == 0


async def test_broker_once_global_and_authoritative_tenant_pages_are_frozen_and_replayed(module, complete, transport):
    records = (
        fact(),
        fact(
            tenant_id=None,
            state="global_control",
            task_id="control",
            file_id=None,
            space_id=None,
            task_kind="bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
            header_tenant_id=202,
        ),
        fact(
            tenant_id=None, state="target_missing", task_id="missing", file_id=909, space_id=None, header_tenant_id=202
        ),
    )
    broker = Broker(records)
    app = inventory.application(module, transport, broker_reader=broker)
    async with AsyncSession(complete.engine) as session, session.begin():
        result = await app.arun(session, **transport.inputs)
    assert broker.calls == [(1, 101, 202)] and broker.closed == 1
    pages = [json.loads(value) for value in transport.objects.values()]
    seen = {}
    for page in pages:
        for row in page["records"]:
            if row.get("record_type") == "broker_task":
                seen[row["task_id"]] = (page["records"][0]["scope"], page["records"][0]["tenant_id"], row)
    assert set(seen) == {"broker-message:occurrence-1", "control", "missing"}
    assert seen["broker-message:occurrence-1"][:2] == ("tenant", 101)
    assert seen["control"][:2] == seen["missing"][:2] == ("global", None)
    assert seen["missing"][2]["header_tenant_id"] == 202
    # Reentry reads original artifacts, without rebuilding the broker baseline.
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
    assert broker.calls == [(1, 101, 202)]


@pytest.mark.parametrize("mode", ["foreign", "wrong_record", "partial_error"])
async def test_bad_broker_stream_is_closed_and_never_freezes_even_after_outer_commit(module, complete, transport, mode):
    record = fact(tenant_id=909) if mode == "foreign" else fact()
    if mode == "wrong_record":
        record = record_from_values(
            "queued_task", **{key: value for key, value in record.data.items() if key != "header_tenant_id"}
        )
    failure = RuntimeError("transport unavailable") if mode == "partial_error" else None
    broker = Broker((record,), failure)
    app = inventory.application(module, transport, broker_reader=broker)
    raised = None
    async with AsyncSession(complete.engine) as session, session.begin():
        try:
            await app.arun(session, **transport.inputs)
        except (KnowledgeOperationPlanConflictError, RuntimeError) as error:
            raised = error
    assert raised is not None and broker.closed == 1
    if failure is not None:
        assert raised is failure
    assert await inventory.count_runs(complete.engine) == 0


async def test_many_broker_occurrences_stay_paged_and_original_scheduler_is_also_kept(module, complete, transport):
    broker = Broker(tuple(fact(task_id=f"message:{i}") for i in range(401)))
    app = inventory.application(module, transport, broker_reader=broker)
    async with AsyncSession(complete.engine) as session, session.begin():
        await app.arun(session, **transport.inputs)
    contents = [json.loads(value) for value in transport.objects.values()]
    broker_pages = [
        page for page in contents if any(row.get("record_type") == "broker_task" for row in page["records"])
    ]
    rows = [row for page in broker_pages for row in page["records"] if row.get("record_type") == "broker_task"]
    assert len(rows) == len({row["task_id"] for row in rows}) == 401
    assert all(len(page["records"]) <= 200 for page in broker_pages)
    assert len(broker_pages) == 3
    assert any(row.get("record_type") == "queued_task" for page in contents for row in page["records"])
    assert broker.calls == [(1, 101, 202)] and broker.closed == 1
