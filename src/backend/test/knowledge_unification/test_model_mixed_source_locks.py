"""T474: Model physical prelocks cover different roots without sharing evidence.

覆盖 AC: AC-68, AC-71, AC-87, AC-88, AC-89, AC-91, AC-92
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceConflictError, ResourceReferenceInvalidError
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.resource_reference.application.contracts import LegacyEvidence, SourceKey, TargetKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_model_reference_owner as models

model_owner_tenant = models.model_owner_tenant
SPACE = SourceKey(101, "knowledge", "1", "current")
DEFAULT = SourceKey(101, "model_default", "linsight_llm", "current")


@pytest.fixture
async def mixed_models(model_owner_tenant):
    engine = await models.async_database()
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_actual_model_owner_union_prelocks_then_issues_each_exact_source(mixed_models):
    owner = ModelReferenceTargetOwner(sharing=models.FrozenSharing())
    verifier = ReferenceTargetVerifier({"model": owner})
    async with AsyncSession(mixed_models) as session, session.begin():
        result = await verifier.averify_mixed_source_targets(
            session, ((DEFAULT, (TargetKey("model", "22"),)), (SPACE, (TargetKey("model", "11"),)))
        )
        assert tuple(result) == (SPACE, DEFAULT)
        for source, receipts in result.items():
            assert all(item.source_key == source for item in receipts)
            verifier.validate_binding_receipts(session, source, receipts, tuple(item.target.key for item in receipts))
        assert session.in_transaction() and not session.new and not session.dirty


async def test_physical_prelock_cannot_itself_authorize_root_sharing(mixed_models):
    class Deny:
        async def aget_shared_server_ids(self, *args):
            return frozenset()

    owner = ModelReferenceTargetOwner(sharing=Deny())
    async with AsyncSession(mixed_models) as session, session.begin():
        assert await owner.aprelock_mixed_targets(session, (TargetKey("model", "22"),), (SPACE, DEFAULT)) is None
        with pytest.raises(ResourceReferenceInvalidError):
            await ReferenceTargetVerifier({"model": owner}).averify_targets(
                session, DEFAULT, (TargetKey("model", "22"),)
            )


async def test_each_model_default_root_auxiliary_plan_is_union_locked_before_first_model(mixed_models):
    evaluation = SourceKey(101, "model_default", "evaluation_llm", "current")
    workflow = SourceKey(101, "model_default", "workflow_llm", "current")
    async with AsyncSession(mixed_models) as session, session.begin():
        session.add_all(
            [
                LLMServer(id=4, tenant_id=1, name="other-root", type="openai"),
                LLMServer(id=5, tenant_id=1, name="third-root", type="openai"),
                LLMModel(id=44, tenant_id=1, server_id=4, model_name="aux-workflow", model_type="llm"),
                LLMModel(id=66, tenant_id=1, server_id=5, model_name="aux-evaluation", model_type="llm"),
                TenantSystemModelConfig(tenant_id=1, key="evaluation_llm", value='{"model_id":66}'),
                TenantSystemModelConfig(tenant_id=1, key="workflow_llm", value='{"model_id":44}'),
            ]
        )
    owner = ModelReferenceTargetOwner(sharing=models.FrozenSharing())
    locks = []
    async with AsyncSession(mixed_models) as session, session.begin():

        def record(state):
            if state.is_select and state.statement._for_update_arg is not None:
                entities = {row.get("entity") for row in state.statement.column_descriptions}
                if LLMModel in entities or LLMServer in entities:
                    locks.append(("model" if LLMModel in entities else "server", state.statement.compile().params))

        event.listen(session.sync_session, "do_orm_execute", record)
        result = await ReferenceTargetVerifier({"model": owner}).averify_mixed_source_targets(
            session, ((evaluation, (TargetKey("model", "22"),)), (workflow, (TargetKey("model", "22"),)))
        )
        assert len(result) == 2 and locks[0][0] == "server" and locks[1][0] == "model"
        assert {22, 44, 66} <= next(
            set(value) for value in locks[1][1].values() if isinstance(value, list) and 22 in value
        )


async def test_legacy_original_from_space_is_not_borrowed_by_default_root(mixed_models):
    class Ledger:
        async def aresolve(self, session, source_key, target, *, run_id, evidence_key):
            assert source_key == SPACE and (run_id, evidence_key) == ("frozen-run", "space-only")
            return LegacyEvidence(run_id, "a" * 64, evidence_key)

    async with AsyncSession(mixed_models) as session, session.begin():
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="knowledge",
                source_id="1",
                source_version="current",
                slot_key="model",
                target_type="model",
                target_id="99",
                target_tenant_id=None,
                source_revision=1,
                legacy_invalid_reason="target_missing",
                legacy_run_id="frozen-run",
                legacy_evidence_key="space-only",
            )
        )
    owner = ModelReferenceTargetOwner(legacy_evidence=Ledger())
    async with AsyncSession(mixed_models) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            await ReferenceTargetVerifier({"model": owner}).averify_mixed_source_targets(
                session, ((SPACE, (TargetKey("model", "99"),)), (DEFAULT, (TargetKey("model", "99"),)))
            )
        await session.rollback()


@pytest.mark.parametrize(
    "source",
    [
        SourceKey(202, "knowledge", "1", "current"),
        SourceKey(101, "assistant", "a", "current"),
        SourceKey(101, "knowledge", "1", "draft"),
    ],
)
async def test_mixed_physical_port_rejects_untrusted_tenant_type_or_version(mixed_models, source):
    async with AsyncSession(mixed_models) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            await ModelReferenceTargetOwner().aprelock_mixed_targets(
                session, (TargetKey("model", "11"),), (SPACE, source)
            )


async def test_mixed_prelock_mapping_drift_rejects_without_appending_new_target_locks(mixed_models):
    async with AsyncSession(mixed_models) as session, session.begin():
        session.add(LLMServer(id=4, tenant_id=101, name="replacement", type="openai"))
    changed = []
    async with AsyncSession(mixed_models) as session, session.begin():

        def move(state):
            if (
                state.is_select
                and state.statement._for_update_arg is not None
                and not changed
                and LLMModel in {r.get("entity") for r in state.statement.column_descriptions}
            ):
                changed.append(True)
                state.session.execute(
                    update(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11).values(server_id=4)
                )

        event.listen(session.sync_session, "do_orm_execute", move)
        with pytest.raises(ResourceReferenceConflictError):
            await ModelReferenceTargetOwner().aprelock_mixed_targets(
                session, (TargetKey("model", "11"),), (SPACE, DEFAULT)
            )
        await session.rollback()
    async with AsyncSession(mixed_models) as session, session.begin():
        assert changed and (await session.get(LLMModel, 11)).server_id == 1


@pytest.mark.parametrize("other_inherited_key", [False, True])
async def test_all_mixed_sources_exclude_defaults_being_overridden_from_prospective_sharing(
    mixed_models, monkeypatch, other_inherited_key
):
    from types import SimpleNamespace

    from bisheng.llm.application import reference_target_owner as owner_module

    async with AsyncSession(mixed_models) as session, session.begin():
        session.add(
            TenantSystemModelConfig(
                tenant_id=1, key="linsight_llm", value='{"embedding_model":{"id":"22","name":"root-embedding"}}'
            )
        )
        if other_inherited_key:
            session.add(TenantSystemModelConfig(tenant_id=1, key="workflow_llm", value='{"model_id":22}'))
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="knowledge",
                source_id="1",
                source_version="current",
                slot_key="model",
                target_type="model",
                target_id="22",
                target_tenant_id=1,
                source_revision=1,
            )
        )
    monkeypatch.setattr(
        owner_module,
        "get_permission_relation_api",
        AsyncMock(return_value=SimpleNamespace(list_resource_ids=AsyncMock(return_value=()))),
    )
    owner = ModelReferenceTargetOwner()
    async with AsyncSession(mixed_models) as session, session.begin():
        # Unchanged single-source semantics may still consume the current Root default.
        original = (
            await ReferenceTargetVerifier({"model": owner}).averify_targets(session, SPACE, (TargetKey("model", "22"),))
        )[0]
        assert original.target.new_binding_allowed
    async with AsyncSession(mixed_models) as session, session.begin():
        receipts = await ReferenceTargetVerifier({"model": owner}).averify_mixed_source_targets(
            session,
            ((SPACE, (TargetKey("model", "22"), TargetKey("model", "11"))), (DEFAULT, (TargetKey("model", "11"),))),
        )
        old = next(receipt.target for receipt in receipts[SPACE] if receipt.target.key.target_id == "22")
        assert old.state == "valid" and old.new_binding_allowed is other_inherited_key
        assert all(receipt.target.new_binding_allowed for receipt in receipts[DEFAULT])
