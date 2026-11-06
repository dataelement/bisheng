"""Read views preserve invalid choices and never manufacture target metadata.

覆盖 AC: AC-71, AC-88, AC-89, AC-91, AC-92.
"""

from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.channel.application import reference_source_owner as owner_module
from bisheng.channel.application.reference_source_owner import ChannelReferenceSourceOwner
from bisheng.channel.domain.services import channel_service as service_module
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_ch_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
async def view(business, monkeypatch):
    root = await fixtures.create(business, sync=fixtures.config(10, folder="30", enabled=False))
    verifier = SourceReadVerifier({"channel_sync": ChannelReferenceSourceOwner()}, AuthenticatedSourceReadIdentity())
    target = KnowledgeSourceReadTargetOwner(verifier)
    runtime = ReferenceSourceReadRuntime(
        verifier, SourceReadRepository(verifier), {"knowledge_space": target, "knowledge_file": target}
    )
    monkeypatch.setattr(service_module, "get_reference_read_runtime", AsyncMock(return_value=runtime), raising=False)
    monkeypatch.setattr(owner_module, "require_business_action", AsyncMock())
    monkeypatch.setattr(knowledge_module, "get_async_db_session", business.sessions)
    monkeypatch.setattr(service_module, "batch_check_business_visible", AsyncMock(return_value={"10": True}))
    token = set_current_permission_actor(PermissionActor(tenant_id=101, user_id=7))
    try:
        yield business, root
    finally:
        reset_current_permission_actor(token)


async def test_valid_view_keeps_original_ids_flags_and_minimal_public_states(view):
    context, root = view
    result = await context.service._load_knowledge_sync(root.id, context.user)
    item = result.main.spaces[0]
    assert not result.main.enabled and item.knowledge_space_id == "10" and item.folder_id == "30"
    assert item.knowledge_space_name == "space-10"
    assert {(state.target_id, state.state, state.is_valid) for state in item.reference_states} == {
        ("10", "valid", True),
        ("30", "valid", True),
    }
    assert all(
        set(state.model_dump()) == {"slot_key", "target_type", "target_id", "state", "is_valid"}
        for state in item.reference_states
    )


async def test_deleted_space_and_descendant_folder_stay_selected_without_fake_names(view):
    context, root = view
    await fixtures.deleted_space(context)
    # A real space deletion removes its descendants; a live orphan file is
    # deliberately rejected by the actual target Owner as inconsistent data.
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(KnowledgeFile).where(KnowledgeFile.id == 30, KnowledgeFile.tenant_id == 101))
    result = await context.service._load_knowledge_sync(root.id, context.user)
    item = result.main.spaces[0]
    assert (item.knowledge_space_id, item.folder_id, item.knowledge_space_name) == ("10", "30", None)
    assert not result.main.enabled and len(item.reference_states) == 2
    assert all(state.state == "invalid_deleted" and not state.is_valid for state in item.reference_states)


async def test_hidden_target_retains_id_without_exposing_metadata(view, monkeypatch):
    context, root = view
    monkeypatch.setattr(service_module, "batch_check_business_visible", AsyncMock(return_value={"10": False}))
    result = await context.service._load_knowledge_sync(root.id, context.user)
    assert result.main.spaces[0].knowledge_space_id == "10"
    assert result.main.spaces[0].knowledge_space_name is None


async def test_deleting_is_displayed_normally_but_not_claimed_executable(view):
    context, root = view
    async with context.sessions() as session, session.begin():
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="knowledge_space",
                target_id="10",
                target_tenant_id=101,
                operation_id="deleting10",
                operation_type="force_delete",
                stage="deleting",
                actor_type="user",
                actor_id="7",
            )
        )
    result = await context.service._load_knowledge_sync(root.id, context.user)
    assert result.main.spaces[0].knowledge_space_id == "10"
    assert all(not state.is_valid for state in result.main.spaces[0].reference_states)


async def test_missing_index_is_not_shown_as_empty_settings(view):
    context, root = view
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.delete(BusinessReferenceSet).where(
                BusinessReferenceSet.tenant_id == 101, BusinessReferenceSet.source_id == root.id
            )
        )
    with pytest.raises(ReferenceCoverageNotReadyError):
        await context.service._load_knowledge_sync(root.id, context.user)
