"""Project operations against real SQL, including rolled-back and stale input."""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from bisheng.chat_session.domain.models.project import ChatProject, ChatProjectMembership
from bisheng.chat_session.domain.repositories import project_repository as module
from bisheng.chat_session.domain.schemas.projects import PROJECT_ACTION_ADAPTER, ProjectActor
from bisheng.common.errcode.chat import ProjectConversationError, ProjectUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.session import MessageSession


@pytest.fixture
def repo(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'projects.db'}")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            m.__table__
            for m in (
                ChatProject,
                ChatProjectMembership,
                MessageSession,
            )
        ],
    )
    from bisheng.core.database import tenant_filter

    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    tenant_filter.register_tenant_filter_events()
    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables
        | {
            "chat_project",
            "chat_project_membership",
            "message_session",
        },
    )

    @contextmanager
    def session():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(module, "get_sync_db_session", session)
    actor = ProjectActor(tenant_id=1, user_id=7)
    with tenant_execution_scope(1), session() as db:
        db.add_all(
            [
                MessageSession(chat_id=f"chat-{i:03}", name=f"History {i}", user_id=7, tenant_id=1, flow_type=15)
                for i in range(125)
            ]
        )
        db.add(MessageSession(chat_id="foreign", user_id=8, tenant_id=1, flow_type=15))
        db.add(MessageSession(chat_id="gone", user_id=7, tenant_id=1, flow_type=15, is_delete=True))
        db.add(MessageSession(chat_id="public", user_id=7, tenant_id=1, flow_type=15, api_subject_type="public_v3"))
        db.commit()
    yield module.ProjectRepository, actor
    engine.dispose()


def action(operation, **kwargs):
    if operation == "create":
        kwargs.setdefault("project_id", str(uuid4()))
    return PROJECT_ACTION_ADAPTER.validate_python({"operation": operation, **kwargs})


def create(repo, actor, name="Project"):
    return repo.execute(actor, action("create", name=name))["outcome"]["project_id"]


def test_create_assign_delete_preserves_conversation_and_retries_safely(repo):
    """AC-01, AC-05, AC-07: durable operations; a retried create returns the same project."""
    repository, actor = repo
    request = action("create", name=" Research ", chat_id="chat-000")
    first = repository.execute(actor, request)
    assert repository.execute(actor, request) == first
    snapshot = repository.snapshot(actor)
    assert len(snapshot["projects"]) == 1
    assert snapshot["projects"][0]["name"] == "Research"
    project = first["outcome"]["project_id"]
    assert snapshot["memberships"] == [{"chat_id": "chat-000", "project_id": project}]
    repository.execute(actor, action("delete", project_id=project))
    assert repository.snapshot(actor)["memberships"] == []
    # A late retry of the original create cannot resurrect the deleted project.
    with pytest.raises(ProjectUnavailableError):
        repository.execute(actor, request)
    assert repository.snapshot(actor)["projects"] == []
    with tenant_execution_scope(1), module.get_sync_db_session() as db:
        assert db.get(MessageSession, "chat-000").is_delete is False


def test_independent_operations_survive_and_one_membership_wins(repo):
    """AC-06: per-object operations; a conversation belongs to at most one project."""
    repository, actor = repo
    a, b = create(repository, actor, "A"), create(repository, actor, "B")
    repository.execute(actor, action("rename", project_id=a, name="A2"))
    repository.execute(actor, action("rename", project_id=b, name="B2"))
    for project in (a, b):
        repository.execute(actor, action("assign", project_id=project, chat_id="chat-001"))
    snap = repository.snapshot(actor)
    assert {p["name"] for p in snap["projects"]} == {"A2", "B2"}
    assert snap["memberships"] == [{"chat_id": "chat-001", "project_id": b}]


def test_ownership_is_enforced(repo):
    """AC-10: knowing identifiers is insufficient, including another account's project id."""
    repository, actor = repo
    project = create(repository, actor)
    for other in (ProjectActor(1, 8), ProjectActor(2, 7)):
        assert repository.snapshot(other)["projects"] == []
        with pytest.raises(ProjectUnavailableError):
            repository.execute(other, action("rename", project_id=project, name="stolen"))
        with pytest.raises(ProjectUnavailableError):
            repository.execute(other, action("create", project_id=project, name="stolen"))
    for chat in ("foreign", "public", "missing"):
        with pytest.raises(ProjectConversationError):
            repository.execute(actor, action("assign", project_id=project, chat_id=chat))


