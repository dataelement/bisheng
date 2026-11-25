"""Full M4 consumption and bounded native transactions for the upgrade flow."""

from datetime import datetime

import pytest
import sqlalchemy as sa

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.app import App
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from test.knowledge_unification.test_migration_references_application import seed_six_and_old_invalid
from test.knowledge_unification.test_migration_registration import (
    complete as complete,
)
from test.knowledge_unification.test_migration_registration import (
    native as native,
)
from test.knowledge_unification.test_migration_registration import (
    no_real_network as no_real_network,
)
from test.knowledge_unification.test_migration_registration import (
    prepared,
    run_registration,
    seed_app,
    seed_versions,
)
from test.knowledge_unification.test_migration_registration import (
    published_input as published_input,
)
from test.knowledge_unification.test_migration_registration import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_migration_registration import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_migration_registration import (
    test_added_zero_reference_workflow_requires_real_registration as seed_registered_addition,
)
from test.knowledge_unification.test_migration_registration import (
    transport as transport,
)
from test.knowledge_unification.test_permission_publication_application import app


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_app}], indirect=True)
async def test_full_consumes_old_registration_proof_without_rebasing(published_input):
    value = published_input
    application = await prepared(value)
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(App.__table__).where(App.id == "register-app").values(update_time=datetime(2026, 11, 20, 10))
        )
    registered = await run_registration(application, apply=True, **value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            before = {
                r.tenant_id: (r.baseline_hash, r.plan_hash, dict(r.checkpoints["backfilling"]))
                for r in (await session.execute(sa.select(Run))).scalars()
            }
    report = await application.arun_references(**value.input, operator_id=7)
    assert report.complete
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            for row in (await session.execute(sa.select(Run))).scalars():
                original = before[row.tenant_id]
                assert (row.baseline_hash, row.plan_hash) == original[:2]
                assert all(row.checkpoints["backfilling"][key] == checkpoint for key, checkpoint in original[2].items())
                assert row.phase == "completed" and row.coverage_epoch
    assert registered["registration_plan_ref"]


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_versions(12)}], indirect=True)
async def test_registration_commits_one_checkpoint_per_bounded_batch(published_input, monkeypatch):
    from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository

    value = published_input
    application = await prepared(value)
    original, counts = KnowledgeUnificationRunRepository.acheckpoint, {}

    async def observe(self, session, **kwargs):
        result = await original(self, session, **kwargs)
        if kwargs["checkpoint_key"] == "references":
            counts[result.tenant_id] = counts.get(result.tenant_id, 0) + 1
        return result

    monkeypatch.setattr(KnowledgeUnificationRunRepository, "acheckpoint", observe)
    result = await run_registration(application, apply=True, **value.input, operator_id=7)
    assert result["registration_complete"]
    assert counts[101] == 1


