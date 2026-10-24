"""Coverage AC: AC-45, AC-49, AC-50.

Real HTTP routes, authorization, services, SQL projection and queries are used.
The shared fixture supplies synthetic logged-in actors and external identity
reads; this is not browser JWT admission or MySQL/DM8 evidence.
"""

from datetime import timedelta

import pytest
from sqlalchemy import event

from bisheng.dsh.domain.models.model_audit_title import DshModelAuditConversationTitle
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key
from test.dsh.test_content_safety_query_api import data, get, invalid
from test.dsh.test_content_safety_query_api import query_api as query_api
from test.dsh.test_content_safety_query_api import query_engine as query_engine
from test.dsh.test_content_safety_repository import tenant_session
from test.dsh.test_content_safety_tree_queries import add, publish

MODES = ("groups", "tree", "requests")


@pytest.fixture(autouse=True)
def title_metadata_table(query_engine):
    DshModelAuditConversationTitle.__table__.create(query_engine, checkfirst=True)


def route(mode, *, tenant=101, user=11):
    if mode == "groups":
        return "/conversation-groups"
    if mode == "tree":
        return "/conversation-tree"
    return f"/conversation-groups/{conversation_key(tenant, user, 'shared')}/requests"


def seed(api, factory, mode, entries, *, tenant=101, user=11):
    labels = {}
    with tenant_session(api.engine, tenant) as session, session.begin():
        for label, started, changes in entries:
            row = add(
                session,
                factory,
                api.clock.now(),
                "shared" if mode == "requests" else label,
                tenant=tenant,
                user=user,
                direction="BOTH",
                started_at=started,
                model_started_at=started,
                **changes,
            )
            labels[row.request_id] = label
        publish(session, api.clock.now())
    return labels


def selected(result, mode, labels):
    return {labels[item["request_id"]] if mode == "requests" else item["conversation_id"] for item in result["items"]}


def bounds(api, days=7):
    return {"start_at": (api.clock.now() - timedelta(days=days)).isoformat(), "end_at": api.clock.now().isoformat()}


@pytest.mark.parametrize("mode", MODES)
async def test_actual_group_tree_and_group_requests_default_to_seven_days(query_api, content_safety_native_audit, mode):
    api = query_api
    labels = seed(
        api,
        content_safety_native_audit,
        mode,
        [(f"day-{days}", api.clock.now() - timedelta(days=days), {}) for days in (1, 6, 8, 30)],
    )
    result = data(await get(api, route(mode), has_sensitive_hit=True))
    assert selected(result, mode, labels) == {"day-1", "day-6"}


@pytest.mark.parametrize("mode", MODES)
async def test_actual_group_tree_and_group_requests_reject_over_31_days(query_api, content_safety_native_audit, mode):
    api = query_api
    seed(api, content_safety_native_audit, mode, [("observed", api.clock.now() - timedelta(days=1), {})])
    invalid(
        await get(
            api,
            route(mode),
            has_sensitive_hit=True,
            start_at=(api.clock.now() - timedelta(days=31, microseconds=1)).isoformat(),
            end_at=api.clock.now().isoformat(),
        )
    )


@pytest.mark.parametrize("mode", MODES)
async def test_explicit_31_day_window_remains_allowed(query_api, content_safety_native_audit, mode):
    api = query_api
    labels = seed(
        api,
        content_safety_native_audit,
        mode,
        [(f"day-{days}", api.clock.now() - timedelta(days=days), {}) for days in (1, 30)],
    )
    assert selected(data(await get(api, route(mode), has_sensitive_hit=True, **bounds(api, 31))), mode, labels) == {
        "day-1",
        "day-30",
    }


@pytest.mark.parametrize("mode", MODES)
async def test_default_window_moves_with_service_clock_without_invalidating_cursor(
    query_api, content_safety_native_audit, mode
):
    api = query_api
    names = sorted(("moving-a", "moving-b", "moving-c"), key=lambda name: conversation_key(101, 11, name), reverse=True)
    entries = [(name, api.clock.now() - timedelta(days=1), {}) for name in names[:2]]
    entries.append((names[2], api.clock.now() + timedelta(milliseconds=500), {}))
    labels = seed(api, content_safety_native_audit, mode, entries)
    path = route(mode)
    first = data(await get(api, path, has_sensitive_hit=True, limit=1))
    assert first["next_cursor"]
    # Already persisted future observations must become eligible when the real query clock advances.
    assert names[2] not in selected(data(await get(api, path, has_sensitive_hit=True)), mode, labels)
    api.clock.advance(1)
    found = selected(first, mode, labels)
    cursor = first["next_cursor"]
    for _ in range(5):
        result = data(await get(api, path, has_sensitive_hit=True, limit=1, cursor=cursor))
        current = selected(result, mode, labels)
        assert found.isdisjoint(current)
        found.update(current)
        cursor = result["next_cursor"]
        if cursor is None:
            break
    else:
        raise AssertionError("Finite API continuation did not converge")
    assert found == set(names)