def test_project_conversations_paginate_through_old_members(repo):
    """AC-04: independent history pagination, unaffected by concurrent edits."""
    repository, actor = repo
    project = create(repository, actor)
    for i in range(125):
        repository.execute(actor, action("assign", project_id=project, chat_id=f"chat-{i:03}"))
    rows, cursor = [], None
    while True:
        page = repository.conversations(actor, project_id=project, cursor=cursor, limit=40)
        rows.extend(page["data"])
        cursor = page["next_cursor"]
        repository.execute(actor, action("rename", project_id=project, name="edited while paging"))
        if not cursor:
            break
    assert len({r["conversationId"] for r in rows}) == 125


LEGACY = {
    "projects": [
        {"legacy_id": "mine", "name": "Mine"},
        {"legacy_id": "theirs", "name": "Theirs"},
        {"legacy_id": "mixed", "name": "Mixed"},
        {"legacy_id": "empty", "name": "Empty"},
    ],
    "memberships": [
        {"chat_id": "chat-001", "legacy_project_id": "mine"},
        {"chat_id": "foreign", "legacy_project_id": "theirs"},
        {"chat_id": "chat-002", "legacy_project_id": "mixed"},
        {"chat_id": "gone", "legacy_project_id": "mixed"},
    ],
}


def statuses(outcome):
    return {(i.get("legacy_id") or i.get("chat_id")): i["status"] for i in outcome["outcome"]["items"]}


def test_import_infers_owner_from_conversations(repo):
    """AC-11/12: a legacy project goes to the account that owns its conversations."""
    repository, actor = repo
    result = statuses(repository.execute(actor, action("import", **LEGACY)))
    assert result == {
        "mine": "imported",
        "theirs": "not_owned",
        "mixed": "imported",
        "gone": "conversation_unavailable",
        "empty": "not_owned",
    }
    snap = repository.snapshot(actor)
    assert sorted(p["name"] for p in snap["projects"]) == ["Mine", "Mixed"]
    assert sorted(m["chat_id"] for m in snap["memberships"]) == ["chat-001", "chat-002"]
    # The other account in the same browser gets only the project holding its conversation.
    other = ProjectActor(1, 8)
    assert statuses(repository.execute(other, action("import", **LEGACY)))["theirs"] == "imported"
    other_snap = repository.snapshot(other)
    assert [p["name"] for p in other_snap["projects"]] == ["Theirs"]
    assert other_snap["memberships"][0]["chat_id"] == "foreign"


def test_import_is_idempotent_and_never_overrides_cloud_edits(repo):
    """AC-11: re-import after rename, move-out or delete changes nothing."""
    repository, actor = repo
    payload = {
        "projects": [{"legacy_id": "old", "name": "Legacy"}],
        "memberships": [{"chat_id": "chat-001", "legacy_project_id": "old"}],
    }
    repository.execute(actor, action("import", **payload))
    project = repository.snapshot(actor)["projects"][0]["id"]
    repository.execute(actor, action("rename", project_id=project, name="Cloud"))
    repository.execute(actor, action("assign", chat_id="chat-001", project_id=None))
    assert statuses(repository.execute(actor, action("import", **payload))) == {"old": "already_imported"}
    snap = repository.snapshot(actor)
    assert [p["name"] for p in snap["projects"]] == ["Cloud"]
    assert snap["memberships"] == []
    repository.execute(actor, action("delete", project_id=project))
    repository.execute(actor, action("import", **payload))
    assert repository.snapshot(actor)["projects"] == []


def test_import_keeps_existing_cloud_membership(repo):
    """AC-11: a conversation already in a cloud project stays there."""
    repository, actor = repo
    cloud = create(repository, actor, "Cloud")
    repository.execute(actor, action("assign", chat_id="chat-001", project_id=cloud))
    payload = {
        "projects": [{"legacy_id": "old", "name": "Legacy"}],
        "memberships": [
            {"chat_id": "chat-001", "legacy_project_id": "old"},
            {"chat_id": "chat-003", "legacy_project_id": "old"},
        ],
    }
    result = statuses(repository.execute(actor, action("import", **payload)))
    assert result == {"old": "imported", "chat-001": "cloud_membership_kept"}
    members = {m["chat_id"]: m["project_id"] for m in repository.snapshot(actor)["memberships"]}
    assert members["chat-001"] == cloud


def test_create_and_assign_roll_back_together(repo):
    """AC-05, AC-10: invalid ownership cannot leave a newly created project."""
    repository, actor = repo
    with pytest.raises(ProjectConversationError):
        repository.execute(actor, action("create", name="No orphan", chat_id="foreign"))
    assert repository.snapshot(actor)["projects"] == []
