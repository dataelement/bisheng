"""Native stopped-service registration, without SQL/FGA replay or certificate."""

import json

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.knowledge.application.unification_registration import run_registration
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet as Head
from test.knowledge_unification.test_migration_cli import arguments, entry, runtime, seed_cli_operator
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
from test.knowledge_unification.test_permission_publication_application import app


async def prepared(value):
    application = app(value)
    await application.arun_permissions(**value.input, operator_id=7)
    return application


def no_prior_replay(monkeypatch, application):
    async def forbidden(*args, **kwargs):
        raise AssertionError("registration must not replay SQL or permission publication")

    monkeypatch.setattr(application, "arun", forbidden)
    monkeypatch.setattr(application, "arun_permissions", forbidden)


async def test_preview_is_readonly_and_reuses_completed_publication(published_input, monkeypatch):
    value = published_input
    application = await prepared(value)
    no_prior_replay(monkeypatch, application)
    writes = []

    def observe(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    before = value.store.writes, value.store.scans, len(value.artifacts.objects)
    try:
        result = await run_registration(application, **value.input, operator_id=7)
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert not writes and not result["ready"] and not result["registration_complete"]
    assert before == (value.store.writes, value.store.scans, len(value.artifacts.objects))


async def test_register_and_noop_resume_do_not_certify_or_scan_fga(published_input, monkeypatch):
    value = published_input
    application = await prepared(value)
    no_prior_replay(monkeypatch, application)
    before = value.store.writes, value.store.scans
    result = await run_registration(application, apply=True, **value.input, operator_id=7)
    assert result["registration_complete"] and result["full_verification_deferred"] and not result["ready"]
    assert before == (value.store.writes, value.store.scans)
    async with value.sessions() as session, session.begin():
        runs = (await session.execute(sa.select(Run))).scalars().all()
        assert all(r.phase == "backfilling" and r.coverage_epoch is None for r in runs)
        assert all(r.checkpoints["backfilling"]["references"]["complete"] for r in runs)
        assert (await session.execute(sa.select(Head.id).where(Head.record_kind == "source"))).all()
        with pytest.raises(ReferenceCoverageNotReadyError):
            await production_coverage_factory(session).arequire_global_ready()
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    async def reject(*args, **kwargs):
        raise AssertionError("completed prefix must not be rescanned or rewritten")

    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", reject)
    again = await run_registration(application, apply=True, **value.input, operator_id=7)
    assert again["registration_complete"] and again["registration_plan_ref"] == result["registration_plan_ref"]
    value.sessions.assert_closed()


async def test_uncompleted_permissions_and_wrong_operator_are_rejected(published_input):
    value = published_input
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run_registration(app(value), apply=True, **value.input, operator_id=7)
    application = await prepared(value)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await run_registration(application, apply=True, **value.input, operator_id=8)
    assert caught.value.kwargs["reason"].endswith("publication_binding")


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_cli_operator}], indirect=True)
async def test_cli_registration_requires_existing_resume_and_no_conflicting_stage(published_input):
    value = published_input
    await prepared(value)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await entry().arun(
            arguments(value, "--register-references-only", "--apply", "--operator-id", "7"),
            runtime_factory=runtime(value),
        )
    result = await entry().arun(
        arguments(value, "--register-references-only", "--apply", "--resume", "--operator-id", "7"),
        runtime_factory=runtime(value),
    )
    assert result["registration_complete"] and not result["ready"]
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await entry().arun(
            arguments(value, "--register-references-only", "--permissions-only", "--apply"),
            runtime_factory=runtime(value),
        )


async def test_atomic_source_checkpoint_failure_then_resume(published_input, monkeypatch):
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    value = published_input
    application = await prepared(value)
    original = ReferenceBackfillRepository.awrite_registered_source
    failed = []

    async def interrupt(self, session, **kwargs):
        result = await original(self, session, **kwargs)
        if kwargs["source_key"].tenant_id == 101 and not failed:
            failed.append(True)
            raise KnowledgeOperationPlanConflictError(reason="before_checkpoint")
        return result

    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", interrupt)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run_registration(application, apply=True, **value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        rows = (await session.execute(sa.select(Head.id).where(Head.tenant_id == 101))).all()
        assert not rows
        run = (await session.execute(sa.select(Run).where(Run.tenant_id == 101))).scalar_one()
        assert run.checkpoints.get("backfilling", {}).get("references") is None
    assert (await run_registration(application, apply=True, **value.input, operator_id=7))["registration_complete"]


