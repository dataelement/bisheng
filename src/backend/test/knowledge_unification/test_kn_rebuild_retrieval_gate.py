"""T671 / AC-51: real SQL and F048-loaded files distinguish pause from denial."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.services import knowledge_file_visibility_service as module
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import KnowledgeFileVisibilityService
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeFilePermissionAdapter,
    KnowledgeFileDaoPermissionLoader,
)
from bisheng.permission.application import business_authorization
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge_unification import test_kn_rebuild_write_entries as entry_tests

concrete_tenant = entry_tests.concrete_tenant
writes = entry_tests.writes


@pytest.fixture
async def retrieval(writes, monkeypatch):
    facts = SimpleNamespace(files={101}, space_visible=False, checked=[])

    @asynccontextmanager
    async def sessions():
        yield writes.session

    async def snapshots(keys):
        return {
            key: PermissionResourceSnapshot(*key, 3, "ctx3", "CUSTOM", "knowledge_space", "19", "CURRENT")
            for key in keys
        }

    async def decide(actor, targets, action):
        assert action == "visible"
        facts.checked.append(tuple(int(target.resource_id) for target in targets))
        return tuple(int(target.resource_id) in facts.files for target in targets)

    async def space_action(kind, ident, action):
        assert (kind, ident, action) == ("knowledge_space", 19, "visible")
        if not facts.space_visible:
            raise SpacePermissionDeniedError()

    runtime = SimpleNamespace(batch_check_actions=AsyncMock(side_effect=decide))
    adapter = F048KnowledgeFilePermissionAdapter(
        loader=KnowledgeFileDaoPermissionLoader(
            SimpleNamespace(get_permission_snapshots=AsyncMock(side_effect=snapshots))
        ),
        permission=runtime,
    )
    monkeypatch.setattr(module, "get_async_db_session", sessions)
    monkeypatch.setattr(
        module, "resolve_permission_actor", AsyncMock(return_value=PermissionActor(user_id=7, current_tenant_id=101))
    )
    monkeypatch.setattr(module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    writes.service._require_action = AsyncMock(side_effect=space_action)
    service = KnowledgeFileVisibilityService(None, writes.service.login_user)
    service.version_repo = KnowledgeDocumentVersionRepositoryImpl(writes.session)
    service._knowledge_space_service = writes.service
    service._config = lambda: SimpleNamespace(index_filter_threshold=100)
    return SimpleNamespace(service=service, facts=facts, writes=writes)


async def call(service, entry, *, ids=None):
    if entry == "prefilter":
        return await service.build_index_prefilter(19, ids)
    return await service.post_filter_retrievable_files(19, [101, 103] if ids is None else ids)


@pytest.mark.parametrize("entry", ["prefilter", "postfilter"])
@pytest.mark.parametrize("qualification", ["file_only", "space_only"])
@pytest.mark.parametrize("transition_only", [False, True])
async def test_authorized_rebuilding_space_is_a_pause_instead_of_empty_or_permission_error(
    retrieval, entry, qualification, transition_only
):
    if qualification == "space_only":
        retrieval.facts.files = set()
        retrieval.facts.space_visible = True
    if transition_only:
        row = await retrieval.writes.session.get(Knowledge, 19)
        row.state, row.model_transition = 1, {"operation_id": "pending"}
        await retrieval.writes.session.commit()
    with pytest.raises(KnowledgeProcessingConflictError) as failure:
        await call(retrieval.service, entry)
    assert failure.value.Code == 10999
    assert retrieval.facts.checked
    if qualification == "file_only":
        # A custom file grant is sufficient; a new container-visible requirement
        # would incorrectly close the independently visible child scope.
        retrieval.writes.service._require_action.assert_not_awaited()
    else:
        retrieval.writes.service._require_action.assert_awaited_once_with("knowledge_space", 19, "visible")


@pytest.mark.parametrize("entry", ["prefilter", "postfilter"])
async def test_empty_rebuilding_scope_can_use_the_existing_space_visible_gate(retrieval, entry):
    retrieval.facts.space_visible = True
    with pytest.raises(KnowledgeProcessingConflictError):
        await call(retrieval.service, entry, ids=[])
    retrieval.writes.service._require_action.assert_awaited_once_with("knowledge_space", 19, "visible")


@pytest.mark.parametrize("entry", ["prefilter", "postfilter"])
async def test_completely_unauthorized_rebuilding_space_keeps_its_original_empty_result(retrieval, entry):
    retrieval.facts.files = set()
    result = await call(retrieval.service, entry)
    assert result.is_empty if entry == "prefilter" else result == set()


@pytest.mark.parametrize("entry", ["prefilter", "postfilter"])
async def test_idle_space_retains_successful_primary_filter_without_an_extra_container_gate(retrieval, entry):
    row = await retrieval.writes.session.get(Knowledge, 19)
    row.state = 1
    await retrieval.writes.session.commit()
    retrieval.facts.files = {101, 103}
    result = await call(retrieval.service, entry)
    assert result.milvus_expr == "document_id in [101]" if entry == "prefilter" else result == {101}
    retrieval.writes.service._require_action.assert_not_awaited()


@pytest.mark.parametrize("entry", ["prefilter", "postfilter"])
async def test_qa_keeps_its_original_qualification_even_with_the_same_state_number(retrieval, entry):
    row = await retrieval.writes.session.get(Knowledge, 19)
    row.type = KnowledgeTypeEnum.QA.value
    await retrieval.writes.session.commit()
    result = await call(retrieval.service, entry)
    assert result.milvus_expr == "document_id in [101]" if entry == "prefilter" else result == {101}
    retrieval.writes.service._require_action.assert_not_awaited()


async def test_original_visible_historical_version_is_still_available_for_delivery(retrieval):
    retrieval.facts.files = {103}
    assert await retrieval.service.post_filter_visible_files(19, [103]) == {103}
    retrieval.writes.service._require_action.assert_not_awaited()
