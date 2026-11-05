"""T375: model/server and sharing facts follow the real source Owner tenant.

覆盖 AC: AC-37, AC-68, AC-89, AC-91, AC-92
"""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, event, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.resource_reference.application.source_contracts import TransientTargetRequest
from test.knowledge_unification import test_knowledge_read_owner as knowledge
from test.knowledge_unification import test_model_reference_owner as models

owner_tenant = knowledge.owner_tenant
knowledge_read_context = knowledge.knowledge_read_context


class Sharing:
    allowed = frozenset({2})
    error = None
    expected_tenant = 101

    async def aget_shared_server_ids(self, session, tenant_id, server_ids):
        assert tenant_id == self.expected_tenant and server_ids == (2,)
        if self.error:
            raise self.error
        return self.allowed


@pytest.fixture
async def model_read_context(knowledge_read_context, monkeypatch):
    from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner

    ctx = knowledge_read_context
    tables = [Tenant.__table__, LLMModel.__table__, LLMServer.__table__, TenantSystemModelConfig.__table__]
    monkeypatch.setattr(
        knowledge.tenant_filter,
        "_tenant_aware_tables",
        knowledge.tenant_filter._tenant_aware_tables | {table.name for table in tables if "tenant_id" in table.columns},
    )
    async with ctx.engine.begin() as connection:
        for table in tables:
            await connection.run_sync(lambda conn, table=table: table.create(conn))
    async with AsyncSession(ctx.engine) as session, session.begin():
        await session.run_sync(models.setup)
    ctx.sharing = Sharing()
    ctx.model = ModelSourceReadTargetOwner(ctx.verifier, legacy_evidence=ctx.legacy, sharing=ctx.sharing)
    return ctx


