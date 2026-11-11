"""AC-03, AC-05, AC-07: first-message binding shares the session transaction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from bisheng.chat_session.domain.repositories import project_repository
from bisheng.chat_session.domain.repositories.project_session_repository import ProjectSessionRepository
from bisheng.common.errcode.chat import ProjectUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.session import MessageSession
from test.chat_session.test_projects_repository import action, create
from test.chat_session.test_projects_repository import repo as _repo_fixture

repo = _repo_fixture


def test_first_message_binds_session_and_membership_atomically(repo):
    repository, actor = repo
    project = create(repository, actor)
    row = MessageSession(chat_id="first-message", name="New Chat", user_id=7, tenant_id=1, flow_type=15)
    assert ProjectSessionRepository.create(actor, row, project) == "first-message"
    assert repository.snapshot(actor)["memberships"] == [{"chat_id": "first-message", "project_id": project}]


def test_deleted_project_cannot_create_session(repo):
    repository, actor = repo
    project = create(repository, actor)
    repository.execute(actor, action("delete", project_id=project))
    with pytest.raises(ProjectUnavailableError):
        ProjectSessionRepository.create(
            actor, MessageSession(chat_id="orphan", user_id=7, tenant_id=1, flow_type=15), project
        )
    with tenant_execution_scope(1), project_repository.get_sync_db_session() as db:
        assert db.get(MessageSession, "orphan") is None


@pytest.mark.parametrize("entry", ["initialize_chat", "_agent_initialize_chat"])
async def test_workbench_creation_routes_project_intent_to_owner_before_any_generation(monkeypatch, entry):
    """AC-03: both production entry points create the session through the project owner."""
    from bisheng.common.services import config_service
    from bisheng.workstation.domain.schemas.chat import APIChatCompletion
    from bisheng.workstation.domain.services import chat_service

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=False)))
    monkeypatch.setattr(
        chat_service.WorkStationService,
        "aget_config",
        AsyncMock(return_value=SimpleNamespace(models=[SimpleNamespace(id="model")])),
    )
    owner = AsyncMock(side_effect=RuntimeError("stop after creation"))
    legacy_insert = AsyncMock()
    monkeypatch.setattr(chat_service.ChatSessionService, "create_owned_project_session", owner)
    monkeypatch.setattr(chat_service.MessageSessionDao, "async_insert_one", legacy_insert)
    data = APIChatCompletion(clientTimestamp="1", model="model", text="Hello", project_id=uuid4())
    user = SimpleNamespace(user_id=7, tenant_id=1)
    with pytest.raises(RuntimeError, match="stop after creation"):
        await getattr(chat_service, entry)(data, user)
    assert owner.await_count == 1
    assert owner.call_args.args[2] == data.project_id
    legacy_insert.assert_not_awaited()
