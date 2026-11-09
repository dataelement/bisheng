"""Shared frozen graph reads over actual M2 output, replacing transport only."""

import asyncio
from dataclasses import FrozenInstanceError, fields, replace

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.knowledge.application.unification_inventory_codec import (
    decode_inventory_page,
    encode_inventory_page,
    iter_manifest_nodes,
    record_from_values,
)
from test.knowledge_unification import test_migration_inventory_application as original

resource_native = original.resource_native
native = original.native
complete = original.complete
transport = original.transport
module = original.module


@pytest.fixture
async def frozen(module, complete, transport):
    app = original.application(module, transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        result = await app.arun(session, **transport.inputs)
    return result


def arguments(transport):
    return {name: transport.inputs[name] for name in ("environment", "backup_ref", "schema_ref")}


def reader(module, transport):
    return module.UnificationInventoryApplication(artifact_store=transport.store)


async def read(module, transport, result, **kwargs):
    return [
        page async for page in reader(module, transport).aiter_frozen_pages(result, **arguments(transport), **kwargs)
    ]


def root_records(transport, frozen, kind):
    descriptor = getattr(frozen, kind + "_ref")
    return decode_inventory_page(
        transport.objects[descriptor["object_key"]],
        run_id=frozen.run_id,
        section="manifest",
        scope="global",
        tenant_id=None,
        page_index=0,
        kind=kind,
    ).records


async def replace_baseline(transport, frozen, entries, *, metadata_changes=None):
    metadata = next(record for record in root_records(transport, frozen, "baseline") if record.record_type == "run")
    metadata = record_from_values("run", **(metadata.data | (metadata_changes or {})))
    root = None
    for node in iter_manifest_nodes(run_id=frozen.run_id, kind="baseline", entries=iter(entries), metadata=metadata):
        descriptor = await transport.store.aput_canonical(run_id=frozen.run_id, kind="baseline", content=node.content)
        if node.is_root:
            root = descriptor
    # Keep the real plan's binding to precisely the new baseline. The helper is
    # artifact-only: this never replaces the actual SQL ledger's frozen refs.
    records = tuple(
        record_from_values("run", **(record.data | {"baseline_ref": root})) if record.record_type == "run" else record
        for record in root_records(transport, frozen, "plan")
    )
    content = encode_inventory_page(
        run_id=frozen.run_id,
        section="manifest",
        scope="global",
        tenant_id=None,
        page_index=0,
        records=records,
        kind="plan",
    )
    plan = await transport.store.aput_canonical(run_id=frozen.run_id, kind="plan", content=content)
    return replace(frozen, baseline_ref=root, plan_ref=plan)


async def leaves(transport, frozen, indices, *, tenant=101, count=None):
    # Use a genuine original M2 resource record, not a made-up typed business row.
    record = next(
        record
        for content in transport.objects.values()
        if b'"section":"resources"' in content and b'"scope":"tenant"' in content
        for record in decode_inventory_page(
            content, run_id=frozen.run_id, section="resources", scope="tenant", tenant_id=101, page_index=0
        ).records
        if record.record_type == "resource"
    )
    result = []
    for index in indices:
        fact = record_from_values("resource", **(record.data | {"tenant_id": tenant}))
        content = encode_inventory_page(
            run_id=frozen.run_id,
            section="resources",
            scope="tenant",
            tenant_id=tenant,
            page_index=index,
            records=(fact,),
            kind="baseline",
        )
        descriptor = await transport.store.aput_canonical(run_id=frozen.run_id, kind="baseline", content=content)
        result.append(
            record_from_values(
                "manifest_entry",
                section="resources",
                scope="tenant",
                tenant_id=tenant,
                page_index=index,
                record_count=1 if count is None else count,
                descriptor=descriptor,
                level=0,
            )
        )
    return tuple(result)


async def test_actual_m2_graph_yields_only_frozen_bounded_leaves_without_new_inventory(
    module, complete, transport, frozen
):
    before = dict(transport.objects)
    complete.queries.clear()
    pages = await read(module, transport, frozen)
    assert pages and complete.queries == [] and transport.objects == before
    assert all(page.section != "manifest" and page.record_count <= 199 for page in pages)
    assert all(page.scope == "global" or page.tenant_id in frozen.tenant_ids for page in pages)
    assert all(type(page.content) is bytes and len(page.content) <= 16 * 1024 * 1024 for page in pages)
    assert {field.name for field in fields(pages[0])} == {
        "kind",
        "section",
        "scope",
        "tenant_id",
        "page_index",
        "record_count",
        "descriptor",
        "content",
    }
    with pytest.raises(FrozenInstanceError):
        pages[0].tenant_id = 999
    assert not hasattr(pages[0], "__dict__")


async def test_frozen_replay_delegates_the_same_reader_and_verifies_materials_once(
    module, complete, transport, frozen, monkeypatch
):
    used, gets = [], []
    actual = module.UnificationInventoryApplication.aiter_frozen_pages
    original_get = transport.store.storage.get_object

    async def observed(self, *args, **kwargs):
        used.append(1)
        async for page in actual(self, *args, **kwargs):
            yield page

    async def get(**kwargs):
        gets.append(kwargs["object_name"])
        return await original_get(**kwargs)

    monkeypatch.setattr(module.UnificationInventoryApplication, "aiter_frozen_pages", observed)
    monkeypatch.setattr(transport.store.storage, "get_object", get)
    async with AsyncSession(complete.engine) as session, session.begin():
        assert await reader(module, transport).arun(session, **transport.inputs) == frozen
    assert used == [1]
    for key in ("backup_ref", "schema_ref"):
        assert gets.count(transport.inputs[key]["object_key"]) == 1


@pytest.mark.parametrize("indices", [(1,), (0, 2), (1, 0), (0, 0)])
async def test_leaf_page_indices_are_contiguous_ordered_and_unique(module, transport, frozen, indices):
    result = await replace_baseline(transport, frozen, await leaves(transport, frozen, indices))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await read(module, transport, result)


@pytest.mark.parametrize("bad", ["foreign", "count", "duplicate_object", "environment"])
async def test_foreign_scope_bad_count_duplicate_object_and_wrong_root_fail_closed(module, transport, frozen, bad):
    entries = await leaves(
        transport, frozen, (0,), tenant=999 if bad == "foreign" else 101, count=2 if bad == "count" else None
    )
    if bad == "duplicate_object":
        entries *= 2
    result = await replace_baseline(
        transport,
        frozen,
        entries,
        metadata_changes={"environment": "another-environment"} if bad == "environment" else {},
    )
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await read(module, transport, result)


async def test_legal_empty_sections_and_tenants_do_not_require_fabricated_pages(module, transport, frozen):
    result = await replace_baseline(transport, frozen, ())
    # A real nonempty conversion plan cannot be attached to an empty baseline.
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await read(module, transport, result)
    metadata = next(row for row in root_records(transport, result, "plan") if row.record_type == "run")
    content = encode_inventory_page(
        run_id=result.run_id,
        section="manifest",
        scope="global",
        tenant_id=None,
        page_index=0,
        records=(metadata,),
        kind="plan",
    )
    plan = await transport.store.aput_canonical(run_id=result.run_id, kind="plan", content=content)
    result = replace(result, plan_ref=plan)
    pages = await read(module, transport, result)
    assert not any(page.kind == "baseline" for page in pages)
    assert result.tenant_ids == (1, 101, 202)


@pytest.mark.parametrize("depth", [62, 63])
async def test_original_depth_boundary_does_not_confuse_manifest_level_indices(module, transport, frozen, depth):
    # Keep the entire actual original membership closure while varying only
    # manifest depth; a lone Root without its Header is no longer a legal graph.
    entries = tuple(
        record_from_values(
            "manifest_entry",
            section=page.section,
            scope=page.scope,
            tenant_id=page.tenant_id,
            page_index=page.page_index,
            record_count=page.record_count,
            descriptor=page.descriptor,
            level=0,
        )
        for page in await read(module, transport, frozen)
        if page.kind == "baseline"
    )
    for level in range(depth):
        count = len(entries)
        content = encode_inventory_page(
            run_id=frozen.run_id,
            section="manifest",
            scope="global",
            tenant_id=None,
            page_index=0,
            records=entries,
            kind="baseline",
        )
        descriptor = await transport.store.aput_canonical(run_id=frozen.run_id, kind="baseline", content=content)
        entry = record_from_values(
            "manifest_entry",
            section="manifest",
            scope="global",
            tenant_id=None,
            page_index=0,
            record_count=count,
            descriptor=descriptor,
            level=level,
        )
        entries = (entry,)
    result = await replace_baseline(transport, frozen, (entry,))
    # iter_manifest_nodes adds one intermediate node below its root.
    if depth + 2 > 64:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await read(module, transport, result)
    else:
        assert await read(module, transport, result)


async def test_late_corruption_and_material_corruption_are_errors_not_partial_success(module, transport, frozen):
    entries = await leaves(transport, frozen, (0, 1))
    result = await replace_baseline(transport, frozen, entries)
    transport.objects[entries[-1].data["descriptor"]["object_key"]] = b"corrupt tail"
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(module, transport, result)
    transport.objects[transport.inputs["schema_ref"]["object_key"]] = b"corrupt material"
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(module, transport, frozen)


async def test_original_transaction_callback_and_cancellation_are_not_swallowed(module, transport, frozen):
    def cancelled():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await read(module, transport, frozen, current=cancelled)
