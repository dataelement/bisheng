"""T111: internal impact uses real Owner SQL, complete pages and ledger reads.

The ledger adapter is a test-only same-session SQL port. Production remains
unconfigured until MIG supplies its real coverage adapter; no FGA is invoked.
"""

import json
from contextlib import contextmanager
from dataclasses import asdict

import pytest
from sqlalchemy import event, select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError, LLMModelSharedReadonlyError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, management_tenant_scope
from bisheng.core.database import tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.services.model_reference_service import ModelReferenceService
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.resource_reference.application.contracts import (
    CoverageStatus,
    GlobalCoverageStatus,
    SourceType,
    tenant_inventory_digest,
)
from bisheng.resource_reference.application.source_disclosure import SourceDisclosureRuntime
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_model_deletion_repository as models
from test.knowledge_unification.test_reference_owner_paging import seed

model_owner_tenant = models.model_owner_tenant
removal_session = models.removal_session


class RestrictedMetadata:
    """These original BRR-only fixtures have no business disclosure metadata."""

    async def adisclose_sources(self, session, *, identity, source_keys):
        return (None,) * len(source_keys)


class SqlLedger:
    def __init__(self, session):
        self.session, self.reads, self.drift = session, 0, False

    async def aget_status(self, tenant_id, source_type, writer_contract_version):
        row = (
            await self.session.execute(select(KnowledgeUnificationRun).where(KnowledgeUnificationRun.run_id == "proof"))
        ).scalar_one_or_none()
        ready = row is not None and row.source_coverage.get(source_type.value) is True
        return CoverageStatus(tenant_id, source_type, writer_contract_version, ready, None if ready else "missing")

    async def aget_global_status(self, writer_contract_version):
        self.reads += 1
        with bypass_tenant_filter():
            ids = tuple((await self.session.execute(select(Tenant.id).order_by(Tenant.id))).scalars())
            rows = tuple((await self.session.execute(select(KnowledgeUnificationRun))).scalars())
        if self.drift and self.reads == 2:
            rows[0].verification_report = {"epoch": 2}
            await self.session.flush()
        ready = {row.tenant_id for row in rows} == set(ids) and all(
            row.phase == "completed"
            and row.writer_contract_version == writer_contract_version
            and all(row.source_coverage.get(kind.value) is True for kind in SourceType)
            and row.verification_report == {"epoch": 1}
            for row in rows
        )
        return GlobalCoverageStatus(
            ready,
            writer_contract_version,
            tuple(SourceType),
            tenant_inventory_digest(ids),
            1,
            ids,
            None if ready else "incomplete",
        )


@pytest.fixture
async def impact(removal_session, monkeypatch):
    session = removal_session
    for model in (BusinessReferenceSet, KnowledgeUnificationRun, KnowledgeProcessingJob):
        await session.run_sync(lambda active, model=model: model.__table__.create(active.connection(), checkfirst=True))
    session.add_all(
        KnowledgeUnificationRun(
            tenant_id=tenant,
            run_id="proof",
            origin="empty_tenant",
            phase="completed",
            source_coverage={kind.value: True for kind in SourceType},
            verification_report={"epoch": 1},
        )
        for tenant in (1, 101, 202)
    )
    await session.commit()
    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables
        | {"knowledge_unification_run", "business_reference_set", "knowledge_processing_job"},
    )
    ledger = SqlLedger(session)
    verifier = ReferenceTargetVerifier({"model": ModelReferenceTargetOwner()})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    service = ModelReferenceService(
        coverage_factory=lambda active: CoverageRepository(ledger, global_port=ledger), runtime=runtime
    )
    service.disclosure_runtime = SourceDisclosureRuntime({kind: RestrictedMetadata() for kind in SourceType})
    return session, service, ledger


@contextmanager
def actor(*, admin=True, super_admin=False):
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    token = set_current_permission_actor(
        PermissionActor(
            user_id=7,
            tenant_id=101,
            super_admin=super_admin,
            tenant_admin_tenant_ids=frozenset({101}) if admin else frozenset(),
        )
    )
    try:
        yield user
    finally:
        reset_current_permission_actor(token)


async def inspect(impact, identity, *, server_id=1, retained=(), delete_server=False):
    session, service, _ = impact
    return await service.ainspect_removed_models(
        session, identity=identity, server_id=server_id, retained_model_ids=retained, delete_server=delete_server
    )


