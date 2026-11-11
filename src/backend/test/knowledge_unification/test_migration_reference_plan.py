"""Actual M2 artifacts -> readonly source closure -> bounded ordered replay."""

import asyncio
import importlib
import tracemalloc
from collections import Counter
from dataclasses import fields, replace

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.database.models.flow_version import FlowVersion
from bisheng.knowledge.application.unification_inventory_codec import (
    decode_inventory_page,
    encode_inventory_page,
    iter_manifest_nodes,
    record_from_values,
)
from bisheng.knowledge.application.unification_source_codec import decode_source_page, encode_source_page
from bisheng.knowledge.application.unification_sources import (
    ReferenceInventoryRecord,
    RetiredInventoryRecord,
    RootInventoryRecord,
    SourceInventoryRecord,
)
from bisheng.resource_reference.application.contracts import SourceKey, SourceRootKey
from test.knowledge_unification import test_migration_frozen_plan_reader as graph
from test.knowledge_unification import test_migration_inventory_application as m2
from test.knowledge_unification.test_migration_source_inventory import graph as workflow_graph

resource_native = m2.resource_native
native = m2.native
complete = m2.complete
transport = m2.transport


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_reference_plan")


@pytest.fixture
async def produced(complete, transport, request):
    parameters = getattr(request, "param", (5, "single"))
    count, shape = parameters[:2]
    target = parameters[2] if len(parameters) == 3 else 11
    async with AsyncSession(complete.engine) as session, session.begin():
        session.add_all([m2.raw.flow("saved"), m2.raw.flow("retired", is_delete=1)])
        if shape == "single":
            session.add(
                FlowVersion(
                    id=1, tenant_id=101, flow_id="saved", name="saved", data=workflow_graph(*([target] * count))
                )
            )
        else:
            session.add_all(
                [
                    FlowVersion(id=i + 1, tenant_id=101, flow_id="saved", name="saved", data=workflow_graph(11))
                    for i in range(count)
                ]
            )
        session.add_all(
            [
                FlowVersion(id=1000001, tenant_id=101, flow_id="retired", name="retired", data={}),
                FlowVersion(id=1000002, tenant_id=101, flow_id="saved", name="retired", data={}, is_delete=1),
            ]
        )
    inventory_module = importlib.import_module("bisheng.knowledge.application.unification_inventory")
    async with AsyncSession(complete.engine) as session, session.begin():
        frozen = await m2.application(inventory_module, transport).arun(session, **transport.inputs)
    return complete, transport, frozen, count, shape


def reader(module, produced):
    transport = produced[1]
    inventory_module = importlib.import_module("bisheng.knowledge.application.unification_inventory")
    return module.UnificationReferencePlanReader(
        inventory=graph.reader(inventory_module, transport), artifact_store=transport.store
    )


async def prepare(module, produced):
    instance = reader(module, produced)
    return instance, await instance.aprepare(produced[2], **graph.arguments(produced[1]))


async def source_records(produced):
    inventory = importlib.import_module("bisheng.knowledge.application.unification_inventory")
    return [
        page
        async for page in graph.reader(inventory, produced[1]).aiter_frozen_pages(
            produced[2], **graph.arguments(produced[1])
        )
        if page.section == "sources" and page.tenant_id == 101
    ]


async def actual_leaves(produced, kind):
    inventory = importlib.import_module("bisheng.knowledge.application.unification_inventory")
    return [
        page
        async for page in graph.reader(inventory, produced[1]).aiter_frozen_pages(
            produced[2], **graph.arguments(produced[1])
        )
        if page.kind == kind
    ]


def entry(page):
    return record_from_values(
        "manifest_entry",
        section=page.section,
        scope=page.scope,
        tenant_id=page.tenant_id,
        page_index=page.page_index,
        record_count=page.record_count,
        descriptor=page.descriptor,
        level=0,
    )


