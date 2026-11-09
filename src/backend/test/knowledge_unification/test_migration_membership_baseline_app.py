"""Actual M2 and M3 paths refuse incomplete, hash-consistent Member graphs.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
"""

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_inventory_codec import (
    decode_inventory_page,
    encode_inventory_page,
    iter_manifest_nodes,
    record_from_values,
)
from test.knowledge_unification import test_migration_frozen_plan_reader as graph
from test.knowledge_unification import test_migration_inventory_application as original

resource_native = original.resource_native
native = original.native
module = original.module
complete = original.complete
transport = original.transport


@pytest.mark.parametrize("missing", ["space_membership_header", "creator", "resource_conversion"])
async def test_actual_fresh_inventory_cannot_freeze_an_incomplete_producer(module, complete, transport, missing):
    app = original.application(module, transport)
    actual = app.preflight.aiter_tenant

    async def incomplete(*args, **kwargs):
        async for section, record in actual(*args, **kwargs):
            if getattr(record, "record_type", None) != missing:
                yield section, record

    app.preflight.aiter_tenant = incomplete
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
            await app.arun(session, **transport.inputs)
    assert "membership_inventory_" in failure.value.kwargs["reason"]
    assert await original.count_runs(complete.engine) == 0


@pytest.mark.parametrize("missing", ["space_membership_header", "resource_conversion"])
async def test_actual_frozen_replay_and_m3_admission_reject_incomplete_graph_before_writes(
    module, complete, transport, missing
):
    # Create an actual valid current freeze, then reconstruct the correctly
    # hashed historical artifact and ledger binding in this fixture only. The
    # new fresh artifact gate must not be bypassed in production to seed it.
    app = original.application(module, transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        frozen = await app.arun(session, **transport.inputs)
    pages = [page async for page in app.aiter_frozen_pages(frozen, **graph.arguments(transport))]
    refs = {}
    for kind in ("baseline", "plan"):
        entries = []
        for page in pages:
            if page.kind != kind:
                continue
            descriptor, count = page.descriptor, page.record_count
            if page.section == ("control" if missing == "space_membership_header" else "conversion"):
                decoded = decode_inventory_page(
                    page.content,
                    run_id=frozen.run_id,
                    section=page.section,
                    scope=page.scope,
                    tenant_id=page.tenant_id,
                    page_index=page.page_index,
                    kind=kind,
                )
                records = tuple(row for row in decoded.records if row.record_type != missing)
                count = len(records)
                content = encode_inventory_page(
                    run_id=frozen.run_id,
                    section=page.section,
                    scope=page.scope,
                    tenant_id=page.tenant_id,
                    page_index=page.page_index,
                    records=records,
                    kind=kind,
                )
                descriptor = await transport.store.aput_canonical(run_id=frozen.run_id, kind=kind, content=content)
            entries.append(
                record_from_values(
                    "manifest_entry",
                    section=page.section,
                    scope=page.scope,
                    tenant_id=page.tenant_id,
                    page_index=page.page_index,
                    record_count=count,
                    descriptor=descriptor,
                    level=0,
                )
            )
        metadata = next(row for row in graph.root_records(transport, frozen, kind) if row.record_type == "run")
        if kind == "plan":
            metadata = record_from_values("run", **(metadata.data | {"baseline_ref": refs["baseline"]}))
        for node in iter_manifest_nodes(run_id=frozen.run_id, kind=kind, entries=iter(entries), metadata=metadata):
            descriptor = await transport.store.aput_canonical(run_id=frozen.run_id, kind=kind, content=node.content)
            if node.is_root:
                refs[kind] = descriptor
    frozen = replace(frozen, baseline_ref=refs["baseline"], plan_ref=refs["plan"])
    async with complete.engine.begin() as connection:
        await connection.execute(
            sa.update(original.KnowledgeUnificationRun.__table__)
            .where(original.KnowledgeUnificationRun.run_id == frozen.run_id)
            .values(
                baseline_ref=frozen.baseline_ref,
                plan_ref=frozen.plan_ref,
                baseline_hash=frozen.baseline_ref["sha256"],
                plan_hash=frozen.plan_ref["sha256"],
            )
        )
    assert frozen.baseline_ref["sha256"] and frozen.plan_ref["sha256"]
    complete.queries.clear()
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as replay:
            await original.application(module, transport).arun(session, **transport.inputs)
    assert "membership_inventory_" in replay.value.kwargs["reason"]

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine) as session:
            yield session

    converter = UnificationSQLConversionApplication(artifact_store=transport.store, session_factory=sessions)
    with pytest.raises(KnowledgeOperationPlanConflictError) as convert:
        await converter.arun(**transport.inputs)
    assert "membership_inventory_" in convert.value.kwargs["reason"]
    assert not [sql for sql, _ in complete.queries if sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
