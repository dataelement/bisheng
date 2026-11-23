"""Offline maintenance CLI E2E, isolated native SQL and protocol transports.

Each fixture creates/disposes a private SQLite database; no shared environment
or existing user data is accessed. Only the MySQL/DM8 control-lock transport is
substituted. Business repositories, Run/CAS, permission publication, reference
backfill, artifact checks and Coverage are the actual production implementations.
HTTP/JWT/browser checks do not apply to this stopped-service CLI entry.
"""

import shutil
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.knowledge.application.unification_upgrade_materials import UpgradeMaterials, envelope
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from test.knowledge_unification.test_migration_cli import entry
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
    transport as transport,
)

pytestmark = pytest.mark.e2e


def arguments(value, directory, *extra):
    return (
        entry()
        .parser()
        .parse_args(
            [
                "--run-id",
                value.input["run_id"],
                "--materials-dir",
                str(directory),
                *extra,
            ]
        )
    )


def runtime(value):
    class Lease:
        async def ensure(self):
            return None

    @asynccontextmanager
    async def executor_lock():
        yield Lease()

    @asynccontextmanager
    async def opened(*args, **kwargs):
        yield SimpleNamespace(
            store=value.artifacts.store,
            sessions=value.sessions,
            engine=value.database.engine,
            executor_lock=executor_lock,
            inventory=None,
        )

    return opened