async def rewrite_sources(produced, change):
    _, transport, frozen, _, _ = produced
    records = [
        record
        for page in await source_records(produced)
        for record in decode_source_page(
            page.content, run_id=frozen.run_id, tenant_id=101, page_index=page.page_index
        ).records
    ]
    change(records)
    entries = [
        entry(page)
        for page in await actual_leaves(produced, "baseline")
        if not (page.section == "sources" and page.tenant_id == 101)
    ]
    for index, offset in enumerate(range(0, len(records), 199)):
        rows = tuple(records[offset : offset + 199])
        content = encode_source_page(run_id=frozen.run_id, tenant_id=101, page_index=index, records=rows)
        descriptor = await transport.store.aput_canonical(run_id=frozen.run_id, kind="sources", content=content)
        entries.append(
            record_from_values(
                "manifest_entry",
                section="sources",
                scope="tenant",
                tenant_id=101,
                page_index=index,
                record_count=len(rows),
                descriptor=descriptor,
                level=0,
            )
        )
    changed = await graph.replace_baseline(transport, frozen, entries)
    return (*produced[:2], changed, *produced[3:])


async def rewrite_decisions(produced, change):
    _, transport, frozen, _, _ = produced
    original = graph.root_records(transport, frozen, "plan")
    entries, decisions = [], []
    for page in await actual_leaves(produced, "plan"):
        if page.section != "conversion" or page.tenant_id != 101:
            entries.append(entry(page))
            continue
        decisions.extend(
            decode_inventory_page(
                page.content,
                run_id=frozen.run_id,
                section="conversion",
                scope="tenant",
                tenant_id=101,
                page_index=page.page_index,
                kind="plan",
            ).records
        )
    change(decisions)
    for index, offset in enumerate(range(0, len(decisions), 199)):
        rows = tuple(decisions[offset : offset + 199])
        content = encode_inventory_page(
            run_id=frozen.run_id,
            section="conversion",
            scope="tenant",
            tenant_id=101,
            page_index=index,
            records=rows,
            kind="plan",
        )
        descriptor = await transport.store.aput_canonical(run_id=frozen.run_id, kind="plan", content=content)
        entries.append(
            record_from_values(
                "manifest_entry",
                section="conversion",
                scope="tenant",
                tenant_id=101,
                page_index=index,
                record_count=len(rows),
                descriptor=descriptor,
                level=0,
            )
        )
    metadata = next(record for record in original if record.record_type == "run")
    for node in iter_manifest_nodes(run_id=frozen.run_id, kind="plan", entries=iter(entries), metadata=metadata):
        descriptor = await transport.store.aput_canonical(run_id=frozen.run_id, kind="plan", content=node.content)
        if node.is_root:
            changed = replace(frozen, plan_ref=descriptor)
    return (*produced[:2], changed, *produced[3:])


async def test_actual_m2_roots_zero_versions_retired_and_replay_are_readonly(module, produced):
    database, transport, frozen, count, _ = produced
    before = dict(transport.objects)
    database.queries.clear()
    instance, plan = await prepare(module, produced)
    chunks = [chunk async for chunk in instance.aiter_reference_chunks(plan, tenant_id=101)]
    assert not database.queries and transport.objects == before and plan.frozen == frozen
    saved = [chunk for chunk in chunks if chunk.source.header.source_key.source_id == "saved"]
    assert sum(len(chunk.records) for chunk in saved) == count and saved[-1].complete
    assert all(len(chunk.records) <= 199 for chunk in chunks)
    assert all(type(record) is ReferenceInventoryRecord for chunk in chunks for record in chunk.records)
    zero = next(row for row in plan.roots if row.header.root_key.source_id == "zero-version")
    assert zero.header.retained_version_count == 0
    assert not any(entry.header.source_key.source_id == "zero-version" for entry in plan.sources)
    assert len([row for row in plan.retired if row.header.root_key.source_id in {"saved", "retired"}]) == 3
    assert all(not chunk.records and chunk.complete for chunk in chunks if chunk.source.header.reference_count == 0)
    assert not {"content", "config", "records", "references"} & {field.name for field in fields(plan)}
    assert all(
        {field.name for field in fields(page)}
        == {"section", "tenant_id", "page_index", "record_count", "object_key", "sha256"}
        for page in plan.pages
    )
    knowledge_root = next(row for row in plan.roots if row.header.root_key.source_id == "9000")
    knowledge_source = next(row for row in plan.sources if row.header.source_key.source_id == "9000")
    assert (knowledge_root.at.page.page_index, knowledge_root.at.record_index) < (
        knowledge_source.header_at.page.page_index,
        knowledge_source.header_at.record_index,
    )


