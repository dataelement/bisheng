"""Native storage facts are not a sharing or deletion authorization API."""

from copy import deepcopy

import pytest

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanChangedError,
    KnowledgeProcessingConflictError,
)
from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from test.knowledge_unification import test_model_delete_plan_application as actual

model_owner_tenant = actual.model_owner_tenant
removal_session = actual.removal_session
impact = actual.impact
ready = actual.ready


def actor():
    return {
        "tenant_id": 101,
        "actor_user_id": 7,
        "data_scope": "all_visible",
        "credential_reference": {
            "kind": "web_session",
            "user_id": 7,
            "tenant_id": 101,
            "token_version": 3,
            "expires_at": "2099-11-09T11:00:00",
        },
    }


async def reserve(session, repo, *, server_id=5):
    await repo.alock_provider(session, server_id=server_id)
    return await repo.acreate_share_reservation(
        session,
        server_id=server_id,
        actor_reference=actor(),
        server_revision="a" * 64,
        command_digest="b" * 64,
        metadata={"purpose": "share"},
    )


async def test_empty_provider_has_a_real_indexed_fence_without_model_or_coverage(ready):
    session, _, plans = ready
    repo = ModelProviderOperationRepository(plans)
    row = await reserve(session, repo)
    assert row.operation == "model_share_server" and row.model_server_id == 5
    assert row.impact == {} and row.target_manifest == [] and row.model_execution_state == "PREPARING"
    with pytest.raises(KnowledgeProcessingConflictError):
        await repo.arequire_idle(session, server_id=5)
    await repo.arequire_idle(session, server_id=5, allowed_operation_id=row.operation_id)
    await repo.arequire_idle(session, server_id=1)


async def test_provider_fence_release_and_ack_are_same_transaction_storage(ready):
    session, _, plans = ready
    repo = ModelProviderOperationRepository(plans)
    row = await reserve(session, repo)
    original = plans._payload(row), row.request_hash, row.plan_digest
    await repo.aset_state(session, row=row, expected="PREPARING", target="COMPLETED", metadata={"result": "stable-ack"})
    await repo.arequire_idle(session, server_id=5)
    restored = await repo.aread_plan(session, confirmation_id=row.id)
    repo.validate(restored)
    assert restored.model_execution_state == "COMPLETED"
    assert restored.model_execution_metadata == {"result": "stable-ack"}
    assert (plans._payload(restored), restored.request_hash, restored.plan_digest) == original


async def test_competing_or_wrong_stage_cannot_complete_the_fence(ready):
    session, _, plans = ready
    repo = ModelProviderOperationRepository(plans)
    row = await reserve(session, repo)
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await repo.aset_state(session, row=row, expected="RESERVED", target="COMPLETED")
    with pytest.raises(KnowledgeProcessingConflictError):
        await reserve(session, repo)


async def test_consumed_owner_can_use_new_web_credential_but_cannot_change_subject_or_pin(ready):
    session, _, plans = ready
    repo = ModelProviderOperationRepository(plans)
    row = await reserve(session, repo)
    fresh = deepcopy(actor())
    fresh["credential_reference"].update(token_version=4, expires_at="2099-12-09T11:00:00")
    repo.require_current_actor(row, fresh)
    for key, value in (("actor_user_id", 8), ("management_tenant_id", 101), ("tenant_id", 202)):
        changed = deepcopy(fresh)
        changed[key] = value
        with pytest.raises(KnowledgeOperationPlanChangedError):
            repo.require_current_actor(row, changed)


async def test_original_unconsumed_confirmation_still_requires_exact_credential(ready):
    session, references, plans = ready
    with actual.native.actor() as identity:
        actual.web(identity)
        confirmation = await actual.application(references, plans).aplan_server_delete(
            session, identity=identity, server_id=5
        )
    repo = ModelProviderOperationRepository(plans)
    row = await repo.aread_plan(session, confirmation_id=confirmation.confirmation.confirmation_id)
    repo.require_current_actor(row, actor())
    fresh = deepcopy(actor())
    fresh["credential_reference"]["token_version"] = 4
    with pytest.raises(KnowledgeOperationPlanChangedError):
        repo.require_current_actor(row, fresh)
    assert row.operation_id is None and row.model_server_id is None
    await repo.arequire_idle(session, server_id=5)


async def test_root_shared_readonly_is_preserved_before_any_reservation(ready):
    session, _, plans = ready
    with pytest.raises(LLMModelSharedReadonlyError):
        await ModelProviderOperationRepository(plans).alock_provider(session, server_id=2)
