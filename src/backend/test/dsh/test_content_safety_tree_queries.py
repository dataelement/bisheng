"""Coverage AC: AC-45, AC-47, AC-48, AC-49, AC-50.

Real request-to-group projection and shadow tree publication precede each query.
SQLite checks bounded query semantics, not MySQL/DM8 plans or concurrent locks.
"""

from datetime import timedelta
from hashlib import sha256

import pytest
from sqlalchemy import event

from bisheng.dsh.domain.repositories.model_audit_queries import (
    DshModelAuditQueryRepository as Repository,
)
from bisheng.dsh.domain.schemas.model_audit_status import refresh_audit_status
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key
from test.dsh.model_audit_fixtures import audit_database
from test.dsh.test_content_safety_repository import tenant_session


@pytest.fixture
def query_engine():
    with audit_database() as engine:
        yield engine


def add(
    session,
    factory,
    now,
    conversation,
    *,
    tenant=101,
    user=11,
    model="Model A",
    days=1,
    direction=None,
    state=None,
    parent=None,
    **changes,
):
    hit = direction is not None
    started = now - timedelta(days=days)
    values = {
        "tenant_id": tenant,
        "user_id": user,
        "model_name": model,
        "model_name_digest": sha256(model.encode()).hexdigest(),
        "conversation_id": conversation,
        "conversation_id_digest": sha256(conversation.encode()).hexdigest(),
        "conversation_key": conversation_key(tenant, user, conversation),
        "association_status": "ASSOCIATED",
        "session_origin": "subagent" if parent else "main",
        "parent_conversation_id": parent,
        "started_at": started,
        "model_started_at": started,
        "model_result": "SUCCEEDED",
        "response_result": "COMPLETED",
        "usage_settlement": "SETTLED",
        "content_status": "NOT_CAPTURED",
        "has_sensitive_hit": hit,
        "input_sensitive_hit": direction in {"INPUT", "BOTH"},
        "input_safety_state": "BLOCKED" if direction in {"INPUT", "BOTH"} else "UNREPORTED",
        "output_sensitive_hit": direction in {"OUTPUT", "BOTH"},
        "output_safety_state": "BLOCKED" if direction in {"OUTPUT", "BOTH"} else "UNREPORTED",
        "content_safety_state": state or ("BLOCKED" if hit else "UNREPORTED"),
    }
    values.update(changes)
    row = factory(**values)
    refresh_audit_status(row)
    session.add(row)
    session.flush()
    assert Repository(session).project_request(row.request_id, now=now - timedelta(seconds=1))
    return row


def publish(session, now):
    repository = Repository(session)
    for _ in range(20):
        if not repository.fold_hierarchy_batch(limit=100)["has_more"]:
            break
    else:
        raise AssertionError("Finite synthetic hierarchy did not fold")
    owner = None
    for _ in range(100):
        result = repository.tree_step(owner=owner, now=now, limit=100)
        owner = result.get("owner")
        if not result["has_more"]:
            assert repository.tree_progress()["summary_ready"]
            return repository
    raise AssertionError("Finite synthetic tree did not publish")


def page(repository, mode, **query):
    return getattr(repository, "group_page" if mode == "groups" else "tree_page")(**query)


def conversations(result):
    return {item["conversation_id"] for item in result["items"]}


def window(now, days=7):
    return {
        "start_at": (now - timedelta(days=days)).replace(tzinfo=None),
        "end_at": now.replace(tzinfo=None),
    }


@pytest.mark.parametrize("mode", ["groups", "tree"])
def test_last_month_hit_cannot_join_yesterday_clean_request(
    query_engine, content_safety_native_audit, content_safety_clock, mode
):
    now = content_safety_clock.now()
    with tenant_session(query_engine) as session, session.begin():
        add(
            session,
            content_safety_native_audit,
            now,
            "mixed",
            days=30,
            direction="INPUT",
        )
        add(session, content_safety_native_audit, now, "mixed")
        add(session, content_safety_native_audit, now, "recent-hit", direction="INPUT")
        repository = publish(session, now)
        result = page(repository, mode, has_sensitive_hit=True, **window(now))
        assert conversations(result) == {"recent-hit"}
        assert result["scan_limited"] is False
        assert conversations(page(repository, mode, has_sensitive_hit=False, **window(now))) == {"mixed"}