async def seed_active_operator(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.user.domain.models.user import User

    # Native migration fixtures deliberately start with historical user 7
    # disabled. Prepare the live operator before freezing the test baseline.
    async with AsyncSession(database.engine) as session, session.begin():
        await session.execute(sa.update(User.__table__).where(User.user_id == 7).values(delete=0))


async def seed_unfrozen_source(database):
    from test.knowledge_unification.test_migration_registration import seed_versions
    from test.knowledge_unification.test_upgrade_new_run import seed_actor

    await seed_actor(database)
    await seed_versions(1)(database)


async def seed_owned_assistant(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.database.models.assistant import Assistant

    await seed_active_operator(database)
    async with AsyncSession(database.engine) as session, session.begin():
        session.add(Assistant(id="c3-assistant", tenant_id=101, user_id=7, name="C3 source", model_name="11", status=0))


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_owned_assistant}], indirect=True)
@pytest.mark.parametrize("owner_tenant", [202, 999999])
async def test_ac159_165_foreign_child_drift_is_not_hidden_by_source_tenant_filters(
    published_input, tmp_path, owner_tenant
):
    from bisheng.database.models.assistant import AssistantLink

    value = published_input
    preview = await entry().arun(arguments(value, tmp_path, "--dry-run"), runtime_factory=runtime(value))
    assert preview["can_apply"]
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.insert(AssistantLink.__table__).values(
                id=781999, tenant_id=owner_tenant, assistant_id="c3-assistant", knowledge_id=9000
            )
        )
    writes, before = [], (value.store.writes, dict(value.artifacts.objects))

    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    try:
        changed = await entry().arun(arguments(value, tmp_path, "--dry-run"), runtime_factory=runtime(value))
        assert not changed["can_apply"] and not changed["preflight_complete"], changed
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await entry().arun(
                arguments(value, tmp_path, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
            )
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert not writes and before == (value.store.writes, value.artifacts.objects)


@pytest.mark.parametrize("published_input", [{"freeze": False, "reference_seed": seed_unfrozen_source}], indirect=True)
async def test_ac159_original_new_run_flow_rechecks_frozen_source_before_any_resume_writes(
    published_input, tmp_path, monkeypatch
):
    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
    from test.knowledge_unification.test_upgrade_new_run import runtime as native_history_runtime

    value = published_input
    directory = tmp_path / "original-flow-source-drift"
    cli = entry()
    preview = await cli.arun(arguments(value, directory, "--dry-run"), runtime_factory=native_history_runtime(value))
    assert preview["can_apply"]

    async def interrupted(*args, **kwargs):
        raise RuntimeError("e2e stopped immediately after freeze")

    with monkeypatch.context() as patch:
        patch.setattr(UnificationSQLConversionApplication, "arun_references", interrupted)
        with pytest.raises(RuntimeError, match="immediately after freeze"):
            await cli.arun(
                arguments(value, directory, "--apply", "--operator-id", "7"),
                runtime_factory=native_history_runtime(value),
            )
    # This source participates in no SQL conversion command. Its native config
    # changed without changing update_time or any reference/index revision.
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(FlowVersion.__table__)
            .where(FlowVersion.id == 800000)
            .values(data={"nodes": [], "edges": [], "after_freeze_drift": True})
        )
    writes, before = [], value.store.writes

    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await cli.arun(
                arguments(value, directory, "--apply", "--operator-id", "7"),
                runtime_factory=native_history_runtime(value),
            )
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert not writes and value.store.writes == before


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_active_operator}], indirect=True)
class TestF118UpgradeFlow:
    @pytest.mark.parametrize("damage", ["not_mapping", "extra_ready", "forged_count"])
    async def test_ac159_166_rehashed_summary_tampering_rejects_before_native_effects(
        self, published_input, tmp_path, damage
    ):
        value = published_input
        preview = await entry().arun(arguments(value, tmp_path, "--dry-run"), runtime_factory=runtime(value))
        materials = UpgradeMaterials(tmp_path, run_id=value.frozen.run_id)
        flow = deepcopy(materials.read_object(preview["flow_ref"], kind="upgrade_flow")["records"][0])
        if damage == "not_mapping":
            flow["history_summary"] = False
        elif damage == "extra_ready":
            flow["history_summary"]["ready"] = True
        else:
            flow["history_summary"]["auto_repair"] = 1
            flow["history_summary"]["actions"] = {"levels": 1}
            flow["history_summary"]["counts_scope"] = "original_history_plan"
        forged = materials.write_object("upgrade_flow", envelope(value.frozen.run_id, "upgrade_flow", [flow]))
        materials.activate(forged)
        # Keep exactly one correctly hashed candidate: rejection must come from
        # semantic/schema validation, not ambiguity with the original plan.
        shutil.rmtree(tmp_path / "reconciliation" / preview["flow_ref"]["sha256"])
        writes, before = [], (value.store.writes, dict(value.artifacts.objects))

        def observe(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
                await entry().arun(
                    arguments(value, tmp_path, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
                )
        finally:
            sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
        assert caught.value.code == 10998 and "summary" in caught.value.kwargs["reason"]
        assert not writes and before == (value.store.writes, value.artifacts.objects)

    async def test_ac159_repeated_preview_reuses_identical_immutable_candidate(self, published_input, tmp_path):
        value = published_input
        first = await entry().arun(arguments(value, tmp_path, "--dry-run"), runtime_factory=runtime(value))
        second = await entry().arun(arguments(value, tmp_path, "--dry-run"), runtime_factory=runtime(value))
        assert first["flow_ref"] == second["flow_ref"]
        assert value.store.writes == 0

    @pytest.mark.parametrize("candidate", ["stale", "second_match"])
    async def test_ac159_candidate_selection_requires_exactly_one_matching_plan(
        self, published_input, tmp_path, candidate
    ):
        value = published_input
        preview = await entry().arun(arguments(value, tmp_path, "--dry-run"), runtime_factory=runtime(value))
        materials = UpgradeMaterials(tmp_path, run_id=value.frozen.run_id)
        flow = deepcopy(materials.read_object(preview["flow_ref"], kind="upgrade_flow")["records"][0])
        flow["planned_at"] = "2026-11-21T00:00:00+00:00"
        if candidate == "stale":
            proof = deepcopy(materials.read_object(flow["reconciliation_ref"], kind="verification"))
            proof["records"][0]["tenant_observations"][0]["source_digest"] = "0" * 64
            flow["reconciliation_ref"] = materials.write_object("verification", proof)
        other = materials.write_object("upgrade_flow", envelope(value.frozen.run_id, "upgrade_flow", [flow]))
        assert other != preview["flow_ref"]
        materials.activate(other)  # ACTIVE/mtime must not choose the candidate.
        writes, before = [], value.store.writes

        def observe(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
        try:
            if candidate == "second_match":
                with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
                    await entry().arun(
                        arguments(value, tmp_path, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
                    )
                assert caught.value.kwargs["reason"].endswith("multiple_matching_candidates")
                assert not writes and value.store.writes == before
            else:
                result = await entry().arun(
                    arguments(value, tmp_path, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
                )
                assert result["ready"]
        finally:
            sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)

    async def test_ac159_bound_candidate_recovers_after_all_local_materials_are_lost(
        self, published_input, tmp_path, monkeypatch
    ):
        from bisheng.core.context.tenant import tenant_execution_scope
        from bisheng.knowledge.domain.repositories.unification_upgrade_repository import UpgradeRunRepository
        from bisheng.resource_reference.domain.repositories.reference_backfill_repository import (
            ReferenceBackfillRepository,
        )

        value = published_input
        directory = tmp_path / "lost-local-materials"
        preview = await entry().arun(arguments(value, directory, "--dry-run"), runtime_factory=runtime(value))
        original = ReferenceBackfillRepository.awrite_registered_source

        async def interrupted(*args, **kwargs):
            raise KnowledgeOperationPlanConflictError(reason="e2e_registered_batch_interrupted")

        monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", interrupted)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await entry().arun(
                arguments(value, directory, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
            )
        async with value.sessions() as session, session.begin():
            with tenant_execution_scope(1):
                state = await UpgradeRunRepository().aload_state(
                    session, run_id=value.frozen.run_id, writer_contract_version=value.frozen.writer_contract_version
                )
            assert state.reconciliation_refs == (preview["flow_ref"],)
        shutil.rmtree(directory)
        monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", original)
        result = await entry().arun(
            arguments(value, directory, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
        )
        assert result["ready"] and result["coverage_epoch"] > 0

    async def test_ac158_159_161_166_frozen_preview_is_readonly_then_same_plan_reaches_coverage(
        self, published_input, tmp_path
    ):
        """AC-158/159/161/166: two CLI calls, automatic environment, real complete certificate."""
        value, writes = published_input, []
        directory = tmp_path / "e2e-f118-upgrade-materials"

        def observe(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        before = value.store.writes, len(value.artifacts.objects)
        sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
        try:
            preview = await entry().arun(arguments(value, directory, "--dry-run"), runtime_factory=runtime(value))
        finally:
            sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
        assert not writes and before == (value.store.writes, len(value.artifacts.objects))
        assert preview["can_apply"] and preview["preflight_complete"] and preview["ready"] is False
        assert preview["environment"] == value.input["environment"]
        result = await entry().arun(
            arguments(value, directory, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
        )
        assert result["ready"] is True and result["coverage_epoch"] > 0
        async with value.sessions() as session, session.begin():
            with bypass_tenant_filter():
                rows = (await session.execute(sa.select(Run).where(Run.run_id == value.frozen.run_id))).scalars().all()
            assert tuple(sorted(row.tenant_id for row in rows)) == value.frozen.tenant_ids
            assert all(row.phase == "completed" and row.coverage_epoch == result["coverage_epoch"] for row in rows)
            assert (
                await production_coverage_factory(session).arequire_global_ready()
            ).verified_tenant_ids == value.frozen.tenant_ids
        again = await entry().arun(
            arguments(value, directory, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
        )
        assert again["coverage_epoch"] == result["coverage_epoch"] and again["ready"]
        audited = await entry().arun(
            arguments(value, directory, "--apply", "--verify", "--operator-id", "7"), runtime_factory=runtime(value)
        )
        assert audited["coverage_epoch"] == result["coverage_epoch"] and audited["ready"]
        value.sessions.assert_closed()

    @pytest.mark.parametrize("damage", ["material", "source"])
    async def test_ac159_tampered_material_or_post_preview_drift_rejects_before_run_or_business_writes(
        self, published_input, tmp_path, damage
    ):
        """AC-159: changed plan or forbidden current facts reject before any migration mutation."""
        value = published_input
        directory = tmp_path / "e2e-f118-upgrade-reject"
        preview = await entry().arun(arguments(value, directory, "--dry-run"), runtime_factory=runtime(value))
        assert preview["preflight_complete"]
        if damage == "material":
            (directory / "objects" / (preview["flow_ref"]["sha256"] + ".json")).write_bytes(b"{}")
        else:
            async with value.sessions() as session, session.begin():
                await session.execute(
                    sa.update(Knowledge.__table__)
                    .where(Knowledge.id == 9000)
                    .values(name="e2e-f118-unauthorized-drift")
                )
        writes, fga_before = [], value.store.writes

        def observe(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
                await entry().arun(
                    arguments(value, directory, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
                )
        finally:
            sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
        assert caught.value.code == 10998
        assert not writes and value.store.writes == fga_before
        value.sessions.assert_closed()

    async def test_ac161_invalid_operator_and_environment_reject_without_mutation(self, published_input, tmp_path):
        """AC-161: invalid actor and conflicting detected environment pair the successful admission."""
        value = published_input
        directory = tmp_path / "e2e-f118-upgrade-identity"
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await entry().arun(arguments(value, directory, "--apply"), runtime_factory=runtime(value))
        assert caught.value.code == 10998
        writes = []

        def observe(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError) as missing:
                await entry().arun(
                    arguments(value, directory, "--apply", "--operator-id", "900001"), runtime_factory=runtime(value)
                )
            assert missing.value.code == 10998 and not writes
        finally:
            sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await entry().arun(
                arguments(value, directory, "--dry-run", "--environment", "different-site"),
                runtime_factory=runtime(value),
            )
        assert caught.value.code == 10998 and caught.value.kwargs["reason"].endswith("environment_assertion_changed")
        assert value.store.writes == 0