@pytest.mark.parametrize("source_tenant,target", [(101, 11), (101, 22), (1, 22), (202, 33), (202, 22)])
async def test_own_and_root_source_models_use_real_owner_facts_not_request_tenant(
    model_read_context, source_tenant, target
):
    ctx = model_read_context
    ref = knowledge.spec("model", target)
    owner = {11: 101, 22: 1, 33: 202}[target]
    await knowledge.configure(ctx, (ref,), tenant_id=source_tenant, cached_owners={ref.target: owner})
    ctx.sharing.expected_tenant = source_tenant
    if source_tenant == 1:
        ctx.sharing.error = AssertionError("Root's own model is not Child sharing")
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        fact = (await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.is_valid and fact.target_tenant_id == owner
        assert not session.sync_session.identity_map and knowledge.scopes._resolve_tenant_id() == 101


async def test_explicit_revocation_is_a_live_non_executable_fact_and_preview_cannot_borrow_it(model_read_context):
    ctx = model_read_context
    ref = knowledge.spec("model", 22)
    await knowledge.configure(ctx, (ref,), cached_owners={ref.target: 1})
    ctx.sharing.allowed = frozenset()
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        fact = (await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.state == "valid" and not fact.is_valid
        preview = await ctx.verifier.aissue_transient_scope(
            session, TransientTargetRequest("workflow", "workflow-a", knowledge.payload((ref,))), ctx.identity
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.model.ainspect_transient_targets(session, preview, (ref.target,), identity=ctx.identity)


@pytest.mark.parametrize("case", ["error", "malformed", "foreign", "owner_change"])
async def test_sharing_and_owner_failures_are_never_an_allow_fallback(model_read_context, case):
    ctx = model_read_context
    ref = knowledge.spec("model", 33 if case == "foreign" else 22)
    await knowledge.configure(
        ctx, (ref,), cached_owners={ref.target: 202 if case == "foreign" else 101 if case == "owner_change" else 1}
    )
    error = RuntimeError("FGA sharing unavailable")
    if case == "error":
        ctx.sharing.error = error
    elif case == "malformed":
        ctx.sharing.allowed = frozenset({True})
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        with pytest.raises(RuntimeError if case == "error" else ResourceReferenceInvalidError) as caught:
            await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity)
        if case == "error":
            assert caught.value is error


@pytest.mark.parametrize("stage", ["deleted", "deleting"])
async def test_real_original_model_tombstone_is_read_without_becoming_a_binding_receipt(model_read_context, stage):
    ctx = model_read_context
    ref = knowledge.spec("model", 11)
    await knowledge.configure(ctx, (ref,))
    if stage == "deleted":
        async with AsyncSession(ctx.engine) as session, session.begin():
            await session.execute(delete(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11))
    await knowledge.tombstone(ctx, ref.target, stage)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        fact = (await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.state == ("invalid_deleted" if stage == "deleted" else "deleting") and not fact.is_valid


async def test_server_candidate_change_requires_whole_read_restart(model_read_context):
    ctx = model_read_context
    ref = knowledge.spec("model", 11)
    await knowledge.configure(ctx, (ref,))
    async with AsyncSession(ctx.engine) as session, session.begin():
        session.add(LLMServer(id=4, tenant_id=101, name="replacement", type="openai"))
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        changed = []

        def move(state):
            if (
                state.is_select
                and state.statement._for_update_arg is not None
                and not changed
                and LLMModel.__tablename__ in str(state.statement)
            ):
                changed.append(True)
                state.session.execute(
                    update(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11).values(server_id=4)
                )

        event.listen(session.sync_session, "do_orm_execute", move)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity)
        assert changed


async def test_default_async_sharing_reads_real_five_type_config_in_source_tenant(model_read_context, monkeypatch):
    from bisheng.llm.application import source_read_target_owner as owner_module
    from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner

    ctx = model_read_context
    ref = knowledge.spec("model", 22)
    await knowledge.configure(ctx, (ref,), cached_owners={ref.target: 1})
    relation = AsyncMock()
    relation.list_resource_ids.return_value = []
    monkeypatch.setattr(owner_module, "get_permission_relation_api", AsyncMock(return_value=relation))
    ctx.model = ModelSourceReadTargetOwner(ctx.verifier, legacy_evidence=ctx.legacy)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        fact = (await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert not fact.is_valid  # share_default flag alone grants no server.
    async with AsyncSession(ctx.engine) as session, session.begin():
        with bypass_tenant_filter():
            session.add(
                TenantSystemModelConfig(
                    tenant_id=1,
                    key="assistant_llm",
                    value=json.dumps({"llm_list": [{"model_id": 22, "default": True}]}),
                )
            )
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        fact = (await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.is_valid and not session.sync_session.identity_map


async def test_missing_unrelated_root_default_does_not_cancel_explicit_server_sharing(model_read_context):
    ctx = model_read_context
    ref = knowledge.spec("model", 22)
    await knowledge.configure(ctx, (ref,), cached_owners={ref.target: 1})
    async with AsyncSession(ctx.engine) as session, session.begin():
        session.add(
            TenantSystemModelConfig(
                tenant_id=1, key="assistant_llm", value=json.dumps({"llm_list": [{"model_id": 999, "default": True}]})
            )
        )
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        fact = (await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.is_valid


async def test_missing_model_uses_frozen_original_proof_without_guessing_its_tenant(model_read_context):
    ctx = model_read_context
    ref = knowledge.spec("model", 90)
    await knowledge.configure(
        ctx, (ref,), cached_owners={ref.target: None}, legacy={ref.target: ("run-original", "target-proof")}
    )
    async with AsyncSession(ctx.engine) as session, session.begin():
        session.add(
            knowledge.KnowledgeUnificationRun(
                tenant_id=101,
                run_id="run-original",
                phase="verified",
                baseline_hash="a" * 64,
                plan_hash="b" * 64,
                baseline_ref={"object_key": "101/baseline", "sha256": "a" * 64},
                plan_ref={"object_key": "101/plan", "sha256": "b" * 64},
            )
        )
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
        fact = (await ctx.model.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.state == "invalid_legacy" and fact.target_tenant_id is None and not fact.is_valid