async def test_full_certifies_real_added_source_and_preserves_its_native_rows(published_input):
    from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet

    value = published_input
    await seed_registered_addition(value, True)
    async with value.sessions() as session, session.begin():
        before = [
            dict(row)
            for row in (
                await session.execute(
                    sa.select(BusinessReferenceSet.__table__).where(BusinessReferenceSet.source_id == "post-freeze")
                )
            ).mappings()
        ]
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete
    async with value.sessions() as session, session.begin():
        after = [
            dict(row)
            for row in (
                await session.execute(
                    sa.select(BusinessReferenceSet.__table__).where(BusinessReferenceSet.source_id == "post-freeze")
                )
            ).mappings()
        ]
        assert after == before
        run = (await session.execute(sa.select(Run).where(Run.tenant_id == 101))).scalar_one()
        assert run.verification_report["reference_coverage"]["proofs"]["workflow_version"]["source_count"] == 1


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_six_and_old_invalid}], indirect=True)
@pytest.mark.parametrize("owner_tenant", [202, 999999])
@pytest.mark.parametrize("completed", [False, True])
async def test_final_tail_refuses_hidden_foreign_or_unknown_tenant_children(
    published_input, monkeypatch, owner_tenant, completed
):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.database.models.assistant import AssistantLink
    from bisheng.knowledge.application.unification_references import ReferenceMigration

    value, original = published_input, ReferenceMigration._verify_tail
    application = app(value)
    epoch = (await application.arun_references(**value.input, operator_id=7)).coverage_epoch if completed else None

    async def add_hidden_child(self, session):
        async with value.sessions() as writer, writer.begin():
            await writer.execute(
                sa.insert(AssistantLink.__table__).values(
                    id=782999, tenant_id=owner_tenant, assistant_id="as-refs", knowledge_id=9000
                )
            )
        return await original(self, session)

    monkeypatch.setattr(ReferenceMigration, "_verify_tail", add_hidden_child)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await application.arun_references(**value.input, operator_id=7, reuse_completed=True)
    assert caught.value.kwargs["reason"] == (
        "unification_inventory_assistant_parent_invalid"
        if owner_tenant == 202
        else "unification_inventory_unregistered_source_or_index_tenant"
    )
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            rows = (await session.execute(sa.select(Run).where(Run.run_id == value.frozen.run_id))).scalars().all()
        assert rows
        if completed:
            assert all(row.coverage_epoch == epoch and row.phase == "completed" for row in rows)
        else:
            assert all(row.coverage_epoch is None and row.phase != "completed" for row in rows)


