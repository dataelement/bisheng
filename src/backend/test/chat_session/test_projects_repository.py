"""Project operations against real SQL, including rolled-back and stale input."""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from bisheng.chat_session.domain.models.project import (
    ChatProject,
    ChatProjectMembership,
    ChatProjectReceipt,
    ChatProjectRevision,
)
from bisheng.chat_session.domain.repositories import project_repository as module
from bisheng.chat_session.domain.schemas.projects import PROJECT_ACTION_ADAPTER, ProjectActor
from bisheng.common.errcode.chat import (
    ProjectConversationError,
    ProjectRequestConflictError,
    ProjectSnapshotChangedError,
    ProjectUnavailableError,
)
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
                ChatProjectReceipt,
                ChatProjectRevision,
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
            "chat_project_receipt",
            "chat_project_revision",
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
        db.add(MessageSession(chat_id="public", user_id=7, tenant_id=1, flow_type=15, api_subject_type="public_v3"))
        db.commit()
    yield module.ProjectRepository, actor
    engine.dispose()


def action(operation, **kwargs):
    return PROJECT_ACTION_ADAPTER.validate_python({"operation": operation, "request_id": str(uuid4()), **kwargs})


def create(repo, actor, name="Project"):
    return repo.execute(actor, action("create", name=name))["outcome"]["project_id"]


def test_create_assign_delete_preserves_conversation_and_replays(repo):
    """AC-01, AC-05, AC-07: durable operations and safe replay."""
    repository, actor = repo
    request = action("create", name=" Research ", chat_id="chat-000")
    first = repository.execute(actor, request)
    assert repository.execute(actor, request)["replayed"] is True
    snapshot = repository.snapshot(actor)
    assert len(snapshot["projects"]) == 1
    assert snapshot["projects"][0]["name"] == "Research"
    project = first["outcome"]["project_id"]
    assert snapshot["memberships"] == [{"chat_id": "chat-000", "project_id": project}]
    repository.execute(actor, action("delete", project_id=project))
    assert repository.snapshot(actor)["memberships"] == []
    assert repository.execute(actor, request)["outcome"]["project_id"] == project
    assert repository.snapshot(actor)["projects"] == []
    with module.get_sync_db_session() as db:
        assert db.get(MessageSession, "chat-000").is_delete is False


def test_independent_stale_operations_survive_and_one_membership_wins(repo):
    """AC-06: per-object operations do not replace a stale whole account map."""
    repository, actor = repo
    a, b = create(repository, actor, "A"), create(repository, actor, "B")
    repository.execute(actor, action("rename", project_id=a, name="A2"))
    repository.execute(actor, action("rename", project_id=b, name="B2"))
    for project in (a, b):
        repository.execute(actor, action("assign", project_id=project, chat_id="chat-001"))
    snap = repository.snapshot(actor)
    assert {p["name"] for p in snap["projects"]} == {"A2", "B2"}
    assert snap["memberships"] == [{"chat_id": "chat-001", "project_id": b}]


def test_ownership_and_idempotency_conflicts_leave_data_unchanged(repo):
    """AC-10: knowing identifiers and matching compatibility user are insufficient."""
    repository, actor = repo
    project = create(repository, actor)
    for other in (ProjectActor(1, 8), ProjectActor(2, 7)):
        assert repository.snapshot(other)["projects"] == []
        with pytest.raises(ProjectUnavailableError):
            repository.execute(other, action("rename", project_id=project, name="stolen"))
    for chat in ("foreign", "public", "missing"):
        with pytest.raises(ProjectConversationError):
            repository.execute(actor, action("assign", project_id=project, chat_id=chat))
    request = action("create", name="once")
    repository.execute(actor, request)
    with pytest.raises(ProjectRequestConflictError):
        repository.execute(actor, request.model_copy(update={"name": "different"}))


def test_snapshot_pages_restart_on_change_and_old_members_are_queryable(repo):
    """AC-04, AC-06: complete metadata and independent history pagination."""
    repository, actor = repo
    project = create(repository, actor)
    for i in range(125):
        repository.execute(actor, action("assign", project_id=project, chat_id=f"chat-{i:03}"))
    rows, cursor = [], None
    while True:
        page = repository.conversations(actor, project_id=project, cursor=cursor, limit=40)
        rows.extend(page["data"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len({r["conversationId"] for r in rows}) == 125
    page = repository.snapshot(actor, limit=10)
    assert page["next_cursor"]
    repository.execute(actor, action("rename", project_id=project, name="new"))
    with pytest.raises(ProjectSnapshotChangedError):
        repository.snapshot(actor, cursor=page["next_cursor"], limit=10)


def test_import_preserves_cloud_edits_and_is_idempotent_across_batches(repo):
    """AC-11: entry receipts survive changed request IDs and later edits."""
    repository, actor = repo
    source = str(uuid4())
    payload = {
        "source_client_id": source,
        "projects": [{"legacy_id": "old", "name": "Legacy"}],
        "memberships": [{"chat_id": "chat-001", "legacy_project_id": "old"}],
    }
    repository.execute(actor, action("import", **payload))
    project = repository.snapshot(actor)["projects"][0]["id"]
    repository.execute(actor, action("rename", project_id=project, name="Cloud"))
    repository.execute(actor, action("assign", chat_id="chat-001", project_id=None))
    repository.execute(actor, action("import", **payload))
    snap = repository.snapshot(actor)
    assert [p["name"] for p in snap["projects"]] == ["Cloud"]
    assert snap["memberships"] == []
    repository.execute(actor, action("delete", project_id=project))
    repository.execute(actor, action("import", **payload))
    assert repository.snapshot(actor)["projects"] == []


def test_create_and_assign_roll_back_together(repo):
    """AC-05, AC-10: invalid ownership cannot leave a newly created project."""
    repository, actor = repo
    with pytest.raises(ProjectConversationError):
        repository.execute(actor, action("create", name="No orphan", chat_id="foreign"))
    assert repository.snapshot(actor)["projects"] == []
