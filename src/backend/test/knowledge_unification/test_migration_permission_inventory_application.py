"""The original formal entry validates namespace before freeze or M3 writes."""

import importlib
import json
from collections import Counter
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.knowledge.application.unification_inventory_codec import record_from_values
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification import test_migration_inventory_application as original

resource_native, native, complete, transport, module = (
    original.resource_native,
    original.native,
    original.complete,
    original.transport,
    original.module,
)


async def frozen_records(app, frozen, transport):
    records = []
    async for page in app.aiter_frozen_pages(
        frozen, **{key: transport.inputs[key] for key in ("environment", "backup_ref", "schema_ref")}
    ):
        records.extend((page.kind, page.section, row) for row in json.loads(page.content)["records"][1:])
    return records


async def test_real_entry_flushes_global_catalog_before_reader_and_compiles_twice_per_graph(
    module, complete, transport, monkeypatch
):
    counters, entries = Counter(), []
    for name in ("derive_permission_models", "_namespace_applicability"):
        actual = getattr(plans, name)

        def tracked(*args, _actual=actual, _name=name, **kwargs):
            counters[_name] += 1
            return _actual(*args, **kwargs)

        monkeypatch.setattr(plans, name, tracked)
    factory = transport.reader_factory

    @asynccontextmanager
    async def observed(catalog):
        pages = [json.loads(content) for content in transport.objects.values()]
        assert any(page["kind"] == "baseline" and page["records"][0]["section"] == "catalog" for page in pages)
        assert any(page["kind"] == "plan" and page["records"][0]["section"] == "permission_namespace" for page in pages)
        entries.append(True)
        async with factory(catalog) as reader:
            yield reader

    app = original.application(module, transport, sharing_reader_factory=observed)
    async with AsyncSession(complete.engine) as session, session.begin():
        frozen = await app.arun(session, **transport.inputs)
    assert entries == [True]
    assert counters == {"derive_permission_models": 2, "_namespace_applicability": 2}
    counters.clear()
    complete.queries.clear()
    records = await frozen_records(app, frozen, transport)
    assert complete.queries == []
    assert counters == {"derive_permission_models": 2, "_namespace_applicability": 2}
    targets = [row for kind, section, row in records if row["record_type"] == "namespace_target_mode"]
    assert len(targets) == 1 and targets[0]["resource_type"] == "knowledge_space"
    async with complete.engine.connect() as connection:
        assert (await connection.execute(sa.select(original.resources.Knowledge.type))).scalar_one() == 0
        assert (
            await connection.execute(sa.select(original.permission.ResourcePermissionMode.resource_type))
        ).scalar_one() == "knowledge_library"


async def test_missing_actual_original_library_mode_blocks_formal_freeze(module, complete, transport):
    async with complete.engine.begin() as connection:
        await connection.execute(sa.delete(original.permission.ResourcePermissionMode))
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises((KnowledgeOperationPlanConflictError, PermissionMigrationBlockedError)):
            await original.application(module, transport).arun(session, **transport.inputs)
    assert await original.count_runs(complete.engine) == 0


@pytest.mark.parametrize("defect", ["target", "header", "matrix"])
async def test_validly_rehashed_wrong_generated_plan_never_reaches_ledger_freeze(
    module, complete, transport, monkeypatch, defect
):
    preflight = importlib.import_module("bisheng.knowledge.application.unification_preflight")
    if defect == "matrix":
        actual = module.catalog_namespace_records

        def corrupted(planner):
            for record in actual(planner):
                if record.record_type != "namespace_applicability":
                    yield record

        monkeypatch.setattr(module, "catalog_namespace_records", corrupted)
    else:
        actual = preflight.namespace_plan_records

        def corrupted(plan):
            for section, record in actual(plan):
                if defect == "target" and record.record_type == "namespace_target_mode":
                    record = record_from_values(
                        record.record_type, **(record.data | {"resource_type": "knowledge_library"})
                    )
                if defect == "header" and record.record_type == "permission_plan":
                    record = record_from_values(record.record_type, **(record.data | {"after_digest": "0" * 64}))
                yield section, record

        monkeypatch.setattr(preflight, "namespace_plan_records", corrupted)
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises((KnowledgeOperationPlanConflictError, PermissionMigrationBlockedError)):
            await original.application(module, transport).arun(session, **transport.inputs)
    assert await original.count_runs(complete.engine) == 0
    async with complete.engine.connect() as connection:
        assert (await connection.execute(sa.select(original.resources.Knowledge.type))).scalar_one() == 0