@pytest.mark.parametrize(
    "damage", ["business_without_clock_change", "index_without_revision_change", "added", "retired"]
)
async def test_final_native_tail_rejects_drift_after_full_verification_before_coverage(
    published_input, monkeypatch, damage
):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.knowledge.application.unification_references import ReferenceMigration
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet

    value = published_input
    if damage == "added":
        await seed_registered_addition(value, True)
    application = app(value)
    original = ReferenceMigration._verify_tail

    async def mutate_then_verify(self, session):
        # The native tail transaction has not read yet. Simulate an unsupported
        # writer after the preceding verification transaction has committed.
        async with value.sessions() as writer, writer.begin():
            if damage == "business_without_clock_change":
                await writer.execute(
                    sa.update(Knowledge.__table__).where(Knowledge.id == 9000).values(name="changed-after-verification")
                )
            elif damage == "index_without_revision_change":
                await writer.execute(
                    sa.update(BusinessReferenceSet.__table__)
                    .where(
                        BusinessReferenceSet.tenant_id == 101,
                        BusinessReferenceSet.source_type == "knowledge",
                        BusinessReferenceSet.source_id == "9000",
                        BusinessReferenceSet.source_version == "current",
                    )
                    .values(digest="0" * 64)
                )
            elif damage == "added":
                await writer.execute(
                    sa.update(FlowVersion.__table__)
                    .where(FlowVersion.flow_id == "post-freeze")
                    .values(data={"tampered": True})
                )
            else:
                # This previously empty version root is part of the full root
                # census, even though no source receipt exists for it.
                await writer.execute(sa.update(Flow.__table__).where(Flow.id == "zero-version").values(is_delete=1))
        await original(self, session)

    monkeypatch.setattr(ReferenceMigration, "_verify_tail", mutate_then_verify)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await application.arun_references(**value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            rows = (await session.execute(sa.select(Run).where(Run.run_id == value.frozen.run_id))).scalars().all()
        assert rows and all(row.coverage_epoch is None and row.phase != "completed" for row in rows)


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_versions(12)}], indirect=True)
async def test_whole_batch_rolls_back_and_unknown_commit_resumes_without_rewrite(published_input, monkeypatch):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    value = published_input
    application = await prepared(value)
    original, called = ReferenceBackfillRepository.awrite_registered_source, []

    async def fail_after_second(self, session, **kwargs):
        result = await original(self, session, **kwargs)
        called.append(kwargs["source_key"])
        if len(called) == 2:
            raise KnowledgeOperationPlanConflictError(reason="in_batch_failure")
        return result

    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", fail_after_second)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run_registration(application, apply=True, **value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        assert not (
            await session.execute(sa.select(BusinessReferenceSet.id).where(BusinessReferenceSet.tenant_id == 101))
        ).all()
        run = (await session.execute(sa.select(Run).where(Run.tenant_id == 101))).scalar_one()
        assert run.checkpoints.get("backfilling", {}).get("references") is None
    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", original)
    assert (await run_registration(application, apply=True, **value.input, operator_id=7))["registration_complete"]


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_versions(12)}], indirect=True)
async def test_batch_commit_ack_unknown_resumes_complete_effect_without_duplicate_ids(published_input, monkeypatch):
    from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
    from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    value, lost = published_input, []
    application = await prepared(value)
    original = KnowledgeUnificationRunRepository.acheckpoint

    def lose_ack(session):
        raise OSError("commit acknowledged too late")

    async def intercept(self, session, **kwargs):
        row = await original(self, session, **kwargs)
        if kwargs["checkpoint_key"] == "references" and row.tenant_id == 101 and not lost:
            lost.append(True)
            sa.event.listen(session.sync_session, "after_commit", lose_ack, once=True)
        return row

    monkeypatch.setattr(KnowledgeUnificationRunRepository, "acheckpoint", intercept)
    with pytest.raises(OSError):
        await run_registration(application, apply=True, **value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        before = tuple(
            (await session.execute(sa.select(BusinessReferenceSet.id).order_by(BusinessReferenceSet.id))).scalars()
        )
        assert before
        row = (await session.execute(sa.select(Run).where(Run.tenant_id == 101))).scalar_one()
        assert row.checkpoints["backfilling"]["references"]["processed_count"] == 13

    async def no_rewrite(*args, **kwargs):
        raise AssertionError("committed batch must not be written twice")

    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", no_rewrite)
    assert (await run_registration(application, apply=True, **value.input, operator_id=7))["registration_complete"]
    async with value.sessions() as session, session.begin():
        after = tuple(
            (await session.execute(sa.select(BusinessReferenceSet.id).order_by(BusinessReferenceSet.id))).scalars()
        )
        assert before == after


async def seed_budget_sources(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.database.models.flow_version import FlowVersion
    from test.knowledge_unification.test_migration_source_inventory import graph

    async with AsyncSession(database.engine) as session, session.begin():
        for ordinal, count in enumerate((1, 7, 1)):
            session.add(
                FlowVersion(
                    id=640001 + ordinal,
                    tenant_id=101,
                    flow_id="zero-version",
                    name="budget",
                    flow_type=10,
                    is_delete=0,
                    is_current=int(ordinal == 0),
                    data=graph(*([11] * count)),
                )
            )


async def seed_large_atomic_source(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.database.models.flow_version import FlowVersion
    from test.knowledge_unification.test_migration_source_inventory import graph

    data = graph(*([11] * 5120))
    data["large_source_test_payload"] = "x" * (5 * 1024 * 1024)
    async with AsyncSession(database.engine) as session, session.begin():
        session.add(
            FlowVersion(
                id=649999,
                tenant_id=101,
                flow_id="zero-version",
                name="large atomic source",
                flow_type=10,
                is_delete=0,
                is_current=1,
                data=data,
            )
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_large_atomic_source}], indirect=True)
@pytest.mark.parametrize("interrupt", [False, True])
async def test_large_source_exceeds_batch_budgets_but_remains_atomic_and_reports_actual_peak(
    published_input, monkeypatch, interrupt
):
    import json
    import resource
    import sys
    import time
    import tracemalloc
    from dataclasses import asdict

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.application.unification_references import ReferenceMigration
    from bisheng.knowledge.domain.services.unification_fingerprints import canonical
    from bisheng.resource_reference.application.backfill import RegisteredReferenceBackfill
    from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    value = published_input
    application = await prepared(value)
    original_write = ReferenceBackfillRepository.awrite_registered_source
    original_prepare = RegisteredReferenceBackfill.aprepare_registered_batch
    original_tail = ReferenceMigration._verify_tail
    interrupted, batches, costs = [], [], []

    async def prepare(self, session, **kwargs):
        keys = tuple(item["source_key"] for item in kwargs["items"])
        if any(key.source_version == "649999" for key in keys):
            batches.append(keys)
            assert len(keys) == 1
        return await original_prepare(self, session, **kwargs)

    async def write(self, session, **kwargs):
        result = await original_write(self, session, **kwargs)
        if interrupt and kwargs["source_key"].source_version == "649999" and not interrupted:
            interrupted.append(True)
            raise KnowledgeOperationPlanConflictError(reason="large_source_after_native_write")
        return result

    async def tail(self, session):
        for key, cost in self._tail_costs.items():
            if key.source_version == "649999":
                costs.append(cost)
                assert cost[0] == 5120 and cost[1] > 5 * 1024 * 1024
                with tenant_execution_scope(key.tenant_id):
                    business = (await self.sources.repository.aload_reference_sources(session, source_keys=(key,)))[key]
                    index = (await self.backfill.repository.aload_raw_snapshots(session, source_keys=(key,)))[key]
                root, version, children = business
                expected_bytes = len(
                    canonical(
                        {
                            "root": asdict(root),
                            "version": asdict(version) if version else None,
                            "children": tuple(asdict(child) for child in children),
                        }
                    )
                ) + len(canonical(index))
                assert cost[1] == expected_bytes  # Includes every full index row, not only its hash.
                assert all(len(batch) == 1 for batch in self._tail_batches(tuple(self._tail_sources)) if key in batch)
        return await original_tail(self, session)

    monkeypatch.setattr(RegisteredReferenceBackfill, "aprepare_registered_batch", prepare)
    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", write)
    monkeypatch.setattr(ReferenceMigration, "_verify_tail", tail)
    started = time.monotonic()
    tracemalloc.start()
    try:
        if interrupt:
            with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
                await application.arun_references(**value.input, operator_id=7, reuse_completed=True)
            assert caught.value.kwargs["reason"] == "large_source_after_native_write"
            async with value.sessions() as session, session.begin():
                for model in (BusinessReferenceSet, BusinessResourceReference):
                    assert not (
                        await session.execute(
                            sa.select(model.id).where(model.tenant_id == 101, model.source_id == "zero-version")
                        )
                    ).all()
                with bypass_tenant_filter():
                    assert not (await session.execute(sa.select(Run.id).where(Run.coverage_epoch.is_not(None)))).all()
        result = await application.arun_references(**value.input, operator_id=7, reuse_completed=True)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.complete and batches and costs
    async with value.sessions() as session, session.begin():
        count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(BusinessResourceReference.__table__)
                .where(
                    BusinessResourceReference.tenant_id == 101, BusinessResourceReference.source_id == "zero-version"
                )
            )
        ).scalar_one()
        assert count == 5120
        run = (await session.execute(sa.select(Run).where(Run.tenant_id == 101))).scalar_one()
        proof = run.verification_report["reference_coverage"]["proofs"]["workflow_version"]
        assert proof["source_count"] == 1 and proof["reference_count"] == 5120
    assert max(len(content) for content in value.artifacts.objects.values()) <= 16 * 1024 * 1024
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        json.dumps(
            {
                "large_source_references": 5120,
                "large_source_padding_bytes": 5 * 1024 * 1024,
                "interrupt_and_resume": interrupt,
                "elapsed_seconds": time.monotonic() - started,
                "python_allocations_peak_bytes": peak,
                "process_lifetime_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
                "tail_snapshot_bytes": costs[-1][1],
            }
        )
    )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_budget_sources}], indirect=True)
