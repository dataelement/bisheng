"""Freeze/convert/resume keep exact rootless history and reject scope drift."""

import json
import time
import tracemalloc
from collections import Counter
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_inventory_codec import record_from_values
from bisheng.knowledge.application.unification_structural_retention import rootless_file_retention
from bisheng.knowledge.domain.services.model_reference_extractor import legacy_knowledge_model_version
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from test.knowledge_unification import test_migration_structural_retention as original

resource_native, native, complete = original.resource_native, original.native, original.complete
raw_resource_native = original.raw_resource_native
transport, module = original.transport, original.module
resources = original.resources
published_input = original.published_input


async def seed_retained_history(database):
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.update(resources.Knowledge).where(resources.Knowledge.id == 9000).values(model="bge-large-zh")
        )
    await database.insert(resources.KnowledgeFile, [resources.file(10, knowledge_id=404, file_level_path="", level=0)])


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_retained_history}], indirect=True)
async def test_retained_history_full_m2_m3_m4_and_coverage_resume(published_input):
    from bisheng.knowledge.application.unification_coverage import production_coverage_factory

    value = published_input
    app = original.reference_tests.app(value)
    first = await app.arun_references(**value.input, operator_id=7)
    assert first.complete and await app.arun_references(**value.input, operator_id=7) == first
    async with value.sessions() as session, session.begin():
        assert (
            await production_coverage_factory(session).arequire_global_ready()
        ).verified_tenant_ids == value.frozen.tenant_ids
        headers = (
            (
                await session.execute(
                    sa.select(BusinessReferenceSet.__table__).where(
                        BusinessReferenceSet.source_type == "knowledge",
                        BusinessReferenceSet.source_id == "9000",
                        BusinessReferenceSet.record_kind == "source",
                    )
                )
            )
            .mappings()
            .all()
        )
        assert len(headers) == 1 and headers[0]["extractor_version"] == legacy_knowledge_model_version("bge-large-zh")
    assert not any(obj == "knowledge_file:10" for _, _, obj in value.store.tuples)


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_retained_history}], indirect=True)
@pytest.mark.parametrize("kind", ["knowledge_file", "folder"])
async def test_late_graph_drift_blocks_coverage_and_completed_resume(published_input, monkeypatch, kind):
    from bisheng.knowledge.application.unification_references import ReferenceMigration
    from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun

    value = published_input
    original_tenant = ReferenceMigration._tenant
    edge = (f"{kind}:10#visible", "visible", "app:unexpected")

    async def late(self, tenant, **kwargs):
        result = await original_tenant(self, tenant, **kwargs)
        if kwargs.get("verify_only") and tenant == self.frozen.tenant_ids[-1]:
            value.store.tuples.add(edge)
        return result

    monkeypatch.setattr(ReferenceMigration, "_tenant", late)
    with pytest.raises(BaseErrorCode):
        await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)
    async with value.database.engine.connect() as connection:
        phases = (
            (
                await connection.execute(
                    sa.select(KnowledgeUnificationRun.phase).where(
                        KnowledgeUnificationRun.run_id == value.frozen.run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "completed" not in phases


@pytest.mark.parametrize("count", [1, 200, 400])
async def test_native_rootless_m2_conversion_and_resume_are_exact(module, complete, transport, count):
    values = [resources.file(ident, knowledge_id=404, file_level_path="", level=0) for ident in range(10, 10 + count)]
    await complete.insert(resources.KnowledgeFile, values)
    metrics = Counter()

    def statement(_conn, _cursor, sql, _params, _context, _many):
        metrics[sql.lstrip().partition(" ")[0].upper()] += 1

    def transaction(_conn):
        metrics["TRANSACTIONS"] += 1

    sa.event.listen(complete.engine.sync_engine, "before_cursor_execute", statement)
    sa.event.listen(complete.engine.sync_engine, "begin", transaction)
    transport.requests.clear()
    started = time.perf_counter()
    tracemalloc.start()
    inventory = original.original.application(module, transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        await inventory.arun(session, **transport.inputs)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine, expire_on_commit=False) as session:
            yield session

    app = UnificationSQLConversionApplication(
        artifact_store=transport.store, session_factory=sessions, structural_reader_factory=transport.reader_factory
    )
    with tenant_execution_scope(1):
        assert (await app.arun(**transport.inputs)).sql_complete
        assert (await app.arun(**transport.inputs)).sql_complete
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    sa.event.remove(complete.engine.sync_engine, "before_cursor_execute", statement)
    sa.event.remove(complete.engine.sync_engine, "begin", transaction)
    print(
        json.dumps(
            {
                "rootless_rows": count,
                "sql": dict(metrics),
                "remote_calls": len(transport.requests),
                "peak_bytes": peak,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
        )
    )
    async with complete.engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    sa.select(resources.KnowledgeFile.__table__)
                    .where(resources.KnowledgeFile.knowledge_id == 404)
                    .order_by(resources.KnowledgeFile.id)
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == count
        for row, expected in zip(rows, values, strict=True):
            assert all(row[key] == value for key, value in expected.items())


@pytest.mark.parametrize("change", ["parent", "incoming", "mode", "path", "proof"])
def test_frozen_rootless_proof_is_closed(change):
    item = original.file().data | {"file_level_path": "", "level": 0}
    baseline = record_from_values("rootless_file", **item)
    proof = rootless_file_retention(item)
    rows = [("control", baseline)]
    if change == "parent":
        rows.append(("resources", original.root()))
    elif change == "incoming":
        rows.append(
            (
                "fga",
                record_from_values("fga_tuple", user="knowledge_file:2#visible", relation="visible", object="app:1"),
            )
        )
    elif change == "mode":
        rows.append(
            (
                "permission",
                record_from_values(
                    "resource_mode",
                    id=2,
                    tenant_id=101,
                    resource_type="knowledge_file",
                    resource_id="2",
                    mode="CUSTOM",
                    parent_type=None,
                    parent_id=None,
                    version=1,
                    projection_state="CURRENT",
                    operation_id=None,
                ),
            )
        )
    elif change == "path":
        rows[0] = ("control", record_from_values("rootless_file", **(item | {"file_level_path": "/10"})))
    with pytest.raises(BaseErrorCode):
        original.validate(rows, () if change == "proof" else (proof,))
