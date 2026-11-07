"""Real M2 artifacts -> typed commands -> Domain -> native SQL transactions."""

import importlib
from collections import Counter
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from test.knowledge_unification import test_migration_inventory_application as m2

resource_native = m2.resource_native
native = m2.native
complete = m2.complete
transport = m2.transport


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_conversion")


@pytest.fixture
async def produced(complete, transport, request):
    count = getattr(request, "param", 5)
    if count > 1:
        await complete.insert(m2.resources.KnowledgeFile, [m2.resources.file(i) for i in range(2, count + 1)])

    @sa.event.listens_for(complete.engine.sync_engine, "begin")
    def real_parent(connection):
        connection.exec_driver_sql("BEGIN")

    app = m2.application(importlib.import_module("bisheng.knowledge.application.unification_inventory"), transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        frozen = await app.arun(session, **transport.inputs)
    return complete, transport, frozen, count


class Sessions:
    def __init__(self, engine, *, fail_at=None, after=False):
        self.engine, self.fail_at, self.after = engine, fail_at, after
        self.opened, self.commits = [], 0

    @asynccontextmanager
    async def __call__(self):
        owner = self

        class Native(AsyncSession):
            async def commit(self):
                hit = False
                if get_current_tenant_id() == 101:
                    owner.commits += 1
                    hit = owner.commits == owner.fail_at
                if hit and not owner.after:
                    raise OSError("native commit transport interrupted before acknowledgement")
                await super().commit()
                if hit:
                    raise OSError("native commit transport lost its acknowledgement")

        async with Native(self.engine) as session:
            self.opened.append(session)
            yield session


def application(module, produced, sessions=None):
    database, transport, _, _ = produced
    sessions = sessions or Sessions(database.engine)
    return module.UnificationSQLConversionApplication(
        artifact_store=transport.store, session_factory=sessions
    ), sessions


def arguments(produced):
    return produced[1].inputs


async def snapshot(database):
    async with database.engine.connect() as connection:
        return {
            model.__tablename__: tuple(
                dict(row)
                for row in (await connection.execute(sa.select(model.__table__).order_by(model.id))).mappings()
            )
            for model in (
                m2.resources.Knowledge,
                m2.resources.KnowledgeFile,
                m2.resources.KnowledgeDocument,
                m2.resources.KnowledgeDocumentVersion,
                Run,
            )
        }


async def test_actual_m2_to_domain_sql_completes_only_sql_and_keeps_all_original_files(module, produced):
    database, _, frozen, count = produced
    before = await snapshot(database)
    app, sessions = application(module, produced)
    report = await app.arun(**arguments(produced))
    after = await snapshot(database)
    assert report.sql_complete and report.tenant_ids == frozen.tenant_ids == (1, 101, 202)
    assert report.baseline_hash == frozen.baseline_ref["sha256"] and report.plan_hash == frozen.plan_ref["sha256"]
    assert tuple(row.tenant_id for row in report.tenant_progress) == (1, 101, 202)
    assert {row.tenant_id: row.command_count for row in report.tenant_progress} == {1: 0, 101: count + 1, 202: 0}
    assert all(
        row.progress.complete and row.progress.processed_count == row.command_count for row in report.tenant_progress
    )
    assert len(after["knowledge_document"]) == len(after["knowledge_document_version"]) == count
    assert after["knowledgefile"] == before["knowledgefile"]
    assert after["knowledge"][0]["type"] == 3
    assert all(row["phase"] == "converting" and row["source_coverage"] == {} for row in after[Run.__tablename__])
    assert len({id(session) for session in sessions.opened}) == len(sessions.opened)
    assert all(not session.in_transaction() for session in sessions.opened)
    # Already-complete SQL recovery reads actual allocated IDs, never inserts a
    # second V1 or reruns M2 inventory against transformed business data.
    repeated, _ = application(module, produced)
    assert await repeated.arun(**arguments(produced)) == report
    assert await snapshot(database) == after


@pytest.mark.parametrize("bad", ["tail", "material", "new_tenant", "future_phase", "wrong_refs"])
async def test_complete_preflight_rejects_bad_tail_or_universe_before_any_business_dml(module, produced, bad):
    database, transport, _, _ = produced
    if bad == "tail":
        key = next(
            key for key, value in reversed(tuple(transport.objects.items())) if b'"section":"conversion"' in value
        )
        transport.objects[key] = b"corrupt frozen tail"
    elif bad == "material":
        transport.objects[transport.inputs["schema_ref"]["object_key"]] = b"corrupt schema evidence"
    else:
        async with database.engine.begin() as connection:
            if bad == "new_tenant":
                await connection.execute(
                    m2.resources.Tenant.__table__.insert(), {"id": 303, "tenant_code": "new", "tenant_name": "new"}
                )
            elif bad == "future_phase":
                await connection.execute(
                    sa.update(Run.__table__).where(Run.tenant_id == 202).values(phase="backfilling")
                )
            else:
                await connection.execute(
                    sa.update(Run.__table__).where(Run.tenant_id == 202).values(plan_hash="f" * 64)
                )
    before = await snapshot(database)
    app, _ = application(module, produced)
    with pytest.raises((KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError)):
        await app.arun(**arguments(produced))
    assert await snapshot(database) == before


@pytest.mark.parametrize("after", [False, True])
async def test_unknown_commit_stops_then_fresh_app_recovers_from_actual_sql_evidence(module, produced, after):
    database, _, _, count = produced
    before = await snapshot(database)
    app, _ = application(module, produced, Sessions(database.engine, fail_at=1, after=after))
    with pytest.raises(ReferenceCoverageNotReadyError) as caught:
        await app.arun(**arguments(produced))
    assert caught.value.kwargs["sql_conversion_report"]["commit_outcome"] == "unknown"
    interrupted = await snapshot(database)
    assert len(interrupted["knowledge_document"]) == (count if after else 0)
    assert interrupted["knowledgefile"] == before["knowledgefile"]
    resumed, _ = application(module, produced)
    report = await resumed.arun(**arguments(produced))
    after_rows = await snapshot(database)
    assert report.sql_complete and len(after_rows["knowledge_document"]) == count
    assert after_rows["knowledgefile"] == before["knowledgefile"]
    if after:
        assert after_rows["knowledge_document"] == interrupted["knowledge_document"]
        assert after_rows["knowledge_document_version"] == interrupted["knowledge_document_version"]


@pytest.mark.parametrize("produced", [401], indirect=True)
async def test_committed_partial_page_and_mixed_tenant_phases_resume_without_replaying_prefix(module, produced):
    database, _, _, count = produced
    broken, _ = application(module, produced, Sessions(database.engine, fail_at=2))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await broken.arun(**arguments(produced))
    interrupted = await snapshot(database)
    assert len(interrupted["knowledge_document"]) == 199
    assert {row["phase"] for row in interrupted[Run.__tablename__]} == {"converting", "baseline_frozen"}
    saved = {row["id"]: row for row in interrupted["knowledge_document_version"]}
    resumed, _ = application(module, produced)
    assert (await resumed.arun(**arguments(produced))).sql_complete
    final = await snapshot(database)
    assert len(final["knowledge_document_version"]) == count
    assert {row["id"]: row for row in final["knowledge_document_version"] if row["id"] in saved} == saved


@pytest.mark.parametrize("produced", [401, 10001], indirect=True)
async def test_native_scale_reads_frozen_graph_once_then_pages_once_and_uses_bounded_fresh_transactions(
    module, produced, monkeypatch
):
    database, transport, _, count = produced
    gets = Counter()
    actual = transport.store.storage.get_object

    async def get(**kwargs):
        gets[kwargs["object_name"]] += 1
        return await actual(**kwargs)

    monkeypatch.setattr(transport.store.storage, "get_object", get)
    before = await snapshot(database)
    database.queries.clear()
    app, sessions = application(module, produced)
    result = await app.arun(**arguments(produced))
    assert result.sql_complete and len((await snapshot(database))["knowledge_document"]) == count
    assert max(gets.values()) <= 2  # No per-batch whole-manifest scan.
    assert sum(gets.values()) <= len(transport.objects) * 2
    assert len(database.queries) < ((count + 198) // 199 + 3) * 70
    assert len(sessions.opened) > (count + 198) // 199
    assert len({id(session) for session in sessions.opened}) == len(sessions.opened)
    assert (await snapshot(database))["knowledgefile"] == before["knowledgefile"]
    print(
        f"M2-to-SQL files={count} SELECT={len(database.queries)} artifact_GET={sum(gets.values())} "
        f"objects={len(transport.objects)} sessions={len(sessions.opened)}"
    )
