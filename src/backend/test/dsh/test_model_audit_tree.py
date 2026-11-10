"""AC-H01/H02/H03/H05/H07/H08: isolated metadata projection, never production data."""

from datetime import timedelta

from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeNode, DshAuditTreePath
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Repository
from test.dsh.model_audit_fixtures import NOW, audit_database, audit_session
from test.dsh.test_model_audit_groups import row


def add(session, request, conversation, *, parent=None, origin="main", user=20, **values):
    record = row(
        "e2e-tree-" + request,
        conversation=conversation,
        user=user,
        session_origin=origin,
        parent_conversation_id=parent,
        **values,
    )
    session.add(record)
    session.flush()
    Repository(session).project_request(record.request_id, now=NOW)
    return record


def finish(repository):
    while repository.fold_hierarchy_batch()["has_more"]:
        pass
    owner = None
    for _ in range(100):
        result = repository.tree_step(owner=owner, now=NOW)
        owner = result.get("owner")
        if not result["has_more"]:
            return result
    raise AssertionError("Bounded tree build did not converge")


def nodes(repository):
    state = repository.tree_state()
    return {
        n.conversation_id: n
        for n in repository.session.exec(
            select(DshAuditTreeNode).where(DshAuditTreeNode.generation == state.active)
        ).all()
    }


def test_nested_counts_and_idempotency():
    """AC-H01/AC-H05: children keep own facts; branch counts include each once."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "parent", "parent")
        add(session, "child1", "child", origin="subagent", parent="parent")
        add(session, "child2", "child", origin="subagent", parent="parent", model_result="FAILED")
        add(session, "grand", "grand", origin="subagent", parent="child")
        repo = Repository(session)
        finish(repo)
        data = nodes(repo)
        assert data["child"].parent_key == data["parent"].conversation_key
        assert data["grand"].root_key == data["parent"].conversation_key
        assert data["parent"].request_count == 1
        assert (data["parent"].branch_count, data["parent"].branch_abnormal) == (4, 1)
        active = repo.tree_state().active
        assert repo.fold_hierarchy_batch()["examined"] == 0
        finish(repo)
        assert repo.tree_state().active == active


def test_missing_late_parent_and_conflicts():
    """AC-H03/AC-H07: late parent resolves; contradictory valid claims detach."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "child", "child", origin="subagent", parent="parent")
        repo = Repository(session)
        finish(repo)
        assert nodes(repo)["child"].relation_state == "PARENT_UNAVAILABLE"
        add(session, "parent", "parent")
        finish(repo)
        assert nodes(repo)["child"].relation_state == "LINKED"
        add(session, "conflict", "child", origin="subagent", parent="other")
        finish(repo)
        assert nodes(repo)["child"].relation_state == "CONFLICT"
        assert nodes(repo)["child"].parent_key == ""


def test_unknown_claims_abstain_but_known_origins_conflict():
    """AC-H03: old missing metadata is not a conflicting declaration or a guess."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "parent", "parent")
        add(session, "legacy", "child", origin=None)
        add(session, "valid", "child", origin="subagent", parent="parent")
        repo = Repository(session)
        finish(repo)
        assert nodes(repo)["child"].relation_state == "LINKED"
        add(session, "main", "child", origin="main")
        finish(repo)
        assert nodes(repo)["child"].relation_state == "CONFLICT"


def test_cycles_self_cross_user_and_missing_parent_remain_accessible():
    """AC-H03/AC-H06: no recursive loading or cross-owner parent resolution."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "a", "a", origin="subagent", parent="b")
        add(session, "b", "b", origin="subagent", parent="a")
        add(session, "self", "self", origin="subagent", parent="self")
        add(session, "stranger", "foreign", user=21)
        add(session, "isolated", "isolated", origin="subagent", parent="foreign")
        add(session, "noparent", "noparent", origin="subagent")
        repo = Repository(session)
        finish(repo)
        data = nodes(repo)
        assert data["a"].relation_state == data["b"].relation_state == "CYCLE"
        assert data["self"].relation_state == "SELF_REFERENCE"
        assert data["isolated"].relation_state == "PARENT_UNAVAILABLE"
        assert data["noparent"].relation_state == "MISSING_PARENT"
        assert all(not n.parent_key for n in data.values())


def test_shadow_generation_and_lease_fencing():
    """AC-H02/AC-H08: no half-built directory; expired workers cannot publish."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "parent", "parent")
        repo = Repository(session)
        repo.fold_hierarchy_batch()
        first = repo.tree_step(now=NOW)
        assert repo.tree_state().active is None
        assert repo.tree_step(now=NOW)["status"] == "BUSY"
        takeover = repo.tree_step(now=NOW + timedelta(seconds=61))
        assert takeover["owner"] != first["owner"]
        assert repo.tree_step(owner=first["owner"], now=NOW + timedelta(seconds=62))["status"] == "STALE"
        owner = takeover["owner"]
        for _ in range(20):
            result = repo.tree_step(owner=owner, now=NOW + timedelta(seconds=63))
            if not result["has_more"]:
                break
        assert repo.tree_state().active


def test_structural_change_during_copy_cannot_publish_mixed_generation():
    """AC-H07/AC-H08: a new parent invalidates an incomplete snapshot."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "child", "child", origin="subagent", parent="parent")
        repo = Repository(session)
        repo.fold_hierarchy_batch()
        first = repo.tree_step(now=NOW)
        old_build = repo.tree_state().building
        add(session, "parent", "parent")
        repo.fold_hierarchy_batch()
        result = repo.tree_step(owner=first["owner"], now=NOW)
        assert result["status"] == "RESTART"
        assert repo.tree_state().active != old_build
        finish(repo)
        assert nodes(repo)["child"].relation_state == "LINKED"


def test_depth_limit_has_standalone_entry_and_bounded_paths():
    """AC-H02/AC-H08: deep claims remain discoverable rather than recursing forever."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        for i in range(35):
            add(
                session,
                str(i),
                f"depth-{i}",
                parent=f"depth-{i - 1}" if i else None,
                origin="subagent" if i else "main",
            )
        repo = Repository(session)
        finish(repo)
        data = nodes(repo)
        assert len(data) == 35
        assert data["depth-34"].relation_state == "DEPTH_LIMIT"
        assert data["depth-34"].parent_key == ""
        assert max(session.exec(select(DshAuditTreePath.depth)).all()) <= 32


def test_unassociated_marked_processed_without_fake_group():
    """AC-H07: old requests without IDs do not keep the relation job busy forever."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        record = row("e2e-tree-unassociated", conversation=None)
        session.add(record)
        repo = Repository(session)
        assert repo.fold_hierarchy_batch()["examined"] == 1
        assert record.hierarchy_indexed
        finish(repo)
        assert not nodes(repo)