@pytest.mark.parametrize("budget", ["references", "bytes"])
async def test_source_details_and_byte_budget_isolate_oversized_sources(published_input, monkeypatch, budget):
    from bisheng.knowledge.application.unification_references import ReferenceMigration
    from bisheng.resource_reference.application.backfill import RegisteredReferenceBackfill

    value = published_input
    application = await prepared(value)
    monkeypatch.setattr(ReferenceMigration, "source_reference_limit", 4)
    if budget == "bytes":
        monkeypatch.setattr(ReferenceMigration, "source_byte_limit", 1)
    batches, original = [], RegisteredReferenceBackfill.aprepare_registered_batch

    async def observe(self, session, **kwargs):
        batches.append(tuple(len(item["rows"]) for item in kwargs["items"]))
        return await original(self, session, **kwargs)

    monkeypatch.setattr(RegisteredReferenceBackfill, "aprepare_registered_batch", observe)
    assert (await run_registration(application, apply=True, **value.input, operator_id=7))["registration_complete"]
    assert any(batch == (7,) for batch in batches)
    assert all(sum(batch) <= 4 or len(batch) == 1 for batch in batches)
    if budget == "bytes":
        assert all(len(batch) == 1 for batch in batches)


def seed_distinct_roots(count):
    async def seed(database):
        from sqlmodel.ext.asyncio.session import AsyncSession

        from bisheng.database.models.flow import Flow
        from bisheng.database.models.flow_version import FlowVersion

        async with AsyncSession(database.engine) as session, session.begin():
            row = (
                (await session.execute(sa.select(*Flow.__table__.c).where(Flow.id == "zero-version"))).mappings().one()
            )
            for ordinal in range(count):
                identifier = f"scale-distinct-{ordinal}"
                await session.execute(sa.insert(Flow.__table__).values({**dict(row), "id": identifier}))
                session.add(
                    FlowVersion(
                        id=810000 + ordinal,
                        tenant_id=101,
                        flow_id=identifier,
                        name=str(ordinal),
                        flow_type=10,
                        is_delete=0,
                        is_current=1,
                        data={"nodes": [], "edges": []},
                    )
                )

    return seed


