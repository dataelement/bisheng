"""The original M3 entry must reach real backfill, verification and Coverage."""

import socket

import pytest
import sqlalchemy as sa

from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from test.knowledge_unification.test_permission_publication_application import (
    app,
)
from test.knowledge_unification.test_permission_publication_application import (
    complete as complete,
)
from test.knowledge_unification.test_permission_publication_application import (
    native as native,
)
from test.knowledge_unification.test_permission_publication_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_permission_publication_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    transport as transport,
)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("native reference migration tests must not open a real socket")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


async def test_actual_original_entry_completes_references_and_production_coverage(published_input):
    value = published_input
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete and result.run_id == value.frozen.run_id
    value.sessions.assert_closed()
    async with value.sessions() as session, session.begin():
        rows = (await session.execute(sa.select(Run).order_by(Run.tenant_id))).scalars().all()
        assert all(row.phase == "completed" and row.coverage_epoch > 0 for row in rows)
        assert all(row.source_coverage == {kind.value: True for kind in SourceType} for row in rows)
        sources = (
            (await session.execute(sa.select(BusinessReferenceSet).where(BusinessReferenceSet.record_kind == "source")))
            .scalars()
            .all()
        )
        assert sources and all(row.ready for row in sources)
        repository = production_coverage_factory(session)
        assert len(await repository.arequire_ready()) == 6
        global_ready = await repository.arequire_global_ready()
        assert global_ready.verified_tenant_ids == value.frozen.tenant_ids
    assert await app(value).arun_references(**value.input, operator_id=7) == result


async def test_registered_backfill_and_checkpoint_roll_back_together_then_resume(published_input, monkeypatch):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    value = published_input
    original = ReferenceBackfillRepository.awrite_registered_source
    hit = []

    async def fail(self, session, **kwargs):
        result = await original(self, session, **kwargs)
        if kwargs["source_key"].tenant_id == 101 and not hit:
            hit.append(True)
            raise KnowledgeOperationPlanConflictError(reason="native_after_index_before_checkpoint")
        return result

    monkeypatch.setattr(ReferenceBackfillRepository, "awrite_registered_source", fail)
    import pytest

    with pytest.raises(KnowledgeOperationPlanConflictError):
        await app(value).arun_references(**value.input, operator_id=7)
    value.sessions.assert_closed()
    async with value.sessions() as session, session.begin():
        rows = (await session.execute(sa.select(Run.__table__).where(Run.tenant_id == 101))).mappings().all()
        assert rows[0]["coverage_epoch"] is None and not rows[0]["source_coverage"]
        assert rows[0]["checkpoints"].get("backfilling", {}).get("references") is None
        assert not (
            await session.execute(sa.select(BusinessReferenceSet.id).where(BusinessReferenceSet.tenant_id == 101))
        ).all()
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete


