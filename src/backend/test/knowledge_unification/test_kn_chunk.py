"""T099: original chunk entry enforces its actual container/version before IO."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeState
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from test.knowledge_unification import test_move_scope_repository as native

store, tenant, moving = native.store, native.tenant, native.moving


class IndexIOReached(Exception):
    pass


@pytest.fixture
async def chunk_entry(moving, monkeypatch):
    actions, io = [], []

    def load(ident):
        with Session(moving.sync) as session:
            return session.get(Knowledge, ident)

    def authorize(*, login_user, knowledge_id, action):
        actions.append((knowledge_id, action))
        if not login_user.allowed:
            raise UnAuthorizedError()
        assert action == "edit"

    def index(*args, **kwargs):
        io.append((args, kwargs))
        raise IndexIOReached()

    monkeypatch.setattr(KnowledgeDao, "query_by_id", staticmethod(load))
    monkeypatch.setattr(KnowledgeService.permission_service, "ensure_action_sync", authorize)
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    monkeypatch.setattr(KnowledgeRag, "init_knowledge_milvus_vectorstore_sync", index)
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    object.__setattr__(user, "allowed", True)
    return SimpleNamespace(database=moving, user=user, actions=actions, io=io)


def invoke(entry, action, *, space_id=10, file_id=82):
    if action == "update":
        return KnowledgeService.update_knowledge_chunk(None, entry.user, space_id, file_id, 0, "edited", "")
    return KnowledgeService.delete_knowledge_chunk(None, entry.user, space_id, file_id, 0)


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_foreign_container_file_is_rejected_before_any_index_io(chunk_entry, action):
    entry = chunk_entry
    with pytest.raises(HTTPException) as failure:
        invoke(entry, action, space_id=11, file_id=82)
    assert failure.value.status_code == 404 and not entry.io
    assert entry.actions == [(11, "edit")]


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_real_pending_model_transition_blocks_chunk_before_index_io(chunk_entry, action):
    entry = chunk_entry
    with Session(entry.database.sync) as session:
        row = session.get(Knowledge, 10)
        row.state = KnowledgeState.PUBLISHED.value
        row.model_transition = {"schema_version": 1, "operation_id": "actual-pending"}
        session.add(row)
        session.commit()
    with pytest.raises(KnowledgeProcessingConflictError):
        invoke(entry, action)
    assert not entry.io and entry.actions == [(10, "edit")]


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_original_container_edit_allows_historical_physical_version_without_file_edit(chunk_entry, action):
    entry = chunk_entry
    with pytest.raises(IndexIOReached):
        invoke(entry, action)
    assert entry.actions == [(10, "edit")] and len(entry.io) == 1


async def test_file_rename_without_original_container_edit_is_insufficient(chunk_entry):
    entry = chunk_entry
    object.__setattr__(entry.user, "allowed", False)
    with pytest.raises(HTTPException) as failure:
        invoke(entry, "delete")
    assert failure.value.status_code == 403 and not entry.io
    assert entry.actions == [(10, "edit")]