@pytest.mark.parametrize(
    "produced", [(401, "single"), (10001, "single"), (401, "versions"), (10001, "versions")], indirect=True
)
async def test_actual_m2_scale_reads_each_page_once_and_never_retains_all_references(module, produced, monkeypatch):
    _, transport, _, count, shape = produced
    gets = Counter()
    original = transport.store.aload_canonical

    async def counted(descriptor, **kwargs):
        gets[descriptor["object_key"]] += 1
        return await original(descriptor, **kwargs)

    monkeypatch.setattr(transport.store, "aload_canonical", counted)
    tracemalloc.start()
    try:
        instance, plan = await prepare(module, produced)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert max(gets.values()) == 1
    gets.clear()
    total, completed, max_chunk = 0, 0, 0
    async for chunk in instance.aiter_reference_chunks(plan, tenant_id=101):
        if chunk.source.header.source_key.source_id == "saved":
            total += len(chunk.records)
            completed += chunk.complete
        max_chunk = max(max_chunk, len(chunk.records))
    assert total == count and completed == (1 if shape == "single" else count) and max_chunk <= 199
    assert max(gets.values()) == 1
    assert set(gets) <= {page.object_key for page in plan.pages if page.section == "sources"}
    entry = next(entry for entry in plan.sources if entry.header.source_key.source_id == "saved")
    root = next(row for row in plan.roots if row.header.root_key.source_id == "saved")
    assert root.at.page.page_index >= entry.references.last.page.page_index
    if shape == "single":
        assert entry.references.first.page.page_index < entry.references.last.page.page_index
        assert entry.decisions.first.page.page_index < entry.decisions.last.page.page_index
        assert peak < 4 * 1024 * 1024
    else:
        assert len([entry for entry in plan.sources if entry.header.source_key.source_id == "saved"]) == count
        assert peak < 32 * 1024 * 1024
    print({"count": count, "shape": shape, "source_pages": len(gets), "peak": peak})


async def test_resume_uses_completed_source_ordinal_and_shares_common_pages(module, produced, monkeypatch):
    instance, plan = await prepare(module, produced)
    entries = [entry for entry in plan.sources if entry.header.source_key.tenant_id == 101]
    chunks = [chunk async for chunk in instance.aiter_reference_chunks(plan, tenant_id=101, after_source_ordinal=1)]
    assert all(chunk.source in entries[1:] for chunk in chunks)
    assert [
        chunk async for chunk in instance.aiter_reference_chunks(plan, tenant_id=101, after_source_ordinal=len(entries))
    ] == []
    with pytest.raises(KnowledgeOperationPlanConflictError):
        _ = [chunk async for chunk in instance.aiter_reference_chunks(plan, tenant_id=999)]
    with pytest.raises(KnowledgeOperationPlanConflictError):
        _ = [chunk async for chunk in instance.aiter_reference_chunks(plan, tenant_id=101, after_source_ordinal=True)]


def change_source(records, case):
    header = next(
        index
        for index, row in enumerate(records)
        if type(row) is SourceInventoryRecord and row.source_key.source_id == "saved"
    )
    refs = [
        index
        for index, row in enumerate(records)
        if type(row) is ReferenceInventoryRecord and row.source_key.source_id == "saved"
    ]
    root = next(
        index
        for index, row in enumerate(records)
        if type(row) is RootInventoryRecord and row.root_key.source_id == "saved"
    )
    if case == "count":
        records[header] = replace(records[header], reference_count=999)
    elif case == "digest":
        records[header] = replace(records[header], reference_digest="f" * 64)
    elif case == "order":
        records[refs[0]], records[refs[1]] = records[refs[1]], records[refs[0]]
    elif case == "duplicate_ref":
        records.insert(refs[0], records[refs[0]])
    elif case == "foreign_source":
        records[refs[0]] = replace(records[refs[0]], source_key=SourceKey(101, "workflow_version", "saved", "other"))
    elif case == "duplicate_header":
        records.append(records[header])
    elif case == "retained":
        records[root] = replace(records[root], retained_version_count=99)
    elif case == "missing_root":
        records.pop(root)
    elif case == "duplicate_root":
        records.append(records[root])
    elif case == "retired_root":
        row = records[root]
        records.append(
            RetiredInventoryRecord(
                row.root_key, None, row.lifecycle, row.configuration_digest, row.business_revision_digest
            )
        )
    elif case == "retired_source":
        row = records[header]
        records.append(
            RetiredInventoryRecord(
                records[root].root_key,
                row.source_key,
                row.lifecycle,
                row.configuration_digest,
                row.business_revision_digest,
            )
        )
    elif case == "retired_orphan":
        index = next(
            i for i, row in enumerate(records) if type(row) is RetiredInventoryRecord and row.source_key is not None
        )
        row = records[index]
        records[index] = replace(
            row,
            root_key=SourceRootKey(101, "workflow_version", "absent"),
            source_key=SourceKey(101, "workflow_version", "absent", row.source_key.source_version),
        )