async def test_valid_before_target_missing_after_never_becomes_new_legacy(published_input):
    import pytest

    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.llm.domain.models.llm_server import LLMModel
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference

    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel.__table__).where(LLMModel.id == 11))
    with pytest.raises(BaseErrorCode):
        await app(value).arun_references(**value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        assert not (await session.execute(sa.select(BusinessResourceReference.id))).all()
        assert not (await session.execute(sa.select(Run.id).where(Run.coverage_epoch.is_not(None)))).all()


async def test_new_tenant_sql_facts_and_empty_certificate_commit_together(published_input, monkeypatch):
    from types import SimpleNamespace

    from bisheng.approval.domain.services import approval_seed_service
    from bisheng.core import database
    from bisheng.database.models import tenant as tenant_module
    from bisheng.database.models.department import Department
    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.department.domain.services import department_service
    from bisheng.linsight.domain.services import builtin_skill_seeder
    from bisheng.tenant.domain.schemas.tenant_schema import TenantCreate
    from bisheng.tenant.domain.services.tenant_service import TenantService
    from bisheng.workstation.domain.services import WorkStationService

    value = published_input
    before = await app(value).arun_references(**value.input, operator_id=7)
    for model in (Department, UserTenant):
        async with value.database.engine.begin() as conn:
            await conn.run_sync(lambda connection, model=model: model.__table__.create(connection, checkfirst=True))
    calls = []

    async def outside(*args, **kwargs):
        value.sessions.assert_closed()
        calls.append(True)

    from bisheng.tenant.application import tenant_creation

    monkeypatch.setattr(tenant_creation, "get_async_db_session", value.sessions)
    monkeypatch.setattr(tenant_creation, "_get_dept_id_prefix", lambda: "NATIVE")
    monkeypatch.setattr(TenantService, "_creation_factory", staticmethod(tenant_creation.create_tenant_with_coverage))
    monkeypatch.setattr(database, "get_async_db_session", value.sessions)
    monkeypatch.setattr(tenant_module, "get_async_db_session", value.sessions)
    monkeypatch.setattr(department_service, "_get_dept_id_prefix", lambda: "NATIVE")
    monkeypatch.setattr(TenantService, "_apply_tenant_permissions", outside)
    monkeypatch.setattr(WorkStationService, "acopy_root_builtin_tools_to_tenant", outside)
    monkeypatch.setattr(builtin_skill_seeder, "seed_builtin_skills", outside)
    monkeypatch.setattr(approval_seed_service, "seed_approval_scenarios_for_tenant", outside)
    result = await TenantService.acreate_tenant(
        TenantCreate(tenant_name="Native new tenant", tenant_code="native-new", admin_user_ids=[7]),
        SimpleNamespace(user_id=7),
    )
    assert len(calls) == 4
    async with value.sessions() as session, session.begin():
        tenant = (await session.execute(sa.select(Tenant.__table__).where(Tenant.id == result["id"]))).mappings().one()
        assert tenant["root_dept_id"] is not None
        member = (
            (await session.execute(sa.select(UserTenant.__table__).where(UserTenant.tenant_id == result["id"])))
            .mappings()
            .one()
        )
        assert member["user_id"] == 7 and member["is_default"] == 0
        from bisheng.core.context.tenant import tenant_execution_scope

        with tenant_execution_scope(result["id"]):
            row = (
                (await session.execute(sa.select(Run.__table__).where(Run.tenant_id == result["id"]))).mappings().one()
            )
        assert row["origin"] == "empty_tenant" and row["phase"] == "completed"
        assert row["coverage_epoch"] == before.coverage_epoch + 1
        ready = await production_coverage_factory(session).arequire_global_ready()
        assert ready.verified_tenant_ids == tuple(sorted((*before.tenant_ids, result["id"])))


async def seed_six_and_old_invalid(database):
    from datetime import datetime

    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
    from bisheng.database.models.assistant import Assistant, AssistantLink
    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
    from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey, reference_set_digest
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
    from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
    from test.knowledge_unification import test_migration_inventory_repository as raw
    from test.knowledge_unification.test_migration_source_inventory import graph, version

    async with AsyncSession(database.engine) as session, session.begin():
        await session.execute(sa.update(Knowledge.__table__).where(Knowledge.id == 9000).values(model="998"))
        references = (ReferenceSpec("model", TargetKey("model", "999")),)
        session.add_all(
            [
                raw.flow("wf-refs", data=graph(11, 997)),
                FlowVersion(id=71, tenant_id=101, flow_id="wf-refs", name="saved", data=graph(11, 997), is_current=1),
                raw.app("app-refs"),
                version("app-version-refs", "app-refs", {"knowledge_bases": [{"id": "9000"}]}),
                Assistant(id="as-refs", tenant_id=101, user_id=7, model_name="11", status=0),
                AssistantLink(tenant_id=101, assistant_id="as-refs", knowledge_id=9000),
                raw.channel("channel-refs"),
                ChannelKnowledgeSync(
                    id="sync-refs", channel_id="channel-refs", knowledge_space_id="9000", is_enabled=False, user_id=7
                ),
                TenantSystemModelConfig(
                    tenant_id=101,
                    key="linsight_llm",
                    value='{"models":[{"id":"11"}],"task_model":{"id":"11"},"linsight_executor_mode":"old"}',
                ),
                Knowledge(id=9001, tenant_id=101, user_id=7, name="Original QA", type=1, model="999"),
                Run(
                    tenant_id=101,
                    run_id="older-legacy-proof",
                    phase="completed",
                    baseline_hash="a" * 64,
                    plan_hash="b" * 64,
                    baseline_ref={"object_key": "old/baseline", "sha256": "a" * 64},
                    plan_ref={"object_key": "old/plan", "sha256": "b" * 64},
                ),
                BusinessReferenceSet(
                    tenant_id=101,
                    source_type="knowledge",
                    source_id="9001",
                    source_version="__root__",
                    record_kind="root_guard",
                    source_revision=7,
                    extractor_version="root-guard-v1",
                    digest=reference_set_digest(()),
                    effective=False,
                    ready=False,
                ),
                BusinessReferenceSet(
                    tenant_id=101,
                    source_type="knowledge",
                    source_id="9001",
                    source_version="current",
                    source_revision=7,
                    extractor_version="knowledge-model-v1",
                    digest=reference_set_digest(references),
                    effective=True,
                    ready=True,
                ),
                BusinessResourceReference(
                    tenant_id=101,
                    source_type="knowledge",
                    source_id="9001",
                    source_version="current",
                    slot_key="model",
                    target_type="model",
                    target_id="999",
                    target_tenant_id=None,
                    source_revision=7,
                    legacy_invalid_reason="target_missing",
                    legacy_run_id="older-legacy-proof",
                    legacy_evidence_key="old-exact-key",
                ),
                ResourceReferenceTombstone(
                    tenant_id=101,
                    target_type="model",
                    target_id="998",
                    target_tenant_id=101,
                    operation_id="original-force",
                    operation_type="model_delete",
                    stage="deleted",
                    actor_type="user",
                    actor_id="7",
                    deleted_at=datetime(2026, 1, 1),
                ),
            ]
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_six_and_old_invalid}], indirect=True)
async def test_actual_six_sources_keep_known_legacy_and_real_force_evidence(published_input):
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
    from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

    value = published_input
    report = await app(value).arun_references(**value.input, operator_id=7)
    assert report.complete
    async with value.sessions() as session, session.begin():
        run = (await session.execute(sa.select(Run.__table__).where(Run.run_id == report.run_id))).mappings().one()
        proofs = run["verification_report"]["reference_coverage"]["proofs"]
        assert all(proof["source_count"] > 0 for proof in proofs.values())
        assert sum(proof["invalid_legacy_count"] for proof in proofs.values()) == 2
        assert sum(proof["invalid_deleted_count"] for proof in proofs.values()) == 1
        rows = (await session.execute(sa.select(BusinessResourceReference.__table__))).mappings().all()
        old = next(row for row in rows if row["target_id"] == "999")
        assert old["legacy_run_id"] == "older-legacy-proof" and old["legacy_evidence_key"] == "old-exact-key"
        assert old["target_tenant_id"] is None and old["id"] == 1
        forced = next(row for row in rows if row["target_id"] == "998")
        assert forced["legacy_invalid_reason"] is None and forced["target_tenant_id"] == 101
        assert (
            await session.execute(sa.select(ResourceReferenceTombstone.operation_id))
        ).scalar_one() == "original-force"
        assert (await session.execute(sa.select(Knowledge.type).where(Knowledge.id == 9001))).scalar_one() == 1
        assert len([row for row in rows if row["source_type"] == "model_default"]) == 3
    assert await app(value).arun_references(**value.input, operator_id=7) == report