@pytest.mark.parametrize("mode", ["groups", "tree"])
def test_user_model_direction_and_state_must_match_one_request(
    query_engine, content_safety_native_audit, content_safety_clock, mode
):
    now = content_safety_clock.now()
    with tenant_session(query_engine) as session, session.begin():
        add(
            session,
            content_safety_native_audit,
            now,
            "split",
            model="Model A",
            direction="INPUT",
        )
        add(
            session,
            content_safety_native_audit,
            now,
            "split",
            model="Model B",
            direction="OUTPUT",
        )
        add(
            session,
            content_safety_native_audit,
            now,
            "both",
            model="Model A",
            direction="BOTH",
        )
        add(
            session,
            content_safety_native_audit,
            now,
            "wrong-user",
            user=22,
            direction="BOTH",
        )
        repository = publish(session, now)
        query = {
            "user_id": 11,
            "model_name": "Model A",
            "sensitive_direction": "BOTH",
            "content_safety_state": "BLOCKED",
            **window(now),
        }
        assert conversations(page(repository, mode, **query)) == {"both"}
        query["model_name"] = "Model B"
        assert not page(repository, mode, **query)["items"]
        query.update(
            model_name="Model A",
            sensitive_direction="OUTPUT",
            content_safety_state="PASSED",
        )
        assert not page(repository, mode, **query)["items"]


@pytest.mark.parametrize("mode", ["groups", "tree"])
def test_direction_intersection_and_false_hit_preserve_unknown_semantics(
    query_engine, content_safety_native_audit, content_safety_clock, mode
):
    now = content_safety_clock.now()
    with tenant_session(query_engine) as session, session.begin():
        for direction in ("INPUT", "OUTPUT", "BOTH"):
            add(
                session,
                content_safety_native_audit,
                now,
                direction,
                direction=direction,
            )
        add(session, content_safety_native_audit, now, "legacy")
        add(session, content_safety_native_audit, now, "passed", state="PASSED")
        repository = publish(session, now)
        for direction, expected in (
            ("INPUT", {"INPUT", "BOTH"}),
            ("OUTPUT", {"OUTPUT", "BOTH"}),
            ("BOTH", {"BOTH"}),
        ):
            assert conversations(page(repository, mode, sensitive_direction=direction, **window(now))) == expected
        assert conversations(page(repository, mode, has_sensitive_hit=False, **window(now))) == {"legacy", "passed"}
        assert conversations(page(repository, mode, content_safety_state="PASSED", **window(now))) == {"passed"}


@pytest.mark.parametrize("mode", ["groups", "tree"])
def test_all_six_safety_states_are_independent_of_model_status(
    query_engine, content_safety_native_audit, content_safety_clock, mode
):
    now = content_safety_clock.now()
    states = ("UNREPORTED", "PASSED", "BLOCKED", "ERROR", "DISABLED", "NOT_APPLICABLE")
    with tenant_session(query_engine) as session, session.begin():
        for state in states:
            add(
                session,
                content_safety_native_audit,
                now,
                state,
                state=state,
                direction="INPUT" if state == "BLOCKED" else None,
            )
        repository = publish(session, now)
        for state in states:
            result = page(
                repository,
                mode,
                content_safety_state=state,
                audit_status="NORMAL",
                **window(now),
            )
            assert conversations(result) == {state}
            assert all(item["abnormal_count"] == 0 for item in result["items"])


def test_descendant_hit_preserves_parent_path_but_not_other_request_cross_products(
    query_engine, content_safety_native_audit, content_safety_clock
):
    now = content_safety_clock.now()
    with tenant_session(query_engine) as session, session.begin():
        add(session, content_safety_native_audit, now, "parent", model="Model A")
        add(
            session,
            content_safety_native_audit,
            now,
            "child",
            parent="parent",
            model="Model B",
            direction="BOTH",
        )
        add(
            session,
            content_safety_native_audit,
            now,
            "grandchild",
            parent="child",
            direction="INPUT",
        )
        repository = publish(session, now)
        query = {"has_sensitive_hit": True, "model_name": "Model B", **window(now)}
        roots = repository.tree_page(**query)
        assert conversations(roots) == {"parent"}
        root = roots["items"][0]
        assert root["match_scope"] == "DESCENDANT"
        children = repository.tree_page(parent_key=root["conversation_key"], generation=root["generation"], **query)
        assert conversations(children) == {"child"} and children["items"][0]["match_scope"] == "SELF"
        assert not repository.tree_page(model_name="Model A", sensitive_direction="BOTH", **window(now))["items"]
        # Full branch counters remain distinct from the selected matching requests.
        assert root["own_summary"]["sensitive_hit_count"] == 0
        assert root["branch_summary"]["sensitive_hit_count"] == 2
        assert root["branch_summary"]["request_count"] == 3


