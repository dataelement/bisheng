"""AC-H02/H04/H05/H06/H08: exact filters and stable independent tree pagination."""

import pytest

from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Repository
from test.dsh.model_audit_fixtures import audit_database, audit_session
from test.dsh.test_model_audit_groups import row
from test.dsh.test_model_audit_tree import add, finish


def test_roots_children_and_child_only_match():
    """AC-H01/AC-H04: only matching child requests expose their nonmatching parent path."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "parent", "parent", name="Provider / P")
        add(session, "child", "child", parent="parent", origin="subagent", name="Provider / C", model_result="FAILED")
        add(session, "other", "other")
        repo = Repository(session)
        finish(repo)
        roots = repo.tree_page(model_name="Provider / C", audit_status="ABNORMAL")
        assert [n["conversation_id"] for n in roots["items"]] == ["parent"]
        parent = roots["items"][0]
        assert parent["match_scope"] == "DESCENDANT"
        assert parent["own_summary"]["request_count"] == 1
        assert parent["branch_summary"]["abnormal_count"] == 1
        children = repo.tree_page(
            parent_key=parent["conversation_key"], generation=parent["generation"], model_name="Provider / C"
        )
        assert [n["conversation_id"] for n in children["items"]] == ["child"]
        assert children["items"][0]["match_scope"] == "SELF"
        exact = repo.tree_page(conversation_id="child")
        assert [n["conversation_id"] for n in exact["items"]] == ["parent"]
        assert not repo.tree_page(model_name="Provider / P", audit_status="ABNORMAL")["items"]
        assert not repo.tree_page(model_name="provider / c")["items"]


def test_complete_paginated_root_set_and_children_do_not_duplicate():
    """AC-H02: compare the complete expected set, not merely absence of duplicates."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        for i in range(12):
            add(session, f"p{i}", f"parent-{i}")
            add(session, f"c{i}", f"child-{i}", parent=f"parent-{i}", origin="subagent")
        repo = Repository(session)
        finish(repo)
        keys, cursor = [], None
        for _ in range(20):
            page = repo.tree_page(limit=3, cursor=cursor)
            keys.extend(n["conversation_id"] for n in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert len(keys) == 12
        assert set(keys) == {f"parent-{i}" for i in range(12)}


def test_resume_inside_branch_does_not_skip_candidate():
    """AC-H04/AC-H08: empty scan-limited pages retain the current candidate."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "p", "parent")
        for i in range(8):
            add(session, f"c{i}", f"child-{i}", parent="parent", origin="subagent", name=f"Provider / {i}")
        repo = Repository(session)
        finish(repo)
        cursor, found = None, []
        for _ in range(20):
            result = repo.tree_page(model_name="Provider / 7", scan_budget=1, cursor=cursor)
            found.extend(n["conversation_id"] for n in result["items"])
            cursor = result["next_cursor"]
            if cursor is None:
                break
        assert found == ["parent"]


def test_cursor_scope_location_and_old_generation_refresh():
    """AC-H02/AC-H06/AC-H07: cursor is bound to query/tenant and retained generation."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        add(session, "p", "parent")
        add(session, "c", "child", origin="subagent", parent="parent")
        add(session, "extra", "extra")
        repo = Repository(session)
        finish(repo)
        first = repo.tree_page(limit=1)
        assert first["next_cursor"]
        with pytest.raises(ValueError):
            repo.tree_page(cursor=first["next_cursor"], model_name="Other")
        root = repo.tree_page(conversation_id="child")["items"][0]
        child = repo.tree_page(parent_key=root["conversation_key"])["items"][0]
        location = repo.tree_location(child["conversation_key"])
        assert [n["conversation_id"] for n in location["items"]] == ["parent", "child"]
        for i in range(2):
            add(session, f"new{i}", f"new-{i}")
            finish(repo)
        assert repo.tree_page(cursor=first["next_cursor"])["progress"]["refresh_required"]
        with audit_session(engine, tenant_id=3) as other:
            with pytest.raises(ValueError):
                Repository(other).tree_page(cursor=first["next_cursor"])


def test_preparing_and_summary_dirty_are_not_empty_or_normal_claims():
    """AC-H05/AC-H07: unknown summary is not zero and old data remains reachable."""
    with audit_database() as engine, audit_session(engine) as session, session.begin():
        repo = Repository(session)
        assert repo.tree_page()["progress"]["hierarchy_ready"] is False
        add(session, "p", "parent")
        finish(repo)
        add(session, "late", "parent", model_result="FAILED")
        old = repo.tree_page()["items"][0]
        assert old["branch_summary"]["ready"] is False
        assert old["branch_summary"]["abnormal_count"] is None
        finish(repo)
        assert repo.tree_page()["items"][0]["branch_summary"]["abnormal_count"] == 1
        session.add(row("e2e-tree-waiting-count", conversation="parent", model_result="FAILED"))
        repo.fold_hierarchy_batch()
        # Relation folding can precede the independent request-count projection.
        pending = repo.tree_page()
        assert pending["progress"]["phase"] == "UPDATING"
        assert pending["items"][0]["branch_summary"]["ready"] is False
        assert pending["items"][0]["branch_summary"]["abnormal_count"] is None
        repo.project_request("e2e-tree-waiting-count")
        finish(repo)
        assert repo.tree_page()["items"][0]["branch_summary"]["abnormal_count"] == 2
