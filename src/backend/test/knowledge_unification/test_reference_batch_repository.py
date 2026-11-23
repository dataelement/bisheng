"""Bounded source projections preserve original facts and explicit lock order."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_reference_plan import UnificationReferencePlanReader
from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository
from bisheng.knowledge.domain.repositories.unification_reference_batch_repository import (
    UnificationReferenceBatchRepository,
)
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository
from test.knowledge_unification.test_migration_references_application import (
    complete as complete,
)
from test.knowledge_unification.test_migration_references_application import (
    native as native,
)
from test.knowledge_unification.test_migration_references_application import (
    no_real_network as no_real_network,
)
from test.knowledge_unification.test_migration_references_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_migration_references_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_migration_references_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_migration_references_application import (
    seed_six_and_old_invalid,
)
from test.knowledge_unification.test_migration_references_application import (
    transport as transport,
)
from test.knowledge_unification.test_permission_publication_application import app


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_six_and_old_invalid}], indirect=True)
async def test_all_six_batch_sources_equal_native_exact_projections(published_input):
    value = published_input
    application = app(value)
    plan = await UnificationReferencePlanReader(
        inventory=application.reader, artifact_store=application.store
    ).aprepare(value.frozen, environment=value.input["environment"], backup_ref=None, schema_ref=None)
    seen = set()
    for tenant in value.frozen.tenant_ids:
        keys = tuple(entry.header.source_key for entry in plan.sources if entry.header.source_key.tenant_id == tenant)
        if not keys:
            continue
        with tenant_execution_scope(tenant):
            async with value.sessions() as session, session.begin():
                batch = await UnificationReferenceBatchRepository().aload_reference_sources(session, source_keys=keys)
                assert set(batch) == set(keys)
                for key in keys:
                    assert batch[key] == await UnificationInventoryRepository().aload_reference_source(
                        session, source_key=key
                    )
                    seen.add(key.source_type.value)
    assert seen == {"workflow_version", "hosted_app_version", "assistant", "channel_sync", "knowledge", "model_default"}


async def test_scope_and_missing_keys_fail_before_fabricating_empty_sources(published_input):
    value = published_input
    with tenant_execution_scope(101):
        async with value.sessions() as session, session.begin():
            repository = UnificationReferenceBatchRepository()
            with pytest.raises(BaseErrorCode):
                await repository.aload_reference_sources(
                    session, source_keys=(SourceKey(202, "knowledge", "9000", "current"),)
                )
            with pytest.raises(BaseErrorCode):
                await repository.aload_reference_sources(
                    session, source_keys=(SourceKey(101, "knowledge", "999999", "current"),)
                )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_six_and_old_invalid}], indirect=True)
async def test_root_and_version_latches_are_acquired_in_stable_order(published_input, monkeypatch):
    value = published_input
    repository, latches = UnificationReferenceBatchRepository(), []
    original = repository._read

    async def observe(session, statement):
        if statement._for_update_arg is not None:
            latches.append(str(statement.compile(compile_kwargs={"literal_binds": True})))
        return await original(session, statement)

    monkeypatch.setattr(repository, "_read", observe)
    keys = (
        SourceKey(101, "workflow_version", "wf-refs", "71"),
        SourceKey(101, "channel_sync", "channel-refs", "current"),
        SourceKey(101, "assistant", "as-refs", "current"),
    )
    with tenant_execution_scope(101):
        async with value.sessions() as session, session.begin():
            await repository.aload_reference_sources(session, source_keys=keys, for_update=True)
    assert len(latches) == 4
    assert "as-refs" in latches[0] and "channel-refs" in latches[1] and "wf-refs" in latches[2]
    assert "flowversion" in latches[3] and "71" in latches[3]


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_six_and_old_invalid}], indirect=True)
@pytest.mark.parametrize("damage", [None, "delete", "other_column"])
async def test_historical_index_projection_only_changes_exact_target_owner(published_input, damage):
    value = published_input

    class View:
        def project_rows(self, family, rows):
            assert family == "business_resource_reference"
            if damage == "delete":
                return ()
            return tuple(
                {**row, "target_tenant_id": 202, **({"target_id": "forged"} if damage else {})} for row in rows
            )

    with tenant_execution_scope(101):
        async with value.sessions() as session, session.begin():
            table = BusinessResourceReference.__table__
            original = (await session.execute(sa.select(*table.c).where(table.c.tenant_id == 101))).mappings().first()
            assert original is not None
            key = SourceKey(101, original["source_type"], original["source_id"], original["source_version"])
            repository = ReferenceBackfillRepository(fact_view=View())
            if damage:
                with pytest.raises(BaseErrorCode) as caught:
                    await repository.aload_raw_snapshots(session, source_keys=(key,))
                assert caught.value.kwargs["reason"] == "reference_backfill_history_reference_projection_scope"
            else:
                single = await repository.aload_raw_snapshot(session, source_key=key)
                batch = await repository.aload_raw_snapshots(session, source_keys=(key,))
                assert single == batch[key]
                assert all(row["target_tenant_id"] == 202 for row in single[2])
                raw = await ReferenceBackfillRepository().aload_raw_snapshot(session, source_key=key)
                assert raw[2] and all(row["target_tenant_id"] != 202 for row in raw[2])
