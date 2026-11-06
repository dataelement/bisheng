"""Workbench defaults and the complete actual SPACE inventory change atomically.

覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
Real mixed Core/Model Owner and SQL; only C4 relation/action transports are
doubles. SQLite does not establish MySQL/DM8 lock/concurrent transaction proof.
"""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application import model_reference as module
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from bisheng.knowledge.application.reference_legacy_evidence import KnowledgeLegacyReferenceEvidence
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.application import reference_target_owner as model_owner_module
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    extract_model_default_references,
)
from bisheng.resource_reference.application.contracts import SourceBindingChange, SourceKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_kn_model_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
async def spaces(business, monkeypatch):
    names = tenant_filter._tenant_aware_tables | {TenantSystemModelConfig.__tablename__}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    async with business.sessions() as session, session.begin():
        await session.execute(sa.delete(Knowledge).where(Knowledge.tenant_id == 101, Knowledge.type == 3))
    return business


async def add(context, ident, model="11"):
    async with context.sessions() as session:
        row = Knowledge(id=ident, tenant_id=101, user_id=7, name=str(ident), type=3, model=model, index_generation="g0")
        await App.acreate(session, row, login_user=context.user, project_created=AsyncMock())
        await session.commit()


async def prepare_default(context, session, batch):
    payload = {"embedding_model": {"id": "12", "name": "own B"}, "models": []}
    key = SourceKey(101, "model_default", "linsight_llm", "current")

    async def lock_root(active):
        await batch.alock_inventory(active)
        await ModelDefaultRepository().alock_root(active, "linsight_llm")

    change = SourceBindingChange(
        key,
        extract_model_default_references("linsight_llm", payload),
        MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
        lock_root,
        new_source=True,
    )
    prepared = await context.runtime.aprepare_mixed_source_bindings(session, (*batch.changes, change))
    return prepared, payload


async def apply_all(context, session, batch, prepared, payload):
    await App.aapply_workbench_model_changes(session, batch, prepared)
    await ModelDefaultRepository().aput(session, "linsight_llm", json.dumps(payload))
    default = next(item for item in prepared if item.source_key.source_type == "model_default")
    await context.runtime.aapply_source_bindings(session, default)


async def test_all_spaces_and_default_use_one_real_mixed_transaction_and_frozen_commands(spaces):
    await add(spaces, 40)
    await add(spaces, 41)
    async with spaces.sessions() as session:
        batch = await App.aplan_workbench_model_changes(session, 12, login_user=spaces.user, operation_id="batch-1")
        assert tuple(change.source_key.source_id for change in batch.changes) == ("40", "41")
        assert {(item.knowledge_id, item.tenant_id, item.actor_user_id) for item in batch.commands} == {
            (40, 101, 7),
            (41, 101, 7),
        }
        assert all(not hasattr(item, "model_id") and item.operation_id == "batch-1" for item in batch.commands)
        prepared, payload = await prepare_default(spaces, session, batch)
        await apply_all(spaces, session, batch, prepared, payload)
        await session.commit()
    facts = fixtures.state(spaces)
    changed = [row for row in facts["knowledge"] if row["id"] in {40, 41}]
    assert all(row["model"] == "11" and row["model_transition"]["pending_model_id"] == "12" for row in changed)
    assert all(row["model_config_revision"] == 1 for row in changed)
    assert all(row["model_config_revision"] == 4 for row in facts["knowledge"] if row["id"] in {12, 13})
    assert len([row for row in facts["business_resource_reference"] if row["source_type"] == "knowledge"]) == 4


async def test_failure_on_second_space_rolls_back_all_business_and_reference_writes(spaces, monkeypatch):
    await add(spaces, 40)
    await add(spaces, 41)
    before = fixtures.state(spaces)
    original = spaces.runtime.aapply_source_bindings

    async def fail_second(session, prepared):
        if prepared.source_key.source_id == "41":
            raise RuntimeError("second source failed")
        return await original(session, prepared)

    monkeypatch.setattr(spaces.runtime, "aapply_source_bindings", fail_second)
    async with spaces.sessions() as session:
        batch = await App.aplan_workbench_model_changes(session, 12, login_user=spaces.user)
        prepared, payload = await prepare_default(spaces, session, batch)
        with pytest.raises(RuntimeError, match="second source failed"):
            await apply_all(spaces, session, batch, prepared, payload)
        await session.rollback()
    assert fixtures.state(spaces) == before


@pytest.mark.parametrize("empty", [False, True])
async def test_inventory_change_is_rejected_after_target_plan_even_when_initially_empty(spaces, empty):
    if not empty:
        await add(spaces, 40)
    async with spaces.sessions() as session:
        batch = await App.aplan_workbench_model_changes(session, 12, login_user=spaces.user)
        await add(spaces, 41)
        before = fixtures.state(spaces)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await prepare_default(spaces, session, batch)
        await session.rollback()
    assert fixtures.state(spaces) == before


async def test_original_batch_cannot_be_replaced_or_consumed_in_another_transaction(spaces):
    await add(spaces, 40)
    async with spaces.sessions() as session, spaces.sessions() as other:
        batch = await App.aplan_workbench_model_changes(session, 12, login_user=spaces.user)
        with pytest.raises(ResourceReferenceInvalidError):
            await replace(batch).alock_inventory(session)
        with pytest.raises(ResourceReferenceInvalidError):
            await batch.alock_inventory(other)
        object.__setattr__(batch, "commands", ())
        with pytest.raises(ResourceReferenceInvalidError):
            await batch.alock_inventory(session)


async def test_default_override_releases_old_root_model_whose_only_inheritance_is_being_replaced(spaces, monkeypatch):
    await add(spaces, 40, "22")
    async with spaces.sessions() as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=1, key="linsight_llm", value='{"embedding_model":{"id":"22"}}'))
    permissions = SimpleNamespace(list_resource_ids=AsyncMock(return_value=()))
    monkeypatch.setattr(model_owner_module, "get_permission_relation_api", AsyncMock(return_value=permissions))
    owner = ModelReferenceTargetOwner(legacy_evidence=KnowledgeLegacyReferenceEvidence())
    verifier = ReferenceTargetVerifier({"model": owner})
    spaces.runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    monkeypatch.setattr(module, "get_reference_binding_runtime", AsyncMock(return_value=spaces.runtime))
    async with spaces.sessions() as session:
        batch = await App.aplan_workbench_model_changes(session, 12, login_user=spaces.user)
        prepared, payload = await prepare_default(spaces, session, batch)
        await apply_all(spaces, session, batch, prepared, payload)
        await session.commit()
    facts = fixtures.state(spaces)
    row = next(row for row in facts["knowledge"] if row["id"] == 40)
    assert row["model"] == "12" and row["model_transition"]["current_model_id"] == "12"
    refs = [item for item in facts["business_resource_reference"] if item["source_type"] == "knowledge"]
    assert {item["target_id"] for item in refs} == {"12"}