@pytest.mark.parametrize("mode", MODES)
async def test_explicit_time_tenant_and_safety_filters_remain_cursor_bound(
    query_api, content_safety_native_audit, mode
):
    api = query_api
    entries = [(f"cursor-{index}", api.clock.now() - timedelta(days=1), {}) for index in range(3)]
    seed(api, content_safety_native_audit, mode, entries)
    seed(api, content_safety_native_audit, mode, entries, tenant=202, user=22)
    original = {"has_sensitive_hit": True, **bounds(api)}
    first = data(await get(api, route(mode), actor=1, tenant_id=101, limit=1, **original))
    assert first["next_cursor"]
    for change in (
        {"start_at": (api.clock.now() - timedelta(days=2)).isoformat()},
        {"end_at": (api.clock.now() - timedelta(seconds=1)).isoformat()},
        {"has_sensitive_hit": False},
        {"sensitive_direction": "INPUT"},
        {"content_safety_state": "BLOCKED"},
        {"model_name": "Model A"},
    ):
        invalid(
            await get(
                api, route(mode), actor=1, tenant_id=101, limit=1, cursor=first["next_cursor"], **{**original, **change}
            )
        )
    invalid(
        await get(
            api,
            route(mode, tenant=202, user=22),
            actor=1,
            tenant_id=202,
            limit=1,
            cursor=first["next_cursor"],
            **original,
        )
    )
    api.clock.advance(1)
    assert data(await get(api, route(mode), actor=1, tenant_id=101, limit=1, cursor=first["next_cursor"], **original))[
        "items"
    ]


@pytest.mark.parametrize("mode", MODES)
async def test_window_queries_preserve_existing_administrator_scope(query_api, content_safety_native_audit, mode):
    api = query_api
    seed(api, content_safety_native_audit, mode, [("authorized", api.clock.now() - timedelta(days=1), {})])
    assert (await get(api, route(mode), actor=42)).status_code == 403
    assert (await get(api, route(mode), tenant_id=202)).status_code == 403
    result = data(await get(api, route(mode), has_sensitive_hit=True, **bounds(api)))
    assert len(result["items"]) == 1
    assert all(scope == (101, None, frozenset({101}), False) for scope in api.scopes)


@pytest.mark.parametrize("mode", MODES)
async def test_safety_and_time_require_the_same_model_request_over_http(query_api, content_safety_native_audit, mode):
    api = query_api
    now = api.clock.now()
    conversation = "shared" if mode == "requests" else "mixed"
    labels = {}
    with tenant_session(api.engine) as session, session.begin():
        for label, days, direction, model in (
            ("old-hit", 30, "INPUT", "Model A"),
            ("recent-clean", 1, None, "Model A"),
            ("other-model", 1, "INPUT", "Model B"),
        ):
            row = add(
                session, content_safety_native_audit, now, conversation, days=days, direction=direction, model=model
            )
            labels[row.request_id] = label
        row = add(
            session,
            content_safety_native_audit,
            now,
            "shared" if mode == "requests" else "actual-match",
            direction="INPUT",
            model="Model A",
        )
        labels[row.request_id] = "actual-match"
        publish(session, now)
    result = data(
        await get(api, route(mode), user_id=11, model_name="Model A", sensitive_direction="INPUT", **bounds(api))
    )
    assert selected(result, mode, labels) == {"actual-match"}


@pytest.mark.parametrize("mode", MODES)
async def test_online_group_queries_never_prefetch_originals_or_safety_events(
    query_api, content_safety_native_audit, mode
):
    api = query_api
    seed(api, content_safety_native_audit, mode, [("metadata-only", api.clock.now() - timedelta(days=1), {})])
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(api.engine, "before_cursor_execute", capture)
    try:
        assert data(await get(api, route(mode), has_sensitive_hit=True, **bounds(api)))["items"]
    finally:
        event.remove(api.engine, "before_cursor_execute", capture)
    assert statements
    forbidden = (
        "dsh_model_audit_content",
        "dsh_model_audit_manifest",
        "dsh_model_audit_body_access",
        "dsh_content_safety_event",
    )
    assert not any(table in sql for sql in statements for table in forbidden)


async def test_location_keeps_its_independent_historical_position_semantics(query_api, content_safety_native_audit):
    api = query_api
    with tenant_session(api.engine) as session, session.begin():
        add(session, content_safety_native_audit, api.clock.now(), "old-parent", days=40)
        add(session, content_safety_native_audit, api.clock.now(), "old-child", days=40, parent="old-parent")
        publish(session, api.clock.now())
    child_key = conversation_key(101, 11, "old-child")
    result = data(await get(api, f"/conversation-tree/{child_key}/location"))
    assert [item["conversation_id"] for item in result["items"]] == ["old-parent", "old-child"]