@pytest.mark.parametrize("mode", ["groups", "tree"])
def test_default_window_is_seven_days_and_maximum_is_31(
    query_engine, content_safety_native_audit, content_safety_clock, mode
):
    now = content_safety_clock.now()
    with tenant_session(query_engine) as session, session.begin():
        add(session, content_safety_native_audit, now, "old", days=8, direction="INPUT")
        add(session, content_safety_native_audit, now, "recent", direction="INPUT")
        repository = publish(session, now)
        assert conversations(page(repository, mode, now=now, has_sensitive_hit=True)) == {"recent"}
        assert conversations(page(repository, mode, now=now, has_sensitive_hit=True, **window(now, 31))) == {
            "old",
            "recent",
        }
        for start, end in ((now - timedelta(days=31, microseconds=1), now), (now, now)):
            with pytest.raises(ValueError):
                page(
                    repository,
                    mode,
                    now=now,
                    start_at=start,
                    end_at=end,
                    has_sensitive_hit=True,
                )


@pytest.mark.parametrize("mode", ["groups", "tree"])
def test_cursor_binds_safety_time_and_tenant_without_binding_implicit_clock(
    query_engine, content_safety_native_audit, content_safety_clock, mode
):
    now = content_safety_clock.now()
    for tenant, user in ((101, 11), (202, 22)):
        with tenant_session(query_engine, tenant) as session, session.begin():
            for index in range(3):
                add(
                    session,
                    content_safety_native_audit,
                    now,
                    f"page-{index}",
                    tenant=tenant,
                    user=user,
                    direction="BOTH",
                )
            publish(session, now)
    with tenant_session(query_engine) as session:
        repository = Repository(session)
        first = page(repository, mode, now=now, has_sensitive_hit=True, limit=1)
        assert first["next_cursor"]
        second = page(
            repository,
            mode,
            now=now + timedelta(seconds=1),
            has_sensitive_hit=True,
            limit=1,
            cursor=first["next_cursor"],
        )
        assert conversations(first).isdisjoint(conversations(second)) and len(second["items"]) == 1
        for changed in (
            {"has_sensitive_hit": False},
            {"sensitive_direction": "INPUT"},
            {"content_safety_state": "BLOCKED"},
            {"model_name": "Model A"},
            {"user_id": 11},
            {"end_at": now - timedelta(seconds=1)},
            {"start_at": now - timedelta(days=2)},
        ):
            with pytest.raises(ValueError):
                page(
                    repository,
                    mode,
                    now=now,
                    limit=1,
                    cursor=first["next_cursor"],
                    **{"has_sensitive_hit": True, **changed},
                )
    with tenant_session(query_engine, 202) as session:
        with pytest.raises(ValueError):
            page(
                Repository(session),
                mode,
                now=now,
                has_sensitive_hit=True,
                limit=1,
                cursor=first["next_cursor"],
            )


def test_group_totals_are_not_mislabeled_as_filtered_hit_counts(
    query_engine, content_safety_native_audit, content_safety_clock
):
    now = content_safety_clock.now()
    with tenant_session(query_engine) as session, session.begin():
        add(
            session,
            content_safety_native_audit,
            now,
            "mixed",
            days=30,
            direction="INPUT",
        )
        add(session, content_safety_native_audit, now, "mixed", direction="OUTPUT")
        add(session, content_safety_native_audit, now, "mixed")
        repository = publish(session, now)
        item = repository.group_page(has_sensitive_hit=True, **window(now))["items"][0]
        assert item["request_count"] == 3 and item["sensitive_hit_count"] == 2 and item["has_sensitive_hit"]
        assert item["summary_scope"] == "ALL_INDEXED_REQUESTS"
        assert item["request_filter_scope"] == "MATCHING_REQUESTS"
        assert item.get("matching_sensitive_hit_count") in (None, 1)
        assert repository.group_page(has_sensitive_hit=False, **window(now))["items"][0]["request_count"] == 3