async def seed_app(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from test.knowledge_unification import test_migration_inventory_repository as raw

    async with AsyncSession(database.engine) as session, session.begin():
        session.add(raw.app("register-app", current_version_id="register-version-0"))
        session.add(raw.app_version("register-version-0", "register-app", capabilities={}))


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_app}], indirect=True)
async def test_timestamp_only_app_drift_is_frozen_and_new_drift_on_resume_rejected(published_input):
    from datetime import datetime

    from bisheng.database.models.app import App

    value = published_input
    application = await prepared(value)
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(App.__table__).where(App.id == "register-app").values(update_time=datetime(2026, 11, 20, 10))
        )
    result = await run_registration(application, apply=True, **value.input, operator_id=7)
    assert result["app_revision_differences"] == 1 and result["registration_complete"]
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(App.__table__).where(App.id == "register-app").values(update_time=datetime(2026, 11, 20, 11))
        )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await run_registration(application, apply=True, **value.input, operator_id=7)
    assert caught.value.kwargs["reason"].endswith("delta_changed")


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_app}], indirect=True)
@pytest.mark.parametrize("field,content", [("owner_user_id", 8), ("state", "offline"), ("current_version_id", None)])
async def test_app_identity_or_lifecycle_drift_is_not_accepted(published_input, field, content):
    from bisheng.database.models.app import App

    value = published_input
    application = await prepared(value)
    async with value.sessions() as session, session.begin():
        await session.execute(sa.update(App.__table__).where(App.id == "register-app").values(**{field: content}))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run_registration(application, apply=True, **value.input, operator_id=7)


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_app}], indirect=True)
async def test_app_configuration_drift_rejected_before_any_registration(published_input):
    from bisheng.database.models.app_version import AppVersion

    value = published_input
    application = await prepared(value)
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(AppVersion.__table__)
            .where(AppVersion.id == "register-version-0")
            .values(capabilities={"models": [], "knowledge_bases": [], "secrets": []})
        )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await run_registration(application, apply=True, **value.input, operator_id=7)
    assert caught.value.kwargs["reason"].endswith("actual_source_after_changed")
    async with value.sessions() as session, session.begin():
        assert not (await session.execute(sa.select(Head.id))).all()


@pytest.mark.parametrize("native_registered", [False, True])
async def test_added_zero_reference_workflow_requires_real_registration(published_input, native_registered):
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.resource_reference.application.contracts import reference_set_digest

    value = published_input
    application = await prepared(value)
    async with value.sessions() as session, session.begin():
        session.add(Flow(id="post-freeze", tenant_id=101, name="new", user_id=7, flow_type=10, is_delete=0))
        session.add(
            FlowVersion(
                id=900001,
                tenant_id=101,
                flow_id="post-freeze",
                name="new",
                flow_type=10,
                data={"nodes": [], "edges": []},
                is_delete=0,
                is_current=1,
            )
        )
        if native_registered:
            common = {
                "tenant_id": 101,
                "source_type": "workflow_version",
                "source_id": "post-freeze",
                "source_revision": 1,
                "digest": reference_set_digest(()),
            }
            session.add(
                Head(
                    **common,
                    source_version="__root__",
                    record_kind="root_guard",
                    extractor_version="root-guard-v1",
                    ready=False,
                    effective=False,
                )
            )
            session.add(
                Head(
                    **common,
                    source_version="900001",
                    record_kind="source",
                    extractor_version="workflow-version-v1",
                    ready=True,
                    effective=True,
                )
            )
    if not native_registered:
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await run_registration(application, apply=True, **value.input, operator_id=7)
        assert caught.value.kwargs["reason"].endswith("added_source_not_registered")
    else:
        result = await run_registration(application, apply=True, **value.input, operator_id=7)
        assert result["retained_added_sources"] == 1