@pytest.mark.parametrize(
    "case",
    [
        "count",
        "digest",
        "order",
        "duplicate_ref",
        "foreign_source",
        "duplicate_header",
        "retained",
        "missing_root",
        "duplicate_root",
        "retired_root",
        "retired_source",
        "retired_orphan",
    ],
)
async def test_real_frozen_source_closure_rejects_semantic_corruption(module, produced, case):
    changed = await rewrite_sources(produced, lambda records: change_source(records, case))
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await prepare(module, changed)
    if case == "retired_root":
        assert caught.value.kwargs["reason"] == "migration_reference_state_retired_index_required_new_run"
    else:
        assert caught.value.kwargs["reason"].startswith("migration_reference_plan_")


@pytest.mark.parametrize(
    "case", ["missing", "extra", "order", "digest", "reopen", "foreign", "bad_key", "reserved_version"]
)
async def test_real_source_decisions_match_original_ssot_per_source(module, produced, case):
    def change(records):
        positions = [
            i
            for i, row in enumerate(records)
            if row.record_type == "source_decision" and row.data["source_id"] == "saved"
        ]
        first = positions[0]
        if case == "missing":
            records.pop(first)
        elif case == "extra":
            records.insert(first, records[first])
        elif case == "order":
            records[first], records[positions[1]] = records[positions[1]], records[first]
        elif case == "reopen":
            records.append(records.pop(first))
        else:
            replacement = {
                "digest": {"revision_digest": "f" * 64},
                "foreign": {"source_id": "unknown"},
                "bad_key": {"source_type": "unknown"},
                "reserved_version": {"source_version": "__root__"},
            }
            data = records[first].data | replacement[case]
            records[first] = record_from_values("source_decision", **data)

    changed = await rewrite_decisions(produced, change)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await prepare(module, changed)
    assert caught.value.kwargs["reason"].startswith("migration_reference_plan_")


@pytest.mark.parametrize("produced", [(1, "single", 999)], indirect=True)
async def test_actual_m2_initial_missing_numeric_slot_keeps_original_decision(module, produced):
    from bisheng.knowledge.application.unification_preflight import source_decision

    instance, plan = await prepare(module, produced)
    chunks = [chunk async for chunk in instance.aiter_reference_chunks(plan, tenant_id=101)]
    missing = next(
        row for chunk in chunks if chunk.source.header.source_key.source_id == "saved" for row in chunk.records
    )
    decision = source_decision(missing, tenant_id=101).data
    assert missing.origin == "explicit_id" and not missing.physical_fact.exists
    assert decision["disposition"] == "initial_missing" and decision["target_id"] == "999"


@pytest.mark.parametrize("produced", [(0, "single")], indirect=True)
async def test_actual_zero_reference_source_has_no_fake_span_or_decision_page(module, produced):
    instance, plan = await prepare(module, produced)
    entry = next(row for row in plan.sources if row.header.source_key.source_id == "saved")
    chunks = [row async for row in instance.aiter_reference_chunks(plan, tenant_id=101) if row.source == entry]
    assert len(chunks) == 1 and chunks[0].complete and chunks[0].records == ()
    assert entry.references is None and entry.decisions is None and entry.header.reference_count == 0


async def test_bad_tail_cancel_and_changed_consumption_page_never_write_or_return_a_partial_plan(module, produced):
    instance, plan = await prepare(module, produced)
    transport = produced[1]
    original = dict(transport.objects)
    tail = produced[2].plan_ref["object_key"]
    transport.objects[tail] = b"bad tail"
    with pytest.raises(ReferenceCoverageNotReadyError):
        await prepare(module, produced)
    transport.objects.update(original)

    def cancel():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await instance.aprepare(produced[2], **graph.arguments(transport), current=cancel)
    source_page = next(page for page in plan.pages if page.section == "sources" and page.tenant_id == 101)
    transport.objects[source_page.object_key] = b"changed"
    with pytest.raises(ReferenceCoverageNotReadyError):
        _ = [chunk async for chunk in instance.aiter_reference_chunks(plan, tenant_id=101)]
