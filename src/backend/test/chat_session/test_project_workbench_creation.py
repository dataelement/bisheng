"""AC-03: production workbench entries bind through the real Owner and SQL.

Only model/storage/telemetry boundaries are replaced. Session creation, project
membership, revision and receipt transactions all use the isolated SQL fixture.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlmodel import select

from bisheng.chat_session.domain.repositories import project_repository
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.session import MessageSession
from test.chat_session.test_projects_repository import create
from test.chat_session.test_projects_repository import repo as _repo_fixture

repo = _repo_fixture


class SessionBindingObserved(Exception):
    """Stop initialization after reading back the committed session binding."""


def prepare_owner_boundaries(monkeypatch):
    from bisheng.chat_session.domain import chat
    from bisheng.chat_session.domain.services import project_events
    from bisheng.database.models import org_snapshot

    monkeypatch.setattr(chat.UserGroupDao, "aget_user_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(org_snapshot, "astamp_session", AsyncMock())
    monkeypatch.setattr(project_events, "publish_project_change", AsyncMock(return_value="live"))


@pytest.mark.parametrize("entry", ["initialize_chat", "_agent_initialize_chat"])
async def test_real_daily_entries_commit_project_binding_before_readback(repo, monkeypatch, entry):
    from bisheng.common.services import config_service
    from bisheng.workstation.domain.schemas.chat import APIChatCompletion
    from bisheng.workstation.domain.services import chat_service

    repository, actor = repo
    project_id = create(repository, actor)
    prepare_owner_boundaries(monkeypatch)
    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=False)))
    monkeypatch.setattr(
        chat_service.WorkStationService,
        "aget_config",
        AsyncMock(return_value=SimpleNamespace(models=[SimpleNamespace(id="model")])),
    )
    monkeypatch.setattr(chat_service.telemetry_service, "log_event", AsyncMock())
    legacy_insert = AsyncMock()
    monkeypatch.setattr(chat_service.MessageSessionDao, "async_insert_one", legacy_insert)
    observed = []

    async def read_committed(chat_id):
        snapshot = repository.snapshot(actor)
        assert snapshot["memberships"] == [{"chat_id": chat_id, "project_id": project_id}]
        with tenant_execution_scope(actor.tenant_id), project_repository.get_sync_db_session() as db:
            session = db.exec(select(MessageSession).where(MessageSession.chat_id == chat_id)).one()
            assert session.user_id == actor.user_id
            assert session.tenant_id == actor.tenant_id
            assert session.flow_type == 15
        observed.append(chat_id)
        raise SessionBindingObserved()

    monkeypatch.setattr(chat_service.MessageSessionDao, "async_get_one", read_committed)
    data = APIChatCompletion(
        clientTimestamp="1", model="model", text="Hello", project_id=project_id, project_request_id=uuid4()
    )
    with pytest.raises(SessionBindingObserved):
        await getattr(chat_service, entry)(data, SimpleNamespace(user_id=actor.user_id, tenant_id=actor.tenant_id))
    assert len(observed) == 1
    legacy_insert.assert_not_awaited()


async def test_real_task_submit_commits_project_binding_before_enqueue(repo, monkeypatch):
    from bisheng.linsight.domain import utils as linsight_utils
    from bisheng.linsight.domain.services import workbench_impl
    from bisheng.workstation.domain.schemas.chat import APIChatCompletion
    from bisheng.workstation.domain.services import task_submit_service

    repository, actor = repo
    project_id = create(repository, actor)
    prepare_owner_boundaries(monkeypatch)
    monkeypatch.setattr(task_submit_service, "_consume_task_invite", AsyncMock(return_value=False))
    monkeypatch.setattr(workbench_impl.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(workbench_impl, "promote_chat_attachments", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_utils, "persist_task_user_turn", AsyncMock())
    monkeypatch.setattr(linsight_utils, "persist_task_turn_message", AsyncMock())

    async def save_version(version):
        snapshot = repository.snapshot(actor)
        assert snapshot["memberships"] == [{"chat_id": version.session_id, "project_id": project_id}]
        return version

    async def enqueue(version):
        page = repository.conversations(actor, project_id=project_id)
        assert [row["chat_id"] for row in page["data"]] == [version.session_id]
        assert page["data"][0]["flow_type"] == 15

    monkeypatch.setattr(workbench_impl.LinsightSessionVersionDao, "insert_one", save_version)
    monkeypatch.setattr(linsight_utils, "enqueue_session_for_execution", enqueue)
    data = APIChatCompletion(
        clientTimestamp="1",
        model="model",
        text="Hello",
        task_mode=True,
        project_id=project_id,
        project_request_id=uuid4(),
    )
    session, version = await task_submit_service.submit_task_turn(
        data, SimpleNamespace(user_id=actor.user_id, tenant_id=actor.tenant_id)
    )
    assert session.chat_id == version.session_id
    assert session.flow_type == 15
    assert len(repository.snapshot(actor)["memberships"]) == 1
