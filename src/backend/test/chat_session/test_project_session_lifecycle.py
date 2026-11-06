"""AC-03, AC-05, AC-07: first-message binding shares the session transaction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from bisheng.chat_session.domain.repositories.project_session_repository import ProjectSessionRepository
from bisheng.common.errcode.chat import ProjectUnavailableError
from bisheng.database.models.session import MessageSession
from test.chat_session.test_projects_repository import action, create
from test.chat_session.test_projects_repository import repo as _repo_fixture

repo = _repo_fixture


def test_first_message_binds_atomically_and_replay_returns_existing_chat(repo):
    repository, actor = repo
    project = create(repository, actor)
    request_id = str(uuid4())
    row = MessageSession(chat_id="first-message", name="New Chat", user_id=7, tenant_id=1, flow_type=15)
    first = ProjectSessionRepository.create(actor, row, project, request_id, {"text": "Hello"})
    assert first["replayed"] is False
    retry_row = row.model_copy(update={"chat_id": "must-not-exist"})
    retry = ProjectSessionRepository.create(actor, retry_row, project, request_id, {"text": "Hello"})
    assert retry["replayed"] is True and retry["chat_id"] == "first-message"
    assert repository.snapshot(actor)["memberships"] == [{"chat_id": "first-message", "project_id": project}]


def test_deleted_project_cannot_create_session(repo):
    repository, actor = repo
    project = create(repository, actor)
    repository.execute(actor, action("delete", project_id=project))
    with pytest.raises(ProjectUnavailableError):
        ProjectSessionRepository.create(
            actor, MessageSession(chat_id="orphan", user_id=7, tenant_id=1, flow_type=15), project, str(uuid4()), {}
        )


def test_title_version_and_soft_delete_remove_membership(repo):
    repository, actor = repo
    project = create(repository, actor)
    repository.execute(actor, action("assign", chat_id="chat-000", project_id=project))
    before = repository.version(actor)
    result = ProjectSessionRepository.rename(actor, "chat-000", "New title")
    assert int(result["revision"]) > int(before)
    skipped = ProjectSessionRepository.rename(actor, "chat-000", "Default title", only_if_default=True)
    assert skipped["changed"] is False
    ProjectSessionRepository.soft_delete(actor, "chat-000")
    assert repository.snapshot(actor)["memberships"] == []
    assert repository.conversations(actor, project_id=project)["data"] == []


@pytest.mark.parametrize("entry", ["initialize_chat", "_agent_initialize_chat"])
async def test_workbench_creation_routes_project_intent_to_owner_before_any_generation(monkeypatch, entry):
    """AC-03, AC-07: both production entry points stop on an existing first request."""
    from bisheng.common.errcode.chat import ProjectSessionExistsError
    from bisheng.common.services import config_service
    from bisheng.workstation.domain.schemas.chat import APIChatCompletion
    from bisheng.workstation.domain.services import chat_service

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=False)))
    monkeypatch.setattr(
        chat_service.WorkStationService,
        "aget_config",
        AsyncMock(return_value=SimpleNamespace(models=[SimpleNamespace(id="model")])),
    )
    owner = AsyncMock(side_effect=ProjectSessionExistsError(chat_id="existing-chat"))
    legacy_insert = AsyncMock()
    monkeypatch.setattr(chat_service.ChatSessionService, "create_owned_project_session", owner)
    monkeypatch.setattr(chat_service.MessageSessionDao, "async_insert_one", legacy_insert)
    data = APIChatCompletion(
        clientTimestamp="1", model="model", text="Hello", project_id=uuid4(), project_request_id=uuid4()
    )
    user = SimpleNamespace(user_id=7, tenant_id=1)
    with pytest.raises(ProjectSessionExistsError):
        await getattr(chat_service, entry)(data, user)
    assert owner.await_count == 1
    assert owner.call_args.args[2:4] == (data.project_id, data.project_request_id)
    assert owner.call_args.args[4]["text"] == "Hello"
    legacy_insert.assert_not_awaited()