def seed_versions(count):
    async def seed(database):
        from sqlmodel.ext.asyncio.session import AsyncSession

        from bisheng.database.models.flow_version import FlowVersion

        async with AsyncSession(database.engine) as session, session.begin():
            for i in range(count):
                session.add(
                    FlowVersion(
                        id=800000 + i,
                        tenant_id=101,
                        flow_id="zero-version",
                        name=str(i),
                        flow_type=10,
                        is_delete=0,
                        is_current=int(i == 0),
                        data={"nodes": [], "edges": []},
                    )
                )

    return seed


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_versions(n)} for n in (12, 24)], indirect=True)
async def test_registration_scale_is_linear_and_has_progress(published_input, caplog):
    import time
    import tracemalloc

    value = published_input
    application = await prepared(value)
    counts = {"sql": 0, "transactions": 0}

    def observe(*args):
        counts["sql"] += 1

    def begin(*args):
        counts["transactions"] += 1

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    sa.event.listen(value.database.engine.sync_engine, "begin", begin)
    tracemalloc.start()
    started = time.monotonic()
    try:
        result = await run_registration(application, apply=True, **value.input, operator_id=7)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
        sa.event.remove(value.database.engine.sync_engine, "begin", begin)
    n = result["source_count"]
    assert counts["transactions"] <= n + result["retired_count"] + 35
    assert counts["sql"] < n * 30 + 200
    print(json.dumps({"registration_scale": n, **counts, "seconds": time.monotonic() - started, "peak_bytes": peak}))


async def seed_retired(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.database.models.flow_version import FlowVersion
    from test.knowledge_unification import test_migration_inventory_repository as raw

    async with AsyncSession(database.engine) as session, session.begin():
        session.add(raw.flow("retired-registration", is_delete=1))
        session.add(
            FlowVersion(
                id=700001,
                tenant_id=101,
                flow_id="retired-registration",
                name="old",
                flow_type=10,
                is_delete=1,
                is_current=0,
                data={"nodes": [], "edges": []},
            )
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_retired}], indirect=True)
async def test_committed_retired_prefix_is_not_replayed_in_registration_resume(published_input, monkeypatch):
    from bisheng.knowledge.application.unification_reference_sources import ReferenceAfterSources

    value = published_input
    application = await prepared(value)
    result = await run_registration(application, apply=True, **value.input, operator_id=7)
    assert result["retired_count"] > 0

    async def reject(*args, **kwargs):
        raise AssertionError("completed retirements must not be reverified in registration-only resume")

    monkeypatch.setattr(ReferenceAfterSources, "averify_retired", reject)
    assert (await run_registration(application, apply=True, **value.input, operator_id=7))["registration_complete"]


@pytest.mark.parametrize("section", ["fga", "sources"])
async def test_only_required_source_leaves_are_revalidated(published_input, section):
    from bisheng.common.errcode.base import BaseErrorCode

    value = published_input
    application = await prepared(value)
    key = next(k for k, body in value.artifacts.objects.items() if ('"section":"' + section + '"').encode() in body)
    value.artifacts.objects[key] = b"corrupt stored leaf"
    if section == "sources":
        with pytest.raises(BaseErrorCode):
            await run_registration(application, apply=True, **value.input, operator_id=7)
        async with value.sessions() as session, session.begin():
            assert not (await session.execute(sa.select(Head.id))).all()
    else:
        assert (await run_registration(application, apply=True, **value.input, operator_id=7))["registration_complete"]


