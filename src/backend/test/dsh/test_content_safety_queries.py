"""Coverage AC: AC-32, AC-34, AC-36, AC-44, AC-45, AC-46, AC-49, AC-50, AC-51, AC-52.

Real scoped repositories and SQL; these fixtures do not prove dual-DB plans.
"""

import base64
import importlib
import json
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event
from sqlmodel import SQLModel

from bisheng.core.context.tenant import visible_tenant_ids
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent as Fact
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditEvidence
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories import content_safety, content_safety_projection
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Repository
from bisheng.user.domain.models.user import User
from test.dsh.test_content_safety_groups import native
from test.dsh.test_content_safety_merge import committed_merge
from test.dsh.test_content_safety_repository import committed_append, tenant_session


@pytest.fixture
def query_engine(content_safety_engine):
    SQLModel.metadata.create_all(
        content_safety_engine, tables=[model.__table__ for model in (DshModelCall, DshModelAuditEvidence, User)]
    )
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(User(user_id=11, user_name="Synthetic user", password=uuid4().hex))
    return content_safety_engine


def event_repository(session):
    return importlib.import_module(
        "bisheng.dsh.domain.repositories.content_safety_queries"
    ).ContentSafetyQueryRepository(session)


@contextmanager
def observed_sql(engine):
    statements = []

    def observed(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            upper = statement.upper()
            # SQLite emits LIMIT ? OFFSET ? with a synthetic zero offset even
            # when the ORM statement has no offset pagination.
            if upper.rstrip().endswith("OFFSET ?") and isinstance(_parameters, (tuple, list)) and _parameters[-1] == 0:
                upper = upper.rsplit(" OFFSET ", 1)[0]
            statements.append(upper)

    event.listen(engine, "before_cursor_execute", observed)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", observed)


def page(engine, now, *, tenant=101, **filters):
    query = {"start_at": now - timedelta(days=7), "end_at": now + timedelta(seconds=1), **filters}
    with tenant_session(engine, tenant) as session:
        return Repository(session).page(**query)


def insert(engine, factory, *, at=None, **values):
    row = native(factory, **values)
    if at:
        row.started_at = at
    with tenant_session(engine) as session, session.begin():
        session.add(row)
    return row


@pytest.mark.parametrize(
    ("filters", "selected"),
    [
        ({"has_sensitive_hit": True}, {"input", "output", "both"}),
        ({"has_sensitive_hit": False}, {"clean"}),
        ({"sensitive_direction": "INPUT"}, {"input", "both"}),
        ({"sensitive_direction": "OUTPUT"}, {"output", "both"}),
        ({"sensitive_direction": "BOTH"}, {"both"}),
        ({"has_sensitive_hit": False, "sensitive_direction": "INPUT"}, set()),
        ({"has_sensitive_hit": True, "user_id": 11, "model_id": 7}, {"input", "output", "both"}),
        ({"has_sensitive_hit": True, "user_id": 22}, set()),
    ],
)
def test_request_filters_compose_on_the_same_summary_row(
    query_engine, content_safety_native_audit, content_safety_clock, filters, selected
):
    ids = {}
    for label, incoming, outgoing in (
        ("clean", False, False),
        ("input", True, False),
        ("output", False, True),
        ("both", True, True),
    ):
        row = insert(
            query_engine,
            content_safety_native_audit,
            input_sensitive_hit=incoming,
            output_sensitive_hit=outgoing,
            has_sensitive_hit=incoming or outgoing,
            content_safety_state="BLOCKED" if incoming or outgoing else "PASSED",
        )
        ids[row.request_id] = label
    result = page(query_engine, content_safety_clock.now(), **filters)
    assert {ids[item["request_id"]] for item in result["items"]} == selected


@pytest.mark.parametrize("state", ["PASSED", "BLOCKED", "ERROR", "DISABLED", "NOT_APPLICABLE", "UNREPORTED"])
def test_all_six_safety_states_filter_independently_of_model_success(
    query_engine, content_safety_native_audit, content_safety_clock, state
):
    expected = insert(query_engine, content_safety_native_audit, content_safety_state=state)
    insert(query_engine, content_safety_native_audit, content_safety_state="ERROR" if state != "ERROR" else "PASSED")
    result = page(query_engine, content_safety_clock.now(), content_safety_state=state)
    assert [item["request_id"] for item in result["items"]] == [expected.request_id]
    assert result["items"][0]["model_result"] == "SUCCEEDED"
    assert result["items"][0]["audit_status"] == "NORMAL"


def test_list_uses_bulk_usage_and_name_reads_without_event_queries_or_counts(
    query_engine, content_safety_native_audit, content_safety_clock
):
    rows = [insert(query_engine, content_safety_native_audit) for _ in range(20)]
    with tenant_session(query_engine) as session, session.begin():
        session.add_all(
            [
                DshModelCall(
                    request_id=row.request_id,
                    user_id=row.user_id,
                    model_id=row.model_id,
                    session_id=row.session_id,
                    usage_month="2026-10",
                    policy_version=1,
                    event_version=1,
                    quota_epoch=1,
                    status="SUCCEEDED",
                    input_tokens=10,
                    output_tokens=4,
                    total_tokens=14,
                    usage_source="PROVIDER",
                    settled_at=content_safety_clock.now(),
                )
                for row in rows
            ]
        )
    with observed_sql(query_engine) as statements:
        result = page(query_engine, content_safety_clock.now(), limit=20)
    assert len(result["items"]) == 20
    assert all(
        item["user_name"] == "Synthetic user" and item["usage"]["total_tokens"] == 14 for item in result["items"]
    )
    assert sum("FROM DSH_MODEL_CALL" in sql for sql in statements) == 1
    assert sum("FROM USER" in sql for sql in statements) == 1
    assert not any(
        token in sql for sql in statements for token in ("DSH_CONTENT_SAFETY_EVENT", "COUNT(", "GROUP BY", " OFFSET ")
    )
    assert len(statements) <= 4


def test_external_nullable_metadata_keeps_not_applicable_and_unknown_usage(
    query_engine, content_safety_event, content_safety_clock
):
    _, external, _ = committed_merge(query_engine, content_safety_projection, content_safety_event(session_id=None))
    result = page(query_engine, content_safety_clock.now(), has_sensitive_hit=True)
    item = next(item for item in result["items"] if item["request_id"] == external.request_id)
    assert item["audit_status"] == "NOT_APPLICABLE" and item["record_origin"] == "EXTERNAL_SAFETY"
    assert item["has_sensitive_hit"] and item["details_status"] == "PENDING"
    assert all(
        item[name] is None
        for name in ("model_result", "response_result", "usage_settlement", "effective_mode", "session_id", "usage")
    )


def test_request_keyset_binds_every_explicit_filter_and_tenant(
    query_engine, content_safety_native_audit, content_safety_clock
):
    for _ in range(3):
        insert(query_engine, content_safety_native_audit, input_sensitive_hit=True, has_sensitive_hit=True)
    now = content_safety_clock.now()
    first = page(query_engine, now, limit=1, has_sensitive_hit=True, sensitive_direction="INPUT")
    second = page(
        query_engine, now, limit=1, has_sensitive_hit=True, sensitive_direction="INPUT", cursor=first["next_cursor"]
    )
    assert first["items"][0]["request_id"] != second["items"][0]["request_id"]
    assert first["items"][0]["started_at"] == second["items"][0]["started_at"]
    for changed in (
        {"has_sensitive_hit": False},
        {"sensitive_direction": "OUTPUT"},
        {"user_id": 22},
        {"start_at": now - timedelta(days=6)},
    ):
        with pytest.raises(ValueError):
            page(
                query_engine,
                now,
                limit=1,
                cursor=first["next_cursor"],
                **{"has_sensitive_hit": True, "sensitive_direction": "INPUT", **changed},
            )
    with pytest.raises(ValueError):
        page(
            query_engine,
            now,
            tenant=202,
            limit=1,
            cursor=first["next_cursor"],
            has_sensitive_hit=True,
            sensitive_direction="INPUT",
        )


def test_event_pages_distinguish_unreported_available_and_purged(
    query_engine, content_safety_event, content_safety_native_audit
):
    native_row = insert(query_engine, content_safety_native_audit)
    raw = content_safety_event(session_id=None)
    _, external, _ = committed_merge(query_engine, content_safety_projection, raw)
    with tenant_session(query_engine) as session:
        repository = event_repository(session)
        clean = repository.request_events(native_row.request_id)
        assert clean["items"] == [] and clean["details_status"] == "UNREPORTED"
        available = repository.request_events(external.request_id)
        assert available["details_status"] == "AVAILABLE" and len(available["items"]) == 1
        assert available["items"][0]["event_id"] == raw["event_id"]
    with tenant_session(query_engine) as session, session.begin():
        session.execute(delete(Fact).where(Fact.tenant_id == 101, Fact.audit_request_id == external.request_id))
    with tenant_session(query_engine) as session:
        purged = event_repository(session).request_events(external.request_id)
        assert purged["items"] == [] and purged["details_status"] == "PURGED"
        assert Repository(session).request(external.request_id).has_sensitive_hit


def test_request_events_have_bounded_stable_tie_keysets_without_raw_payload_or_count(
    query_engine, content_safety_event
):
    raw = content_safety_event(session_id=None)
    _, external, _ = committed_merge(query_engine, content_safety_projection, raw)
    for version in (2, 3):
        committed_merge(
            query_engine,
            content_safety_projection,
            {**raw, "event_id": str(UUID(int=version)), "event_version": version},
        )
    seen, cursor = [], None
    with observed_sql(query_engine) as statements:
        for _ in range(4):
            with tenant_session(query_engine) as session:
                result = event_repository(session).request_events(external.request_id, cursor=cursor, limit=1)
            assert len(result["items"]) <= 1
            seen.extend(item["event_id"] for item in result["items"])
            cursor = result["next_cursor"]
            if cursor is None:
                break
    assert len(seen) == len(set(seen)) == 3 and cursor is None
    assert not any(token in sql for sql in statements for token in ("COUNT(", " OFFSET ", "GROUP BY"))
    with tenant_session(query_engine) as session:
        result = event_repository(session).request_events(external.request_id)
    assert all(not set(item) & {"payload", "payload_hash", "raw_text", "authorization"} for item in result["items"])


def test_empty_continuation_is_available_while_any_request_event_is_retained(query_engine, content_safety_event):
    raw = content_safety_event(session_id=None)
    _, audit, _ = committed_merge(query_engine, content_safety_projection, raw)
    committed_merge(query_engine, content_safety_projection, {**raw, "event_id": str(uuid4()), "event_version": 2})
    with tenant_session(query_engine) as session:
        first = event_repository(session).request_events(audit.request_id, limit=1)
        cursor, retained = first["next_cursor"], first["items"][0]["event_id"]
        assert cursor
    # Model a retention race after the first page, keeping the consumed fact.
    with tenant_session(query_engine) as session, session.begin():
        session.execute(
            delete(Fact).where(
                Fact.tenant_id == 101, Fact.audit_request_id == audit.request_id, Fact.event_id != retained
            )
        )
    with tenant_session(query_engine) as session:
        following = event_repository(session).request_events(audit.request_id, cursor=cursor, limit=1)
        assert following["items"] == [] and following["details_status"] == "AVAILABLE"


def test_event_cursors_cannot_cross_requests_or_tenants(query_engine, content_safety_event):
    first_raw = content_safety_event(session_id=None)
    _, first, _ = committed_merge(query_engine, content_safety_projection, first_raw)
    committed_merge(
        query_engine, content_safety_projection, {**first_raw, "event_id": str(uuid4()), "event_version": 2}
    )
    _, other, _ = committed_merge(query_engine, content_safety_projection, content_safety_event(session_id=None))
    with tenant_session(query_engine) as session:
        cursor = event_repository(session).request_events(first.request_id, limit=1)["next_cursor"]
        assert cursor
        with pytest.raises(ValueError):
            event_repository(session).request_events(other.request_id, limit=1, cursor=cursor)
    with tenant_session(query_engine, 202) as session, pytest.raises((ValueError, LookupError)):
        event_repository(session).request_events(first.request_id, limit=1, cursor=cursor)


@pytest.mark.parametrize("bad_id", [[], {}, 42, None])
def test_malformed_event_cursor_ids_are_query_errors_not_runtime_errors(query_engine, content_safety_event, bad_id):
    raw = content_safety_event(session_id=None)
    _, audit, _ = committed_merge(query_engine, content_safety_projection, raw)
    committed_merge(query_engine, content_safety_projection, {**raw, "event_id": str(uuid4()), "event_version": 2})
    with tenant_session(query_engine) as session:
        repository = event_repository(session)
        cursor = repository.request_events(audit.request_id, limit=1)["next_cursor"]
        position = json.loads(base64.urlsafe_b64decode(cursor))
        position["id"] = bad_id
        malformed = base64.urlsafe_b64encode(json.dumps(position).encode()).decode()
        with pytest.raises(ValueError):
            repository.request_events(audit.request_id, limit=1, cursor=malformed)


def test_unassociated_default_window_is_request_started_at_and_has_no_frozen_window_requirement(
    query_engine, content_safety_event, content_safety_clock
):
    now = content_safety_clock.now()
    for days in (1, 6, 8, 30):
        committed_append(
            content_safety,
            query_engine,
            content_safety_event(
                forwarded=True,
                backend_request_id=None,
                request_started_at=(now - timedelta(days=days)).isoformat(),
            ),
        )
    with tenant_session(query_engine) as session:
        repository = event_repository(session)
        first = repository.unassociated_events(now=now, limit=1)
        assert len(first["items"]) == 1 and first["next_cursor"]
        second = repository.unassociated_events(now=now + timedelta(seconds=1), limit=1, cursor=first["next_cursor"])
        assert len(second["items"]) == 1
        assert first["items"][0]["event_id"] != second["items"][0]["event_id"]
        assert repository.unassociated_events(now=now, limit=20)["next_cursor"] is None
        assert len(repository.unassociated_events(now=now)["items"]) == 2
        assert len(repository.unassociated_events(now=now, start_at=now - timedelta(days=31), end_at=now)["items"]) == 4
        with pytest.raises(ValueError):
            repository.unassociated_events(now=now, start_at=now - timedelta(days=31, seconds=1), end_at=now)
        with pytest.raises(ValueError):
            repository.unassociated_events(now=now, start_at=now, end_at=now - timedelta(days=1))
        with pytest.raises(ValueError):
            repository.unassociated_events(now=now, cursor=first["next_cursor"], user_id=22)
    token = visible_tenant_ids.set(frozenset({101, 202}))
    try:
        with tenant_session(query_engine, 202) as session:
            assert event_repository(session).unassociated_events(now=now)["items"] == []
    finally:
        visible_tenant_ids.reset(token)


@pytest.mark.parametrize("limit", [0, -1, 101, True])
def test_event_page_limits_are_strictly_bounded(query_engine, limit):
    with tenant_session(query_engine) as session, pytest.raises(ValueError):
        event_repository(session).unassociated_events(limit=limit)


# Coverage AC: AC-45, AC-49, AC-50.
def bounded_requests(engine, now, *, tenant=101, **query):
    with tenant_session(engine, tenant) as session:
        return Repository(session).page(now=now, **query)


def test_default_request_window_moves_without_invalidating_its_cursor(
    query_engine, content_safety_native_audit, content_safety_clock
):
    clock = content_safety_clock
    earlier = [insert(query_engine, content_safety_native_audit, at=clock.now() - timedelta(hours=1)) for _ in range(2)]
    entering = insert(
        query_engine,
        content_safety_native_audit,
        at=clock.now() + timedelta(milliseconds=500),
        model_started_at=clock.now() + timedelta(milliseconds=500),
    )
    initial = bounded_requests(query_engine, clock.now())
    assert {item["request_id"] for item in initial["items"]} == {row.request_id for row in earlier}
    first = bounded_requests(query_engine, clock.now(), limit=1)
    seen = [first["items"][0]["request_id"]]
    cursor = first["next_cursor"]
    clock.advance(1)
    for _ in range(3):
        following = bounded_requests(query_engine, clock.now(), cursor=cursor, limit=1)
        seen.extend(item["request_id"] for item in following["items"])
        cursor = following["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 3 and cursor is None
    assert set(seen) == {row.request_id for row in earlier} | {entering.request_id}


def test_windowed_request_cursor_still_binds_explicit_time_safety_and_tenant(
    query_engine, content_safety_native_audit, content_safety_clock
):
    now = content_safety_clock.now()
    for _ in range(3):
        insert(
            query_engine,
            content_safety_native_audit,
            at=now - timedelta(hours=1),
            has_sensitive_hit=True,
            input_sensitive_hit=True,
            output_sensitive_hit=True,
        )
    explicit = {
        "start_at": now - timedelta(days=7),
        "end_at": now,
        "has_sensitive_hit": True,
        "sensitive_direction": "INPUT",
        "limit": 1,
    }
    first = bounded_requests(query_engine, now, **explicit)
    cursor = first["next_cursor"]
    following = bounded_requests(query_engine, now + timedelta(seconds=1), cursor=cursor, **explicit)
    assert following["items"][0]["request_id"] != first["items"][0]["request_id"]
    for changed in (
        {"start_at": now - timedelta(days=6)},
        {"end_at": now + timedelta(seconds=1)},
        {"has_sensitive_hit": False},
        {"sensitive_direction": "OUTPUT"},
    ):
        with pytest.raises(ValueError):
            bounded_requests(query_engine, now + timedelta(seconds=1), cursor=cursor, **{**explicit, **changed})
    with pytest.raises(ValueError):
        bounded_requests(query_engine, now + timedelta(seconds=1), tenant=202, cursor=cursor, **explicit)


def test_request_window_port_bounds_7_and_31_days(query_engine, content_safety_native_audit, content_safety_clock):
    now = content_safety_clock.now()
    insert(query_engine, content_safety_native_audit, at=now - timedelta(days=40))
    recent = insert(query_engine, content_safety_native_audit, at=now - timedelta(days=1))
    assert [item["request_id"] for item in bounded_requests(query_engine, now)["items"]] == [recent.request_id]
    assert [
        item["request_id"]
        for item in bounded_requests(query_engine, now, start_at=now - timedelta(days=31), end_at=now)["items"]
    ] == [recent.request_id]
    with pytest.raises(ValueError):
        bounded_requests(query_engine, now, start_at=now - timedelta(days=31, microseconds=1), end_at=now)
    with pytest.raises(ValueError):
        bounded_requests(query_engine, now, start_at=now, end_at=now)


def test_legacy_requests_without_window_clock_keep_internal_unbounded_semantics(
    query_engine, content_safety_native_audit, content_safety_clock
):
    now = content_safety_clock.now()
    old = insert(query_engine, content_safety_native_audit, at=now - timedelta(days=40))
    recent = insert(query_engine, content_safety_native_audit, at=now - timedelta(days=1))
    with tenant_session(query_engine) as session:
        legacy = Repository(session).page()
    assert {item["request_id"] for item in legacy["items"]} == {old.request_id, recent.request_id}


# Coverage AC: AC-37, AC-38, AC-42, AC-46, AC-49.
@pytest.mark.parametrize("field", ["gateway_request_id", "backend_request_id"])
def test_unassociated_uuid_filters_are_case_equivalent_without_lowering_sql_columns(
    query_engine, content_safety_event, content_safety_clock, field
):
    raw = content_safety_event(
        forwarded=True,
        gateway_request_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        backend_request_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )
    committed_append(content_safety, query_engine, raw)
    now = content_safety_clock.now() + timedelta(seconds=1)
    with tenant_session(query_engine) as session, observed_sql(query_engine) as statements:
        repository = event_repository(session)
        lower = repository.unassociated_events(now=now, **{field: raw[field]})
        upper = repository.unassociated_events(now=now, **{field: raw[field].upper()})
        assert [item["event_id"] for item in upper["items"]] == [raw["event_id"]]
        assert upper == lower
        assert not any("LOWER(" in sql for sql in statements)
    with tenant_session(query_engine, 202) as session:
        assert event_repository(session).unassociated_events(now=now, **{field: raw[field].upper()})["items"] == []


@pytest.mark.parametrize("field", ["gateway_request_id", "backend_request_id"])
def test_unassociated_uuid_case_changes_keep_the_same_explicit_cursor_binding(
    query_engine, content_safety_event, content_safety_clock, field
):
    raw = content_safety_event(
        forwarded=True,
        gateway_request_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        backend_request_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )
    for version in (1, 2, 3):
        committed_append(content_safety, query_engine, {**raw, "event_id": str(uuid4()), "event_version": version})
    now = content_safety_clock.now() + timedelta(seconds=1)
    with tenant_session(query_engine) as session:
        repository = event_repository(session)
        first = repository.unassociated_events(now=now, limit=1, **{field: raw[field]})
        assert first["next_cursor"]
        second = repository.unassociated_events(
            now=now + timedelta(seconds=1), limit=1, cursor=first["next_cursor"], **{field: raw[field].upper()}
        )
        assert len(second["items"]) == 1 and second["items"][0]["event_id"] != first["items"][0]["event_id"]
        with pytest.raises(ValueError):
            repository.unassociated_events(
                now=now, limit=1, cursor=first["next_cursor"], **{field: "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
            )


@pytest.mark.parametrize("field", ["gateway_request_id", "backend_request_id"])
@pytest.mark.parametrize("invalid", ["", "not-a-uuid", "a" * 32, 123, True, [], {}])
def test_unassociated_uuid_filter_rejects_invalid_values_before_sql(query_engine, field, invalid):
    with tenant_session(query_engine) as session, observed_sql(query_engine) as statements:
        with pytest.raises(ValueError, match="Invalid safety query request ID"):
            event_repository(session).unassociated_events(**{field: invalid})
        assert statements == []
