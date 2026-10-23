"""Coverage AC: AC-39, AC-41, AC-47, AC-48, AC-52, AC-53, AC-55.

Real request/group projection, hierarchy folding and committed shadow generations.
SQLite covers sequencing and fencing contracts, not dual-DB concurrent locking.
Final query/DTO safety readiness belongs to its later dedicated query tasks.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import select

from bisheng.database.models.tenant import Tenant
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeNode as Node
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeState as State
from bisheng.dsh.domain.repositories import content_safety_projection
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Repository
from bisheng.dsh.domain.schemas.model_audit_status import refresh_audit_status
from test.dsh.test_content_safety_groups import native, project
from test.dsh.test_content_safety_merge import committed_merge, output_event
from test.dsh.test_content_safety_repository import tenant_session


def action(engine, callback, *, tenant=101):
    with tenant_session(engine, tenant) as session, session.begin():
        return callback(Repository(session))


def add_native(engine, factory, conversation, *, parent=None, hit=False, abnormal=False):
    row = native(
        factory,
        conversation=conversation,
        session_origin="subagent" if parent else "main",
        parent_conversation_id=parent,
        has_sensitive_hit=hit,
        input_sensitive_hit=hit,
        output_sensitive_hit=hit,
        content_safety_state="BLOCKED" if hit else "UNREPORTED",
        model_result="FAILED" if abnormal else "SUCCEEDED",
    )
    with tenant_session(engine) as session, session.begin():
        session.add(row)
    assert project(engine, row.request_id)
    return row


def fold(engine):
    for _ in range(10):
        result = action(engine, lambda repo: repo.fold_hierarchy_batch(limit=100))
        if not result["has_more"]:
            return result
    raise AssertionError("Synthetic hierarchy input exceeds finite fixture bounds")


def step(engine, now, *, owner=None, limit=100):
    return action(engine, lambda repo: repo.tree_step(owner=owner, now=now, limit=limit))


def finish(engine, now, *, owner=None):
    fold(engine)
    for _ in range(100):
        result = step(engine, now, owner=owner)
        owner = result.get("owner")
        if not result["has_more"]:
            return result
    raise AssertionError("Finite shadow generation did not converge")


def state(engine):
    return action(engine, lambda repo: repo.tree_state())


def active_nodes(engine):
    def read(repo):
        current = repo.tree_state()
        return {
            node.conversation_id: node
            for node in repo.session.exec(select(Node).where(Node.generation == current.active)).all()
        }

    return action(engine, read)


def assert_published_safety(engine):
    current = state(engine)
    assert current.active and current.phase == "IDLE"
    assert current.published_safety_summary_revision == current.safety_summary_revision
    assert action(engine, lambda repo: repo.tree_progress())["summary_ready"] is True


def test_real_group_counts_fold_into_parent_own_and_branch_hits_once(
    content_safety_engine, content_safety_native_audit, content_safety_clock
):
    engine = content_safety_engine
    add_native(engine, content_safety_native_audit, "parent")
    add_native(engine, content_safety_native_audit, "child", parent="parent", hit=True)
    add_native(engine, content_safety_native_audit, "grandchild", parent="child", hit=True)
    add_native(engine, content_safety_native_audit, "sibling", parent="parent", abnormal=True)
    finish(engine, content_safety_clock.now())
    nodes = active_nodes(engine)
    assert (nodes["parent"].own_sensitive_hit_count, nodes["parent"].branch_sensitive_hit_count) == (0, 2)
    assert (nodes["child"].own_sensitive_hit_count, nodes["child"].branch_sensitive_hit_count) == (1, 2)
    assert (nodes["grandchild"].own_sensitive_hit_count, nodes["grandchild"].branch_sensitive_hit_count) == (1, 1)
    assert (nodes["sibling"].own_sensitive_hit_count, nodes["sibling"].branch_sensitive_hit_count) == (0, 0)
    assert nodes["parent"].request_count == 1 and nodes["parent"].branch_count == 4
    assert nodes["parent"].branch_abnormal == 1
    assert nodes["child"].parent_key == nodes["parent"].conversation_key
    assert nodes["grandchild"].root_key == nodes["parent"].conversation_key
    assert_published_safety(engine)


def test_repeated_build_and_duplicate_safety_event_do_not_add_hits(
    content_safety_engine, content_safety_event, content_safety_clock
):
    engine = content_safety_engine
    raw = content_safety_event()
    _, external, _ = committed_merge(engine, content_safety_projection, raw)
    assert project(engine, external.request_id)
    finish(engine, content_safety_clock.now())
    generation = state(engine).active
    committed_merge(engine, content_safety_projection, raw)
    assert not project(engine, external.request_id)
    finish(engine, content_safety_clock.now())
    assert state(engine).active == generation
    node = active_nodes(engine)["synthetic-conversation"]
    assert (
        node.request_count == node.branch_count == node.own_sensitive_hit_count == node.branch_sensitive_hit_count == 1
    )
    assert node.abnormal_count == node.branch_abnormal == 0
    assert_published_safety(engine)


def test_only_external_not_applicable_rows_can_publish_without_body_or_execution_evidence(
    content_safety_engine, content_safety_event, content_safety_clock
):
    engine = content_safety_engine
    raw = content_safety_event(session_id=None)
    _, external, _ = committed_merge(engine, content_safety_projection, raw)
    assert project(engine, external.request_id)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _execution_context, _many):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        finish(engine, content_safety_clock.now())
        assert_published_safety(engine)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    forbidden = ("dsh_model_audit_content", "dsh_model_audit_manifest", "dsh_model_audit_evidence", "dsh_model_call")
    assert not any(table in sql for sql in statements for table in forbidden)
    node = active_nodes(engine)["synthetic-conversation"]
    assert node.branch_sensitive_hit_count == 1 and node.branch_abnormal == 0
    with tenant_session(engine) as session:
        saved = session.get(Request, external.request_id)
        assert saved.audit_status == "NOT_APPLICABLE" and saved.effective_mode is None
        assert saved.model_result is None and saved.usage_settlement is None and saved.model_started_at is None


def test_worker_stopped_before_first_generation_remains_preparing(content_safety_engine, content_safety_event):
    engine = content_safety_engine
    raw = content_safety_event()
    _, external, _ = committed_merge(engine, content_safety_projection, raw)
    # Persist the actual request-to-group safety dirty state; run no tree worker.
    assert project(engine, external.request_id)
    current = state(engine)
    assert current.active is None and current.safety_summary_revision > current.published_safety_summary_revision
    progress = action(engine, lambda repo: repo.tree_progress())
    assert progress["phase"] == "PREPARING" and not progress["summary_ready"]
    assert progress["generation"] is None


def test_safety_watermark_alone_invalidates_published_readiness(
    content_safety_engine, content_safety_native_audit, content_safety_clock
):
    engine = content_safety_engine
    add_native(engine, content_safety_native_audit, "parent")
    finish(engine, content_safety_clock.now())

    # Represent an already published generation and a separately persisted safety revision.
    def safety_dirty(repo):
        current = repo.tree_state(lock=True)
        current.published_safety_summary_revision = current.safety_summary_revision
        current.safety_summary_revision += 1
        repo.session.add(current)

    action(engine, safety_dirty)
    progress = action(engine, lambda repo: repo.tree_progress())
    assert progress["phase"] == "UPDATING" and progress["summary_ready"] is False


@pytest.mark.parametrize("interrupted_phase", ["COPY", "PUBLISH"])
def test_late_hit_with_unchanged_structure_restarts_shadow_instead_of_publishing_mixed_summary(
    content_safety_engine, content_safety_event, content_safety_native_audit, content_safety_clock, interrupted_phase
):
    engine, now = content_safety_engine, content_safety_clock.now()
    add_native(engine, content_safety_native_audit, "parent")
    child = add_native(engine, content_safety_native_audit, "child", parent="parent")
    fold(engine)
    result = step(engine, now)
    owner = result["owner"]
    old_build, structure = state(engine).building, state(engine).revision
    if interrupted_phase == "PUBLISH":
        for _ in range(20):
            result = step(engine, now, owner=owner)
            if state(engine).phase == "PUBLISH":
                break
        assert state(engine).phase == "PUBLISH"
    raw = output_event(content_safety_event, backend_request_id=child.request_id)
    committed_merge(engine, content_safety_projection, raw)
    assert project(engine, child.request_id)
    assert state(engine).revision == structure
    result = step(engine, now, owner=owner)
    assert result["status"] == "RESTART"
    assert state(engine).active != old_build
    finish(engine, now)
    current = state(engine)
    assert current.active != old_build
    nodes = active_nodes(engine)
    assert nodes["parent"].branch_sensitive_hit_count == nodes["child"].own_sensitive_hit_count == 1
    assert_published_safety(engine)


def test_safety_only_dirty_revision_triggers_new_generation(
    content_safety_engine, content_safety_native_audit, content_safety_clock
):
    engine = content_safety_engine
    add_native(engine, content_safety_native_audit, "legacy")
    finish(engine, content_safety_clock.now())
    old = state(engine).active

    def dirty(repo):
        current = repo.tree_state(lock=True)
        current.published_safety_summary_revision = current.safety_summary_revision
        current.safety_summary_revision += 1
        repo.session.add(current)

    action(engine, dirty)
    finish(engine, content_safety_clock.now())
    assert state(engine).active != old
    assert_published_safety(engine)


def test_expired_build_owner_cannot_publish_safety_revision(
    content_safety_engine, content_safety_event, content_safety_clock
):
    engine, now = content_safety_engine, content_safety_clock.now()
    _, external, _ = committed_merge(engine, content_safety_projection, content_safety_event())
    assert project(engine, external.request_id)
    fold(engine)
    first = step(engine, now)
    assert state(engine).build_safety_summary_revision == state(engine).safety_summary_revision
    before = state(engine).published_safety_summary_revision
    assert step(engine, now + timedelta(seconds=61), owner=first["owner"])["status"] == "STALE"
    assert state(engine).active is None and state(engine).published_safety_summary_revision == before
    takeover = step(engine, now + timedelta(seconds=62))
    assert takeover["owner"] != first["owner"]
    assert step(engine, now + timedelta(seconds=63), owner=first["owner"])["status"] == "STALE"
    finish(engine, now + timedelta(seconds=63), owner=takeover["owner"])
    assert_published_safety(engine)


def test_unassociated_external_does_not_keep_empty_tree_permanently_dirty(
    content_safety_engine, content_safety_event, content_safety_clock
):
    engine = content_safety_engine
    _, external, _ = committed_merge(engine, content_safety_projection, content_safety_event(conversation=None))
    # Without an associated conversation the merge already leaves group pending clear.
    assert not project(engine, external.request_id)
    finish(engine, content_safety_clock.now())
    assert active_nodes(engine) == {}
    assert_published_safety(engine)
    with tenant_session(engine) as session:
        saved = session.get(Request, external.request_id)
        assert saved.hierarchy_indexed and not saved.group_index_pending


@pytest.mark.parametrize("status", ["disabled", "archived"])
def test_pending_tenant_enumeration_includes_disabled_history_for_late_safety_facts(
    content_safety_engine, content_safety_event, status
):
    engine = content_safety_engine
    Tenant.__table__.create(engine, checkfirst=True)
    with tenant_session(engine) as session, session.begin():
        session.add(Tenant(id=101, tenant_code="synthetic-tree-101", tenant_name="Synthetic history", status=status))
        session.add(Tenant(id=202, tenant_code="synthetic-tree-202", tenant_name="Synthetic idle", status="active"))
    _, external, _ = committed_merge(engine, content_safety_projection, content_safety_event())
    assert project(engine, external.request_id)
    fold(engine)
    pending = action(engine, lambda repo: repo.tree_pending_tenants())
    assert pending == [101] and all(type(tenant) is int for tenant in pending)
    assert action(engine, lambda repo: repo.tree_pending_tenants(cursor=101)) == []


def test_pending_enumeration_includes_safety_only_unpublished_watermark(content_safety_engine):
    engine = content_safety_engine
    Tenant.__table__.create(engine, checkfirst=True)
    with tenant_session(engine) as session, session.begin():
        session.add(Tenant(id=101, tenant_code="synthetic-watermark", tenant_name="Synthetic", status="disabled"))
        session.add(
            State(
                tenant_id=101,
                active=str(uuid4()),
                revision=2,
                published_revision=2,
                summary_revision=3,
                published_summary_revision=3,
                safety_summary_revision=5,
                published_safety_summary_revision=4,
                phase="IDLE",
            )
        )
    assert action(engine, lambda repo: repo.tree_pending_tenants()) == [101]


def test_legacy_unknown_check_stays_unknown_and_does_not_become_model_abnormality(
    content_safety_engine, content_safety_native_audit, content_safety_clock
):
    engine = content_safety_engine
    request = add_native(engine, content_safety_native_audit, "legacy")
    finish(engine, content_safety_clock.now())
    node = active_nodes(engine)["legacy"]
    assert node.request_count == node.branch_count == 1
    assert node.own_sensitive_hit_count == node.branch_sensitive_hit_count == node.branch_abnormal == 0
    with tenant_session(engine) as session:
        saved = session.get(Request, request.request_id)
        assert saved.content_safety_state == saved.input_safety_state == saved.output_safety_state == "UNREPORTED"
        assert not saved.has_sensitive_hit and saved.audit_status == "NORMAL"


def test_model_summary_revision_change_also_prevents_mixed_generation_publication(
    content_safety_engine, content_safety_native_audit, content_safety_clock
):
    engine, now = content_safety_engine, content_safety_clock.now()
    request = add_native(engine, content_safety_native_audit, "model-summary")
    fold(engine)
    first = step(engine, now)
    owner, old_build = first["owner"], state(engine).building
    for _ in range(20):
        step(engine, now, owner=owner)
        if state(engine).phase == "PUBLISH":
            break
    assert state(engine).phase == "PUBLISH"
    safety_revision = state(engine).safety_summary_revision
    with tenant_session(engine) as session, session.begin():
        row = session.get(Request, request.request_id)
        row.model_result = "FAILED"
        refresh_audit_status(row)
        session.add(row)
    assert project(engine, request.request_id)
    assert state(engine).safety_summary_revision == safety_revision
    assert step(engine, now, owner=owner)["status"] == "RESTART"
    finish(engine, now)
    assert state(engine).active != old_build
    node = active_nodes(engine)["model-summary"]
    assert node.branch_abnormal == node.abnormal_count == 1
    assert node.branch_sensitive_hit_count == node.own_sensitive_hit_count == 0
    assert state(engine).published_summary_revision == state(engine).summary_revision
    assert_published_safety(engine)


@pytest.mark.parametrize("status", ["disabled", "archived"])
def test_optional_group_pending_scan_finds_published_late_hit_without_changing_legacy_default(
    content_safety_engine, content_safety_native_audit, content_safety_event, content_safety_clock, status
):
    engine = content_safety_engine
    Tenant.__table__.create(engine, checkfirst=True)
    with tenant_session(engine) as session, session.begin():
        session.add(Tenant(id=101, tenant_code="late-group-101", tenant_name="Synthetic history", status=status))
        session.add(Tenant(id=202, tenant_code="late-group-202", tenant_name="Synthetic idle", status="active"))
    row = add_native(engine, content_safety_native_audit, "published-late-hit")
    finish(engine, content_safety_clock.now())
    before = state(engine)
    published = (
        before.active,
        before.revision,
        before.published_revision,
        before.summary_revision,
        before.published_summary_revision,
        before.safety_summary_revision,
        before.published_safety_summary_revision,
    )
    raw = output_event(
        content_safety_event,
        backend_request_id=row.request_id,
        event_kind="FINAL",
        drain_status="FINISHED",
        conversation={"conversation_id": "published-late-hit", "session_origin": "main", "request_kind": "chat"},
    )
    committed_merge(engine, content_safety_projection, raw)
    after = state(engine)
    assert (
        after.active,
        after.revision,
        after.published_revision,
        after.summary_revision,
        after.published_summary_revision,
        after.safety_summary_revision,
        after.published_safety_summary_revision,
    ) == published
    with tenant_session(engine) as session:
        saved = session.get(Request, row.request_id)
        assert saved.hierarchy_indexed and saved.group_index_pending and saved.has_sensitive_hit
    assert action(engine, lambda repo: repo.tree_pending_tenants()) == []
    assert action(engine, lambda repo: repo.tree_pending_tenants(include_group_pending=False)) == []
    assert action(engine, lambda repo: repo.tree_pending_tenants(include_group_pending=True)) == [101]
    assert action(engine, lambda repo: repo.tree_pending_tenants(cursor=101, include_group_pending=True)) == []
    assert project(engine, row.request_id)
    finish(engine, content_safety_clock.now())
    assert active_nodes(engine)["published-late-hit"].own_sensitive_hit_count == 1
    assert action(engine, lambda repo: repo.tree_pending_tenants(include_group_pending=True)) == []


def test_group_pending_scan_excludes_running_models_with_clean_published_directory(
    content_safety_engine, content_safety_native_audit, content_safety_clock
):
    engine = content_safety_engine
    Tenant.__table__.create(engine, checkfirst=True)
    with tenant_session(engine) as session, session.begin():
        session.add(Tenant(id=101, tenant_code="running-clean-101", tenant_name="Synthetic running"))
        row = native(
            content_safety_native_audit,
            conversation="still-running",
            session_origin="main",
            model_result="RUNNING",
            response_result="RUNNING",
            usage_settlement="PENDING",
        )
        session.add(row)
    assert project(engine, row.request_id)
    finish(engine, content_safety_clock.now())
    assert_published_safety(engine)
    with tenant_session(engine) as session:
        saved = session.get(Request, row.request_id)
        assert saved.model_result == "RUNNING" and saved.hierarchy_indexed and not saved.group_index_pending
        assert Repository.pending_tenants(session) == [101]
    assert action(engine, lambda repo: repo.tree_pending_tenants()) == []
    assert action(engine, lambda repo: repo.tree_pending_tenants(include_group_pending=True)) == []


def test_group_pending_scan_keeps_id_only_bounded_tenant_keyset(content_safety_engine, content_safety_native_audit):
    engine = content_safety_engine
    Tenant.__table__.create(engine, checkfirst=True)
    for tenant in range(101, 202):
        with tenant_session(engine, tenant) as session, session.begin():
            session.add(
                Tenant(
                    id=tenant, tenant_code=f"group-keyset-{tenant}", tenant_name="Synthetic dirty", status="disabled"
                )
            )
            # A native row may finish hierarchy folding before its independent group projection.
            session.add(
                content_safety_native_audit(
                    tenant_id=tenant, user_id=11, hierarchy_indexed=True, group_index_pending=True
                )
            )
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        first = action(engine, lambda repo: repo.tree_pending_tenants(include_group_pending=True))
        assert first == list(range(101, 201)) and all(type(value) is int for value in first)
        assert action(engine, lambda repo: repo.tree_pending_tenants(cursor=first[-1], include_group_pending=True)) == [
            201
        ]
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 2
    assert all(
        sql.startswith("select tenant.id") and "limit" in sql and "exists (" in sql for sql in statements
    )
    assert not any(token in sql for sql in statements for token in ("count(", "distinct", "group by"))