async def seed_channel_and_workflow(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.database.models.flow_version import FlowVersion
    from test.knowledge_unification import test_migration_inventory_repository as raw

    async with AsyncSession(database.engine) as session, session.begin():
        session.add(raw.channel("registration-channel"))
        session.add(
            FlowVersion(
                id=650001,
                tenant_id=101,
                flow_id="zero-version",
                name="v",
                flow_type=10,
                is_delete=0,
                is_current=1,
                data={"nodes": [], "edges": []},
            )
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_channel_and_workflow}], indirect=True)
async def test_channel_timestamp_extension_keeps_original_proof_and_committed_prefix(published_input, monkeypatch):
    from datetime import datetime

    from bisheng.channel.domain.models.channel import Channel
    from bisheng.knowledge.application.unification_references import ReferenceMigration
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    value = published_input
    # Force an old one-source commit boundary; normal upgrades commit bounded
    # batches atomically and must roll the workflow back with a failing channel.
    monkeypatch.setattr(ReferenceMigration, "source_batch_limit", 1)
    application = await prepared(value)
    original_write = ReferenceBackfillRepository.awrite_registered_source

    async def fail_at_channel(self, session, **kwargs):
        if kwargs["source_key"].source_type == "channel_sync":
            raise KnowledgeOperationPlanConflictError(reason="channel_stop")
        return await original_write(self, session, **kwargs)

    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", fail_at_channel)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run_registration(application, apply=True, **value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        rows = (await session.execute(sa.select(Run))).scalars().all()
        with bypass_tenant_filter():
            rows = (await session.execute(sa.select(Run))).scalars().all()
        first = next(r for r in rows if r.tenant_id == 1)
        frozen_checkpoint = dict(first.checkpoints["backfilling"]["registration_plan"])
        tenant = next(r for r in rows if r.tenant_id == 101)
        assert tenant.checkpoints["backfilling"]["references"]["processed_count"] == 1
        await session.execute(
            sa.update(Channel.__table__)
            .where(Channel.id == "registration-channel")
            .values(update_time=datetime(2026, 11, 20, 12))
        )
    written = []

    async def capture(self, session, **kwargs):
        written.append(kwargs["source_key"].source_type.value)
        return await original_write(self, session, **kwargs)

    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", capture)
    result = await run_registration(application, apply=True, **value.input, operator_id=7)
    assert result["channel_revision_differences"] == 1 and result["registration_extension_ref"]
    assert "workflow_version" not in written
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            row = (await session.execute(sa.select(Run).where(Run.tenant_id == 1))).scalar_one()
        assert row.checkpoints["backfilling"]["registration_plan"] == frozen_checkpoint
        assert row.checkpoints["backfilling"]["registration_plan_extension"]["complete"]
    assert (await run_registration(application, apply=True, **value.input, operator_id=7))[
        "registration_extension_ref"
    ] == result["registration_extension_ref"]
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(Channel.__table__)
            .where(Channel.id == "registration-channel")
            .values(update_time=datetime(2026, 11, 20, 13))
        )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await run_registration(application, apply=True, **value.input, operator_id=7)
    assert caught.value.kwargs["reason"].endswith("extension_changed")


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_channel_and_workflow}], indirect=True)
@pytest.mark.parametrize("field,content", [("user_id", 8), ("is_released", True)])
async def test_channel_owner_or_release_change_is_never_timestamp_repair(published_input, field, content):
    from bisheng.channel.domain.models.channel import Channel

    value = published_input
    application = await prepared(value)
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(Channel.__table__).where(Channel.id == "registration-channel").values(**{field: content})
        )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await run_registration(application, apply=True, **value.input, operator_id=7)
    assert caught.value.kwargs["reason"].endswith("channel_identity_changed")


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_channel_and_workflow}], indirect=True)
async def test_channel_binding_change_is_not_timestamp_repair(published_input):
    from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync

    value = published_input
    application = await prepared(value)
    async with value.sessions() as session, session.begin():
        session.add(
            ChannelKnowledgeSync(
                id="changed-link",
                channel_id="registration-channel",
                knowledge_space_id="9000",
                user_id=7,
                is_enabled=False,
            )
        )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await run_registration(application, apply=True, **value.input, operator_id=7)
    assert caught.value.kwargs["reason"].endswith("actual_source_after_changed")


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_channel_and_workflow}], indirect=True)
async def test_new_channel_extension_cannot_rebase_an_already_committed_source(published_input):
    from datetime import datetime

    from bisheng.channel.domain.models.channel import Channel

    value = published_input
    application = await prepared(value)
    await run_registration(application, apply=True, **value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(Channel.__table__)
            .where(Channel.id == "registration-channel")
            .values(update_time=datetime(2026, 11, 21))
        )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await run_registration(application, apply=True, **value.input, operator_id=7)
    assert caught.value.kwargs["reason"].endswith("extension_touches_committed_source")