async def test_five_model_kinds_full_pages_and_distinct_source_versions_are_counted(impact):
    session, _, ledger = impact
    model_queries = []

    def record(state):
        if state.is_select and any(
            getattr(table, "name", None) in {"llm_model", "llm_server"} for table in state.statement.get_final_froms()
        ):
            model_queries.append(state.statement)

    event.listen(session.sync_session, "do_orm_execute", record)
    for index, kind in enumerate(SourceType):
        _, bindings = seed(session, source_type=kind.value, source_id=f"private-{index}", slots=73)
        for offset, binding in enumerate(bindings):
            binding.target_id = str(11 + offset % 5)
    await session.flush()
    with actor() as user:
        result = await inspect(impact, user, delete_server=True)
    assert {target.target_id for target in result.targets} == {"11", "12", "13", "14", "15"}
    assert sum(dict(result.source_counts).values()) == 6
    assert sum(dict(result.slot_counts).values()) == 438
    assert result.blocked and result.check_complete and ledger.reads == 2
    assert result.restricted_counts == result.source_counts
    assert result.coverage_epoch == 1 and len(result.inbound_digest) == 64
    assert "private-" not in json.dumps(asdict(result))
    assert len(model_queries) <= 10


async def test_shared_root_target_counts_both_source_tenants_without_disclosing_them(impact):
    session, _, _ = impact
    for tenant in (101, 202):
        _, rows = seed(session, tenant=tenant, slots=2)
        for row in rows:
            row.target_id, row.target_tenant_id = "22", 1
    await session.flush()
    with actor(super_admin=True) as user, management_tenant_scope(1):
        result = await inspect(impact, user, server_id=2, delete_server=True)
    assert dict(result.source_counts)["assistant"] == 2
    assert dict(result.slot_counts)["assistant"] == 4
    assert result.targets[0].target_id == "22" and result.blocked


async def test_no_production_coverage_adapter_never_means_zero_references(impact):
    session, service, _ = impact
    with actor() as user, pytest.raises(ReferenceCoverageNotReadyError) as failure:
        await ModelReferenceService(runtime=service.runtime).ainspect_removed_models(
            session, identity=user, server_id=1, retained_model_ids=()
        )
    assert failure.value.kwargs["reason"] == "model_reference_coverage_unconfigured"


@pytest.mark.parametrize("failure", ["source", "tenant", "epoch", "query"])
async def test_incomplete_or_changed_checks_fail_closed_even_for_empty_results(impact, failure):
    session, _, ledger = impact
    if failure == "source":
        row = (await session.execute(select(KnowledgeUnificationRun))).scalar_one()
        row.source_coverage = {"assistant": True}
    elif failure == "tenant":
        session.add(Tenant(id=303, tenant_code="uncovered", tenant_name="Uncovered", parent_tenant_id=1, status=0))
    elif failure == "epoch":
        ledger.drift = True
    else:

        def broken(state):
            if state.is_select and "business_resource_reference" in str(state.statement):
                raise RuntimeError("reference storage unavailable")

        event.listen(session.sync_session, "do_orm_execute", broken)
    await session.flush()
    with actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
        await inspect(impact, user)


async def test_original_admin_tenant_and_shared_readonly_boundaries_remain(impact):
    with actor(admin=False) as user, pytest.raises(LLMModelSharedReadonlyError):
        await inspect(impact, user)
    with actor() as user:
        with pytest.raises(LLMModelSharedReadonlyError):
            await inspect(impact, user, server_id=2)
        with pytest.raises(LLMModelNotAccessibleError):
            await inspect(impact, user, server_id=3)


async def test_job_history_audit_model_id_is_not_an_independent_source(impact):
    session, _, _ = impact
    session.add(
        KnowledgeProcessingJob(
            tenant_id=get_current_tenant_id(),
            space_id=9,
            kind="embedding_rebuild",
            actor_user_id=7,
            actor_reference={"actor_user_id": 7},
            idempotency_key="history",
            request_hash="a" * 64,
            expected_model_config_revision=1,
            parameters={"embedding_model_id": 11},
        )
    )
    await session.flush()
    with actor() as user:
        result = await inspect(impact, user)
    assert result.check_complete and not result.blocked
    assert sum(dict(result.source_counts).values()) == 0


async def test_last_page_changes_digest_and_retained_models_are_excluded(impact):
    session, _, _ = impact
    _, rows = seed(session, slots=201)
    await session.flush()
    with actor() as user:
        before = await inspect(impact, user)
        rows[-1].slot_key = "changed-last-slot"
        await session.flush()
        after = await inspect(impact, user)
        retained = await inspect(impact, user, retained=(11,))
    assert before.inbound_digest != after.inbound_digest
    assert dict(after.slot_counts)["assistant"] == 201
    assert not retained.blocked and "11" not in {target.target_id for target in retained.targets}


@pytest.mark.parametrize("corrupt", ["owner", "space", "legacy"])
async def test_inbound_target_metadata_must_agree_with_actual_live_owner(impact, corrupt):
    session, _, _ = impact
    _, rows = seed(session)
    if corrupt == "owner":
        rows[0].target_tenant_id = 202
    elif corrupt == "space":
        rows[0].target_space_id = "99"
    else:
        rows[0].target_tenant_id = None
        rows[0].legacy_invalid_reason = "target_missing"
        rows[0].legacy_run_id, rows[0].legacy_evidence_key = "frozen-run", "frozen-evidence"
    await session.flush()
    with actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
        await inspect(impact, user)