async def seed_retired_indices(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey, reference_set_digest
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
    from test.knowledge_unification import test_migration_inventory_repository as raw
    from test.knowledge_unification.test_migration_source_inventory import graph

    async with AsyncSession(database.engine) as session, session.begin():
        session.add_all(
            [
                raw.flow("deleted-root", is_delete=1),
                raw.flow("mixed-root", data=graph(11)),
                raw.flow("empty-root"),
                FlowVersion(id=901, tenant_id=101, flow_id="deleted-root", name="deleted parent", data=graph(999)),
                FlowVersion(id=902, tenant_id=101, flow_id="mixed-root", name="current", data=graph(11), is_current=1),
                FlowVersion(
                    id=903, tenant_id=101, flow_id="mixed-root", name="deleted version", data=graph(999), is_delete=1
                ),
                Run(
                    tenant_id=101,
                    run_id="retired-legacy-proof",
                    phase="completed",
                    baseline_hash="a" * 64,
                    plan_hash="b" * 64,
                    baseline_ref={"object_key": "old/b", "sha256": "a" * 64},
                    plan_ref={"object_key": "old/p", "sha256": "b" * 64},
                ),
            ]
        )
        # Use the actual extractor's stable slot, not a guessed graph location.
        from bisheng.workflow.domain.services.reference_extractor import extract_workflow_version_references

        slot = extract_workflow_version_references(graph(999))[0].slot_key
        session.add(
            BusinessReferenceSet(
                tenant_id=101,
                source_type="workflow_version",
                source_id="empty-root",
                source_version="__root__",
                record_kind="root_guard",
                source_revision=9,
                extractor_version="root-guard-v1",
                digest=reference_set_digest(()),
                effective=False,
                ready=False,
            )
        )
        for ident, version in (("deleted-root", "901"), ("mixed-root", "903")):
            common = {"tenant_id": 101, "source_type": "workflow_version", "source_id": ident}
            session.add_all(
                [
                    BusinessReferenceSet(
                        **common,
                        source_version="__root__",
                        record_kind="root_guard",
                        source_revision=5,
                        extractor_version="root-guard-v1",
                        digest=reference_set_digest(()),
                        effective=False,
                        ready=False,
                    ),
                    BusinessReferenceSet(
                        **common,
                        source_version=version,
                        source_revision=5,
                        extractor_version="workflow-version-v1",
                        digest=reference_set_digest((ReferenceSpec(slot, TargetKey("model", "999")),)),
                        ready=True,
                    ),
                    BusinessResourceReference(
                        **common,
                        source_version=version,
                        slot_key=slot,
                        target_type="model",
                        target_id="999",
                        source_revision=5,
                        legacy_invalid_reason="target_missing",
                        legacy_run_id="retired-legacy-proof",
                        legacy_evidence_key="retired-exact-key",
                    ),
                ]
            )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_retired_indices}], indirect=True)