@pytest.mark.parametrize(
    "published_input",
    [
        pytest.param({"reference_seed": seed(n)}, id=f"{name}-{n}")
        for name, seed in (("versions", seed_versions), ("roots", seed_distinct_roots))
        for n in (12, 24)
    ],
    indirect=True,
)
@pytest.mark.parametrize("scope", ["registration", "full_reference_with_tail"])
async def test_native_scale_counts_batch_sql_and_semantic_collection_cost(published_input, scope):
    import json
    import time
    import tracemalloc

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.application.unification_reference_plan import UnificationReferencePlanReader
    from bisheng.knowledge.application.unification_reference_reconciliation import collect_semantics

    value = published_input
    application = await prepared(value)
    counts = {"sql": 0, "transactions": 0}

    def sql(*args):
        counts["sql"] += 1

    def begin(*args):
        counts["transactions"] += 1

    reader = UnificationReferencePlanReader(inventory=application.reader, artifact_store=application.store)
    plan = await reader.aprepare(value.frozen, environment=value.input["environment"], backup_ref=None, schema_ref=None)
    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", sql)
    sa.event.listen(value.database.engine.sync_engine, "begin", begin)
    tracemalloc.start()
    started = time.monotonic()
    try:
        for tenant in value.frozen.tenant_ids:
            keys = tuple(item.header.source_key for item in plan.sources if item.header.source_key.tenant_id == tenant)
            if keys:
                with tenant_execution_scope(tenant):
                    async with value.sessions() as session, session.begin():
                        await collect_semantics(session, source_keys=keys)
        semantic_sql = counts["sql"]
        if scope == "registration":
            result = await run_registration(application, apply=True, **value.input, operator_id=7)
        else:
            result = await application.arun_references(**value.input, operator_id=7, reuse_completed=True)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", sql)
        sa.event.remove(value.database.engine.sync_engine, "begin", begin)
    assert result["registration_complete"] if scope == "registration" else result.complete
    assert counts["sql"] > semantic_sql and counts["transactions"] > 0
    print(
        json.dumps(
            {
                "reference_native_scale": len(plan.sources),
                "root_count": len(plan.roots),
                "execution_scope": scope,
                "semantic_collection_sql": semantic_sql,
                **counts,
                "elapsed_seconds": time.monotonic() - started,
                "peak_bytes": peak,
            }
        )
    )
