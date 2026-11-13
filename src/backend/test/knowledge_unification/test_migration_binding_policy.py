"""Binding-only inventories retain SQL conversion and reject weaker frozen graphs."""

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_inventory_codec import (
    decode_inventory_page,
    encode_inventory_page,
    record_from_values,
)
from test.knowledge_unification import test_migration_inventory_application as original
from test.knowledge_unification.test_migration_legacy_index_retention import freeze_empty

resource_native = original.resource_native
native = original.native
complete = original.complete
transport = original.transport
module = original.module

_UNCHANGED = object()


async def leaves(app, frozen, transport):
    return [
        page
        async for page in app.aiter_frozen_pages(
            frozen,
            environment=transport.inputs["environment"],
            backup_ref=transport.inputs["backup_ref"],
            schema_ref=transport.inputs["schema_ref"],
        )
    ]


async def metadata(transport, frozen, kind):
    descriptor = getattr(frozen, f"{kind}_ref")
    content = await transport.store.aload_canonical(descriptor, run_id=frozen.run_id, kind=kind)
    page = decode_inventory_page(
        content,
        run_id=frozen.run_id,
        section="manifest",
        scope="global",
        tenant_id=None,
        page_index=0,
        kind=kind,
    )
    return next(row.data for row in page.records if row.record_type == "run")


async def rewrite_graph(
    module,
    transport,
    frozen,
    original_leaves,
    *,
    baseline_policy=_UNCHANGED,
    plan_policy=_UNCHANGED,
    omit_physical=False,
    empty_physical_kind=None,
):
    """Reissue canonical artifacts so policy rejection cannot be a bad-hash failure."""
    pages = module._Pages(transport.store, frozen.run_id, lambda: None)
    for page in original_leaves:
        if omit_physical and page.section == "physical":
            continue
        pages.entries[page.kind].append(
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
        )
    if empty_physical_kind is not None:
        content = encode_inventory_page(
            run_id=frozen.run_id,
            section="physical",
            scope="tenant",
            tenant_id=101,
            page_index=0,
            records=(),
            kind=empty_physical_kind,
        )
        descriptor = await transport.store.aput_canonical(
            run_id=frozen.run_id, kind=empty_physical_kind, content=content
        )
        pages.entries[empty_physical_kind].append(
            record_from_values(
                "manifest_entry",
                section="physical",
                scope="tenant",
                tenant_id=101,
                page_index=0,
                record_count=0,
                descriptor=descriptor,
                level=0,
            )
        )
    descriptors = {}
    for kind, policy in (("baseline", baseline_policy), ("plan", plan_policy)):
        value = await metadata(transport, frozen, kind)
        if policy is None:
            value.pop("physical_inventory_policy", None)
        elif policy is not _UNCHANGED:
            value["physical_inventory_policy"] = policy
        if kind == "plan":
            value["baseline_ref"] = descriptors["baseline"]
        descriptors[kind] = await pages.manifest(kind, record_from_values("run", **value))
    return replace(frozen, baseline_ref=descriptors["baseline"], plan_ref=descriptors["plan"])


async def freeze(module, complete, transport):
    class UnavailablePhysical:
        async def aiter_facts(self, **kwargs):
            pytest.fail("new inventory must not query physical stores")
            yield  # An async iterator is deliberate; it must never be consumed.

    app = original.application(module, transport, physical_reader=UnavailablePhysical())
    with tenant_execution_scope(1):
        async with AsyncSession(complete.engine) as session, session.begin():
            frozen = await app.arun(session, **transport.inputs)
    return app, frozen


async def test_new_binding_only_graph_has_no_physical_pages_and_completes_native_m3(module, complete, transport):
    app, frozen = await freeze(module, complete, transport)
    pages = await leaves(app, frozen, transport)
    assert pages and not any(page.section == "physical" for page in pages)
    for kind in ("baseline", "plan"):
        assert (await metadata(transport, frozen, kind))["physical_inventory_policy"] == "bindings_only"
    async with complete.engine.connect() as connection:
        before = (await connection.execute(sa.select(original.resources.Knowledge.__table__))).mappings().one()
        binding = before["index_name"], before["collection_name"]

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine, expire_on_commit=False) as session:
            yield session

    conversion = UnificationSQLConversionApplication(artifact_store=transport.store, session_factory=sessions)
    with tenant_execution_scope(1):
        report = await conversion.arun(**transport.inputs)
        replay = await conversion.arun(**transport.inputs)
    assert report.sql_complete and replay.sql_complete
    assert report.tenant_ids == frozen.tenant_ids
    async with complete.engine.connect() as connection:
        after = (await connection.execute(sa.select(original.resources.Knowledge.__table__))).mappings().one()
        assert after["type"] == 3
        assert (after["index_name"], after["collection_name"]) == binding
        assert (
            await connection.execute(sa.select(sa.func.count()).select_from(original.resources.KnowledgeFile))
        ).scalar_one() == 1
        assert (
            await connection.execute(
                sa.select(sa.func.count()).select_from(original.resources.KnowledgeDocumentVersion)
            )
        ).scalar_one() == 1


@pytest.mark.parametrize("changed_root", ["baseline", "plan"])
async def test_root_policy_disagreement_rejects_valid_reissued_artifacts(module, complete, transport, changed_root):
    app, frozen = await freeze(module, complete, transport)
    changed = await rewrite_graph(
        module,
        transport,
        frozen,
        await leaves(app, frozen, transport),
        # Missing means the real legacy policy; the codec intentionally
        # disallows inventing an explicit legacy_physical value on new data.
        **{f"{changed_root}_policy": None},
    )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await leaves(app, changed, transport)
    assert caught.value.kwargs["reason"] == "migration_inventory_frozen_physical_policy_changed"


@pytest.mark.parametrize("kind", ["baseline", "plan"])
async def test_binding_only_policy_rejects_even_an_empty_physical_leaf(module, complete, transport, kind):
    app, frozen = await freeze(module, complete, transport)
    changed = await rewrite_graph(
        module,
        transport,
        frozen,
        await leaves(app, frozen, transport),
        empty_physical_kind=kind,
    )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await leaves(app, changed, transport)
    assert caught.value.kwargs["reason"] == "migration_inventory_unexpected_physical_inventory"


async def test_removing_policy_from_new_roots_cannot_skip_legacy_physical_set_checks(module, complete, transport):
    app, frozen = await freeze(module, complete, transport)
    changed = await rewrite_graph(
        module,
        transport,
        frozen,
        await leaves(app, frozen, transport),
        baseline_policy=None,
        plan_policy=None,
    )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await leaves(app, changed, transport)
    assert caught.value.kwargs["reason"] == "migration_physical_retention_physical_resource_set_changed"


async def test_legacy_roots_without_policy_require_their_complete_original_physical_set(module, complete, transport):
    app, frozen = await freeze_empty(module, complete, transport, legacy=True)
    for kind in ("baseline", "plan"):
        assert "physical_inventory_policy" not in await metadata(transport, frozen, kind)
    original_leaves = await leaves(app, frozen, transport)
    assert {page.kind for page in original_leaves if page.section == "physical"} == {"baseline", "plan"}
    changed = await rewrite_graph(module, transport, frozen, original_leaves, omit_physical=True)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await leaves(app, changed, transport)
    assert caught.value.kwargs["reason"] == "migration_physical_retention_physical_resource_set_changed"