def test_scan_limited_descendant_query_resumes_without_claiming_complete_empty(
    query_engine, content_safety_native_audit, content_safety_clock
):
    now = content_safety_clock.now()
    with tenant_session(query_engine) as session, session.begin():
        add(session, content_safety_native_audit, now, "parent")
        for index in range(8):
            add(
                session,
                content_safety_native_audit,
                now,
                f"child-{index}",
                parent="parent",
                direction="OUTPUT" if index == 7 else None,
            )
        repository = publish(session, now)
        cursor, found = None, []
        for _ in range(20):
            result = repository.tree_page(
                sensitive_direction="OUTPUT",
                scan_budget=1,
                limit=2,
                cursor=cursor,
                **window(now),
            )
            if not result["items"] and result["next_cursor"]:
                assert result["scan_limited"] is True
            found.extend(item["conversation_id"] for item in result["items"])
            cursor = result["next_cursor"]
            if cursor is None:
                assert result["scan_limited"] is False
                break
        else:
            raise AssertionError("Bounded continuation failed to converge")
        assert found == ["parent"]


def test_group_candidate_budget_is_explicit_and_continuable(
    query_engine, content_safety_native_audit, content_safety_clock
):
    now = content_safety_clock.now()
    # The real 1000-candidate production budget is exercised without replacing SQL.
    names = sorted(
        (f"candidate-{index}" for index in range(1002)),
        key=lambda name: conversation_key(101, 11, name),
    )
    with tenant_session(query_engine) as session, session.begin():
        for name in names:
            add(
                session,
                content_safety_native_audit,
                now,
                name,
                direction="INPUT" if name == names[0] else "OUTPUT",
            )
        repository = Repository(session)
        cursor, found = None, []
        for _ in range(20):
            result = repository.group_page(sensitive_direction="INPUT", limit=2, cursor=cursor, **window(now))
            found.extend(item["conversation_id"] for item in result["items"])
            cursor = result["next_cursor"]
            if cursor is None:
                assert result["scan_limited"] is False
                break
            # An indexed prefilter may finish on page one; incomplete scans must be honest.
            assert result["scan_limited"] is True
        else:
            raise AssertionError("Bounded conversation continuation did not converge")
        assert found == [names[0]]


@pytest.mark.parametrize("mode", ["groups", "tree"])
def test_query_sql_remains_bounded_metadata_only_and_tenant_scoped(
    query_engine, content_safety_native_audit, content_safety_clock, mode
):
    now = content_safety_clock.now()
    for tenant, user in ((101, 11), (202, 22)):
        with tenant_session(query_engine, tenant) as session, session.begin():
            add(
                session,
                content_safety_native_audit,
                now,
                f"tenant-{tenant}",
                tenant=tenant,
                user=user,
                direction="INPUT",
            )
            publish(session, now)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(query_engine, "before_cursor_execute", capture)
    try:
        with tenant_session(query_engine) as session:
            result = page(Repository(session), mode, has_sensitive_hit=True, **window(now))
            assert conversations(result) == {"tenant-101"}
    finally:
        event.remove(query_engine, "before_cursor_execute", capture)
    forbidden = (
        "dsh_content_safety_event",
        "dsh_model_audit_content",
        "dsh_model_audit_manifest",
        "dsh_model_call",
    )
    assert statements and not any(table in sql for sql in statements for table in forbidden)
    assert not any("count(" in sql or "offset" in sql.replace("offset ?", "") for sql in statements)
    request_queries = [sql for sql in statements if "dsh_model_audit_request" in sql]
    assert request_queries and all(
        "tenant_id" in sql and ("limit" in sql or "exists (" in sql) for sql in request_queries
    )


def test_foreign_hierarchy_pending_cannot_mark_published_tenant_safety_unready(
    query_engine, content_safety_native_audit, content_safety_clock
):
    now = content_safety_clock.now()
    with tenant_session(query_engine) as session, session.begin():
        add(session, content_safety_native_audit, now, "published-101", direction="INPUT")
        publish(session, now)
    with tenant_session(query_engine, 202) as session, session.begin():
        session.add(content_safety_native_audit(tenant_id=202, user_id=22))
    with tenant_session(query_engine) as session:
        result = Repository(session).group_page(has_sensitive_hit=True)
        assert conversations(result) == {"published-101"}
        assert result["progress"]["safety_ready"] is True
