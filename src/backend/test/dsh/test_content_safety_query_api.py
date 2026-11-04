"""Coverage AC: AC-07, AC-08, AC-35, AC-44, AC-45, AC-46, AC-49, AC-50, AC-51.

Real audit routes, administrator authorization, query services and SQL repositories
are used. Logged-in actor delivery and external identity/permission reads are
synthetic; this does not prove browser JWT admission or MySQL/DM8 integration.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete
from sqlmodel import Session

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context import tenant as context
from bisheng.database.models.tenant import UserTenantDao
from bisheng.dsh import admin_runtime
from bisheng.dsh.api.endpoints import model_audit_admin as endpoint
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent as Fact
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeState
from bisheng.dsh.domain.repositories import content_safety, content_safety_projection
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.domain.services.model_audit_queries import DshModelAuditQueryService
from bisheng.permission import application as permissions
from bisheng.permission.application import relation_api
from bisheng.user.domain.models.user import User, UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from test.dsh import test_content_safety_queries as query_tests
from test.dsh.test_content_safety_groups import native
from test.dsh.test_content_safety_merge import committed_merge
from test.dsh.test_content_safety_repository import committed_append, tenant_session

query_engine = query_tests.query_engine
BASE = "/api/v1/dsh/admin/model-audit"
STATES = ("UNREPORTED", "PASSED", "BLOCKED", "ERROR", "DISABLED", "NOT_APPLICABLE")


@contextmanager
def actor_scope(actor=41, *, admin_scope=None):
    tenant = 1 if actor == 1 else 101
    tokens = [
        context.current_tenant_id.set(tenant),
        context.set_admin_scope_tenant_id(admin_scope),
        context.set_visible_tenant_ids(frozenset({1, tenant})),
        context._bypass_tenant_filter.set(False),
    ]
    try:
        yield
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


@pytest.fixture
def query_api(monkeypatch, query_engine, content_safety_clock, content_safety_identities):
    actor_reads, memberships, scopes = [], [], []

    async def user_read(user_id):
        actor_reads.append(user_id)
        return SimpleNamespace(user_id=user_id, delete=0) if user_id in {1, 41, 42} else None

    async def membership_read(user_id):
        memberships.append(user_id)
        return SimpleNamespace(tenant_id=1 if user_id == 1 else 101) if user_id in {1, 41, 42} else None

    async def relation_check(*, subject, relation, resource):
        return (subject.subject_id == "1" and relation == "super_admin" and resource.resource_type == "system") or (
            subject.subject_id == "41"
            and relation == "admin"
            and resource.resource_type == "tenant"
            and resource.resource_id == "101"
        )

    permission_port = SimpleNamespace(check=AsyncMock(side_effect=relation_check))
    get_permission_port = AsyncMock(return_value=permission_port)
    monkeypatch.setattr(permissions, "get_permission_relation_api", get_permission_port)
    monkeypatch.setattr(relation_api, "get_permission_relation_api", get_permission_port)
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(side_effect=user_read))
    monkeypatch.setattr(UserRoleDao, "aget_user_roles", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserTenantDao, "aget_active_user_tenant", AsyncMock(side_effect=membership_read))

    @contextmanager
    def repository_scope():
        scopes.append(
            (
                context.get_current_tenant_id(),
                context.get_admin_scope_tenant_id(),
                context.get_visible_tenant_ids(),
                context.is_tenant_filter_bypassed(),
            )
        )
        with Session(query_engine, expire_on_commit=False) as session:
            yield DshModelAuditQueryRepository(session)

    service = DshModelAuditQueryService(admin_runtime.authorize_admin, repository_scope, now=content_safety_clock.now)
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def business_error(_request, error):
        # Preserve the existing platform business envelope, as in AuditHarness.
        return JSONResponse(error.return_resp_instance().model_dump())

    async def logged_in_actor(request: Request):
        return SimpleNamespace(user_id=int(request.headers.get("X-Synthetic-Actor", "41")))

    app.dependency_overrides[endpoint.audit_admin] = logged_in_actor
    app.dependency_overrides[endpoint.get_audit_management] = lambda: SimpleNamespace(queries=service)
    app.include_router(endpoint.router, prefix="/api/v1")
    return SimpleNamespace(
        app=app,
        engine=query_engine,
        clock=content_safety_clock,
        identities=content_safety_identities,
        actor_reads=actor_reads,
        memberships=memberships,
        scopes=scopes,
        service=service,
    )


async def get(api, path, *, actor=41, admin_scope=None, **params):
    with actor_scope(actor, admin_scope=admin_scope):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="https://bisheng.invalid"
        ) as client:
            return await client.get(
                BASE + path,
                headers={"X-Synthetic-Actor": str(actor)},
                params={key: value for key, value in params.items() if value is not None},
            )


def data(response):
    assert response.status_code == 200 and response.json()["status_code"] == 200
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["data"]


def invalid(response):
    assert response.status_code == 422 or (response.status_code == 200 and response.json()["status_code"] == 26131)


def store(api, factory, *, tenant=101, **changes):
    actor = next(identity for identity in api.identities if identity.tenant_id == tenant)
    values = {"group_index_pending": False, "hierarchy_indexed": True, **changes}
    row = native(factory, identity=actor, conversation=None, **values)
    with tenant_session(api.engine, tenant) as session, session.begin():
        session.add(row)
    return row


def window(api):
    return {
        "start_at": (api.clock.now() - timedelta(days=7)).isoformat(),
        "end_at": (api.clock.now() + timedelta(seconds=1)).isoformat(),
    }


@pytest.mark.parametrize("state", STATES)
async def test_requests_forward_all_six_safety_states_to_real_summary_query(
    query_api, content_safety_native_audit, state
):
    api = query_api
    expected = store(api, content_safety_native_audit, content_safety_state=state)
    store(api, content_safety_native_audit, content_safety_state="ERROR" if state != "ERROR" else "PASSED")
    result = data(await get(api, "/requests", content_safety_state=state, **window(api)))
    assert [item["request_id"] for item in result["items"]] == [expected.request_id]
    assert result["items"][0]["model_result"] == "SUCCEEDED"
    assert result["items"][0]["content_safety_state"] == state


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"has_sensitive_hit": True}, {"input", "output", "both"}),
        ({"has_sensitive_hit": False}, {"clean"}),
        ({"sensitive_direction": "INPUT"}, {"input", "both"}),
        ({"sensitive_direction": "OUTPUT"}, {"output", "both"}),
        ({"sensitive_direction": "BOTH"}, {"both"}),
        ({"has_sensitive_hit": False, "sensitive_direction": "INPUT"}, set()),
    ],
)
async def test_request_hit_and_direction_filters_intersect_user_model_and_time(
    query_api, content_safety_native_audit, filters, expected
):
    api = query_api
    labels = {}
    for label, incoming, outgoing in (
        ("clean", False, False),
        ("input", True, False),
        ("output", False, True),
        ("both", True, True),
    ):
        row = store(
            api,
            content_safety_native_audit,
            has_sensitive_hit=incoming or outgoing,
            input_sensitive_hit=incoming,
            output_sensitive_hit=outgoing,
            content_safety_state="BLOCKED" if incoming or outgoing else "UNREPORTED",
        )
        labels[row.request_id] = label
    store(api, content_safety_native_audit, user_id=22, model_id=8, has_sensitive_hit=True)
    result = data(await get(api, "/requests", user_id=11, model_id=7, **filters, **window(api)))
    assert {labels[item["request_id"]] for item in result["items"]} == expected


async def test_main_request_window_defaults_to_seven_days_and_rejects_over_31(query_api, content_safety_native_audit):
    api = query_api
    for days in (1, 6, 8, 30):
        store(api, content_safety_native_audit, started_at=api.clock.now() - timedelta(days=days))
    assert len(data(await get(api, "/requests"))["items"]) == 2
    extended = data(
        await get(
            api,
            "/requests",
            start_at=(api.clock.now() - timedelta(days=31)).isoformat(),
            end_at=api.clock.now().isoformat(),
        )
    )
    assert len(extended["items"]) == 4
    invalid(
        await get(
            api,
            "/requests",
            start_at=(api.clock.now() - timedelta(days=32)).isoformat(),
            end_at=api.clock.now().isoformat(),
        )
    )


async def test_external_detail_preserves_null_axes_and_resolves_available_events(query_api, content_safety_event):
    api = query_api
    raw = content_safety_event(session_id=None)
    _, row, _ = committed_merge(api.engine, content_safety_projection, raw)
    detail = data(await get(api, "/requests/" + row.request_id))
    assert detail["record_origin"] == "EXTERNAL_SAFETY" and detail["audit_status"] == "NOT_APPLICABLE"
    assert detail["model_entered"] is False and detail["model_started_at"] is None
    assert all(
        detail[key] is None
        for key in ("model_result", "response_result", "usage_settlement", "effective_mode", "session_id", "usage")
    )
    assert detail["has_sensitive_hit"] and detail["input_sensitive_hit"] and not detail["output_sensitive_hit"]
    assert detail["details_status"] == "AVAILABLE"
    assert detail["source_id"] == raw["source_id"] and detail["gateway_request_id"] == raw["gateway_request_id"]
    listed = data(await get(api, "/requests", audit_status="NOT_APPLICABLE", has_sensitive_hit=True, **window(api)))
    assert [item["request_id"] for item in listed["items"]] == [row.request_id]
    assert listed["items"][0]["details_status"] == "PENDING"


@pytest.mark.parametrize("state", ["UNREPORTED", "AVAILABLE", "PURGED"])
async def test_request_event_details_distinguish_missing_and_retained_evidence(
    query_api, content_safety_event, content_safety_native_audit, state
):
    api = query_api
    if state == "UNREPORTED":
        row = store(api, content_safety_native_audit)
    else:
        _, row, _ = committed_merge(api.engine, content_safety_projection, content_safety_event(session_id=None))
        if state == "PURGED":
            with tenant_session(api.engine) as session, session.begin():
                session.execute(delete(Fact).where(Fact.tenant_id == 101, Fact.audit_request_id == row.request_id))
    result = data(await get(api, f"/requests/{row.request_id}/content-safety-events"))
    assert result["details_status"] == state
    assert len(result["items"]) == (1 if state == "AVAILABLE" else 0)
    detail = data(await get(api, "/requests/" + row.request_id))
    assert detail["details_status"] == state
    assert detail["has_sensitive_hit"] is (state != "UNREPORTED")


async def test_departed_observed_user_remains_queryable_without_current_membership_lookup(
    query_api, content_safety_event
):
    api = query_api
    raw = content_safety_event(session_id=None)
    _, row, _ = committed_merge(api.engine, content_safety_projection, raw)
    with tenant_session(api.engine) as session, session.begin():
        user = session.get(User, 11)
        user.delete = 1
        session.add(user)
    assert [item["request_id"] for item in data(await get(api, "/requests", user_id=11, **window(api)))["items"]] == [
        row.request_id
    ]
    assert data(await get(api, "/requests/" + row.request_id))["user_id"] == 11
    assert data(await get(api, f"/requests/{row.request_id}/content-safety-events"))["items"][0]["user_id"] == "11"
    assert set(api.actor_reads) == set(api.memberships) == {41}


@pytest.mark.parametrize(
    "path",
    ["/requests", "/content-safety-events", "/requests/00000000-0000-4000-8000-000000000001/content-safety-events"],
)
async def test_ordinary_logged_in_actor_is_denied_by_existing_administrator_authority(query_api, path):
    api = query_api
    response = await get(api, path, actor=42)
    assert response.status_code == 403
    assert api.scopes == []


@pytest.mark.parametrize("path", ["/requests", "/content-safety-events"])
async def test_tenant_administrator_cannot_expand_to_another_tenant(query_api, path):
    api = query_api
    assert (await get(api, path, tenant_id=202)).status_code == 403
    assert api.scopes == []


async def test_super_admin_explicit_targets_and_active_scope_are_enforced(query_api, content_safety_native_audit):
    api = query_api
    first = store(api, content_safety_native_audit)
    foreign = store(api, content_safety_native_audit, tenant=202)
    assert [
        item["request_id"] for item in data(await get(api, "/requests", actor=1, tenant_id=101, **window(api)))["items"]
    ] == [first.request_id]
    assert [
        item["request_id"] for item in data(await get(api, "/requests", actor=1, tenant_id=202, **window(api)))["items"]
    ] == [foreign.request_id]
    assert (await get(api, "/requests", actor=1, admin_scope=202, tenant_id=101, **window(api))).status_code == 403
    assert [
        item["request_id"]
        for item in data(await get(api, "/requests", actor=1, admin_scope=202, **window(api)))["items"]
    ] == [foreign.request_id]
    assert all(scope[1] is None and scope[2] == frozenset({scope[0]}) and not scope[3] for scope in api.scopes)


async def test_event_keysets_bind_request_and_tenant_and_return_only_safe_metadata(query_api, content_safety_event):
    api = query_api
    raw = content_safety_event(session_id=None)
    _, row, _ = committed_merge(api.engine, content_safety_projection, raw)
    committed_merge(api.engine, content_safety_projection, {**raw, "event_id": str(uuid4()), "event_version": 2})
    _, other, _ = committed_merge(api.engine, content_safety_projection, content_safety_event(session_id=None))
    first = data(await get(api, f"/requests/{row.request_id}/content-safety-events", limit=1))
    assert first["next_cursor"]
    second = data(
        await get(api, f"/requests/{row.request_id}/content-safety-events", limit=1, cursor=first["next_cursor"])
    )
    assert first["items"][0]["event_id"] != second["items"][0]["event_id"]
    assert second["next_cursor"] is None
    listed = data(await get(api, "/requests", request_id=row.request_id, **window(api)))
    assert [item["request_id"] for item in listed["items"]] == [row.request_id]
    assert all(
        not set(item) & {"tenant_id", "payload", "payload_hash", "raw_text", "authorization"}
        for item in first["items"] + second["items"]
    )
    invalid(await get(api, f"/requests/{other.request_id}/content-safety-events", cursor=first["next_cursor"]))
    unavailable = await get(api, f"/requests/{row.request_id}/content-safety-events", actor=1, tenant_id=202)
    assert unavailable.status_code == 200 and unavailable.json()["status_code"] == 26132


async def test_main_request_cursor_binds_safety_filter_and_tenant(query_api, content_safety_native_audit):
    api = query_api
    for _ in range(3):
        store(
            api,
            content_safety_native_audit,
            input_sensitive_hit=True,
            output_sensitive_hit=True,
            has_sensitive_hit=True,
        )
    params = {**window(api), "has_sensitive_hit": True, "sensitive_direction": "INPUT", "limit": 1}
    first = data(await get(api, "/requests", **params))
    second = data(await get(api, "/requests", **params, cursor=first["next_cursor"]))
    assert first["items"][0]["request_id"] != second["items"][0]["request_id"]
    invalid(await get(api, "/requests", **{**params, "sensitive_direction": "OUTPUT"}, cursor=first["next_cursor"]))
    invalid(await get(api, "/requests", **params, actor=1, tenant_id=202, cursor=first["next_cursor"]))
    for changed in (
        {"start_at": (api.clock.now() - timedelta(days=6)).isoformat()},
        {"end_at": (api.clock.now() + timedelta(seconds=2)).isoformat()},
    ):
        invalid(await get(api, "/requests", **{**params, **changed}, cursor=first["next_cursor"]))


async def test_unassociated_view_is_bounded_by_request_time_and_cannot_expand_association_scope(
    query_api, content_safety_event
):
    api = query_api
    for days in (1, 6, 8, 30):
        raw = content_safety_event(
            forwarded=True,
            backend_request_id=None,
            stage_results={"input": "PASSED", "output": "BLOCKED"},
            request_started_at=(api.clock.now() - timedelta(days=days)).isoformat(),
        )
        committed_append(content_safety, api.engine, raw)
    default = data(await get(api, "/content-safety-events", association_status="UNASSOCIATED"))
    assert len(default["items"]) == 2
    extended = data(
        await get(
            api,
            "/content-safety-events",
            start_at=(api.clock.now() - timedelta(days=31)).isoformat(),
            end_at=api.clock.now().isoformat(),
        )
    )
    assert len(extended["items"]) == 4
    assert all(item["association_status"] == "UNASSOCIATED" for item in extended["items"])
    assert all("tenant_id" not in item and "payload_hash" not in item for item in extended["items"])
    invalid(
        await get(
            api,
            "/content-safety-events",
            start_at=(api.clock.now() - timedelta(days=32)).isoformat(),
            end_at=api.clock.now().isoformat(),
        )
    )
    invalid(await get(api, "/content-safety-events", association_status="ASSOCIATED"))
    selected = data(
        await get(
            api,
            "/content-safety-events",
            gateway_request_id=raw["gateway_request_id"],
            start_at=(api.clock.now() - timedelta(days=31)).isoformat(),
            end_at=api.clock.now().isoformat(),
        )
    )
    assert [item["gateway_request_id"] for item in selected["items"]] == [raw["gateway_request_id"]]


@pytest.mark.parametrize(
    "query",
    [
        {"has_sensitive_hit": "not-a-bool"},
        {"sensitive_direction": "ANY"},
        {"content_safety_state": "SAFE"},
        {"limit": 101},
        {"cursor": "x" * 2049},
    ],
)
async def test_invalid_filter_and_page_inputs_do_not_silently_disable_safety_filters(query_api, query):
    invalid(await get(query_api, "/requests", **query))


@pytest.mark.parametrize(
    "published,current,pending", [(None, 0, False), (0, 0, False), (5, 5, False), (5, 6, False), (5, 5, True)]
)
async def test_query_readiness_exposes_only_published_safety_watermark(
    query_api, content_safety_native_audit, published, current, pending
):
    api = query_api
    published_at = api.clock.now() - timedelta(seconds=5)
    if published is not None:
        with tenant_session(api.engine) as session, session.begin():
            session.add(
                DshAuditTreeState(
                    tenant_id=101,
                    active=str(uuid4()),
                    revision=2,
                    published_revision=2,
                    summary_revision=3,
                    published_summary_revision=3,
                    safety_summary_revision=current,
                    published_safety_summary_revision=published,
                    published_at=published_at,
                )
            )
    if pending:
        store(api, content_safety_native_audit, group_index_pending=True, has_sensitive_hit=True)
    result = data(await get(api, "/query-readiness"))
    assert result["safety_ready"] is (published is not None and published == current and not pending)
    assert result["safety_summary_version"] == (published or 0)
    if published is None:
        assert result["safety_summary_as_of"] is None
    else:
        observed = datetime.fromisoformat(result["safety_summary_as_of"].replace("Z", "+00:00"))
        assert observed.replace(tzinfo=None) == published_at.replace(tzinfo=None)
    if published != current:
        assert result["safety_ready"] is False


# Coverage AC: AC-45, AC-49, AC-50.
async def test_default_request_cursor_survives_clock_advance_without_freezing_window(
    query_api, content_safety_native_audit
):
    api = query_api
    earlier = [
        store(api, content_safety_native_audit, started_at=api.clock.now() - timedelta(hours=1)) for _ in range(2)
    ]
    entering = store(
        api,
        content_safety_native_audit,
        started_at=api.clock.now() + timedelta(milliseconds=500),
        model_started_at=api.clock.now() + timedelta(milliseconds=500),
    )
    initial = data(await get(api, "/requests"))
    assert {item["request_id"] for item in initial["items"]} == {row.request_id for row in earlier}
    first = data(await get(api, "/requests", limit=1))
    seen = [first["items"][0]["request_id"]]
    cursor = first["next_cursor"]
    api.clock.advance(1)
    for _ in range(3):
        following = data(await get(api, "/requests", cursor=cursor, limit=1))
        seen.extend(item["request_id"] for item in following["items"])
        cursor = following["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 3 and cursor is None
    assert set(seen) == {row.request_id for row in earlier} | {entering.request_id}