async def test_retired_root_and_version_cleanup_is_exact_and_resume_stable(published_input):
    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference

    value = published_input
    result = await app(value).arun_references(**value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        heads = (await session.execute(sa.select(BusinessReferenceSet.__table__))).mappings().all()
        assert not any(row["source_id"] == "deleted-root" or row["source_version"] == "903" for row in heads)
        empty = [row for row in heads if row["source_id"] == "empty-root"]
        assert len(empty) == 1 and empty[0]["record_kind"] == "root_guard" and empty[0]["source_revision"] == 9
        assert any(
            row["source_id"] == "mixed-root" and row["source_version"] == "902" and row["ready"] for row in heads
        )
        assert not (
            await session.execute(
                sa.select(BusinessResourceReference.id).where(BusinessResourceReference.target_id == "999")
            )
        ).all()
        assert (
            len((await session.execute(sa.select(FlowVersion.id).where(FlowVersion.id.in_((901, 902, 903))))).all())
            == 3
        )
        run = (await session.execute(sa.select(Run.__table__).where(Run.run_id == result.run_id))).mappings().one()
        assert set(run["checkpoints"]["backfilling"]) == {"references", "references_retired"}
    assert await app(value).arun_references(**value.input, operator_id=7) == result


@pytest.mark.parametrize("occupied", [False, True])
async def test_real_mounted_tenant_creation_never_fakes_empty_source_proof(published_input, monkeypatch, occupied):
    from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
    from bisheng.database.models.department import Department
    from bisheng.database.models.tenant import Tenant
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.tenant.application import tenant_creation

    value = published_input
    before = await app(value).arun_references(**value.input, operator_id=7)
    async with value.database.engine.begin() as connection:
        await connection.run_sync(lambda conn: Department.__table__.create(conn, checkfirst=True))
    async with value.sessions() as session, session.begin():
        next_id = (await session.execute(sa.select(sa.func.max(Tenant.id)))).scalar_one() + 1
        await session.execute(
            sa.insert(Department.__table__).values(
                id=700, dept_id="native-mount", name="Mount", parent_id=1, tenant_id=1, path="/1/700/"
            )
        )
        if occupied:
            await session.execute(
                sa.insert(Knowledge.__table__).values(
                    id=9900, tenant_id=next_id, user_id=7, name="Preexisting source identity", type=1
                )
            )
    monkeypatch.setattr(tenant_creation, "get_async_db_session", value.sessions)
    tenant = await tenant_creation.create_mounted_tenant_with_coverage(
        tenant=Tenant(tenant_code="native-mount", tenant_name="Native Mount", parent_tenant_id=1, root_dept_id=700),
        department_id=700,
        department_tenant_id=1,
    )
    assert tenant.id == next_id
    async with value.sessions() as session, session.begin():
        from bisheng.core.context.tenant import tenant_execution_scope

        with tenant_execution_scope(next_id):
            cert = (await session.execute(sa.select(Run.__table__).where(Run.tenant_id == next_id))).mappings().all()
        with tenant_execution_scope(1):
            department = (
                (await session.execute(sa.select(Department.__table__).where(Department.id == 700))).mappings().one()
            )
        assert department["is_tenant_root"] == 1 and department["mounted_tenant_id"] == next_id
        repository = production_coverage_factory(session)
        if occupied:
            assert not cert
            with pytest.raises(ReferenceCoverageNotReadyError):
                await repository.arequire_global_ready()
        else:
            assert cert[0]["coverage_epoch"] == before.coverage_epoch + 1
            assert (await repository.arequire_global_ready()).verified_tenant_ids == (*before.tenant_ids, next_id)


@pytest.mark.parametrize("boundary", ["references", "certificate"])
async def test_real_commit_ack_unknown_replays_actual_prefix_without_duplicate_ids(
    published_input, monkeypatch, boundary
):
    from bisheng.knowledge.domain.repositories.unification_coverage_repository import UnificationCoverageRepository
    from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference

    value, hit = published_input, []

    def lose_ack(session):
        raise OSError("native commit completed but ACK lost")

    if boundary == "references":
        original = KnowledgeUnificationRunRepository.acheckpoint

        async def checkpoint(self, session, **kwargs):
            result = await original(self, session, **kwargs)
            if kwargs["checkpoint_key"] == "references" and result.tenant_id == 101 and not hit:
                hit.append(True)
                sa.event.listen(session.sync_session, "after_commit", lose_ack, once=True)
            return result

        monkeypatch.setattr(KnowledgeUnificationRunRepository, "acheckpoint", checkpoint)
    else:
        original = UnificationCoverageRepository.awrite_certificate

        async def certificate(self, session, **kwargs):
            result = await original(self, session, **kwargs)
            if kwargs["row"]["tenant_id"] == 202 and not hit:
                hit.append(True)
                sa.event.listen(session.sync_session, "after_commit", lose_ack, once=True)
            return result

        monkeypatch.setattr(UnificationCoverageRepository, "awrite_certificate", certificate)
    with pytest.raises(OSError):
        await app(value).arun_references(**value.input, operator_id=7)
    value.sessions.assert_closed()
    async with value.sessions() as session, session.begin():
        before = tuple(
            (
                await session.execute(sa.select(BusinessResourceReference.id).order_by(BusinessResourceReference.id))
            ).scalars()
        )
        assert before
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete and result.coverage_epoch == 1
    async with value.sessions() as session, session.begin():
        after = tuple(
            (
                await session.execute(sa.select(BusinessResourceReference.id).order_by(BusinessResourceReference.id))
            ).scalars()
        )
        assert before == after
