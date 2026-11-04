"""Coverage AC: AC-25, AC-26, AC-35, AC-39, AC-42, AC-43.

Real ASGI routing, shared-HMAC verification and ingestion transactions are used.
Only configuration, clock and SQL session ports are replaced. SQLite establishes
HTTP/transaction behavior, never real MySQL/DM8 durability or concurrency.
"""

import asyncio
import importlib
import threading
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.exc import OperationalError
from starlette.requests import ClientDisconnect

from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
from bisheng.dsh.domain.schemas.content_safety import MAX_EVENT_BYTES
from bisheng.dsh.domain.services.content_safety_ingest import ContentSafetyIngestService
from test.dsh.test_content_safety_ingest import SessionPort, rows
from test.dsh.test_content_safety_repository import tenant_session, wire_hash
from test.dsh.test_content_safety_runtime import PATH, configure, encode, envelope, headers, runtime_port


@pytest.fixture
def api(monkeypatch, content_safety_engine, content_safety_clock):
    # Import the missing paired endpoint rather than supplying a replacement route.
    endpoint = importlib.import_module("bisheng.dsh.api.endpoints.content_safety_events")
    composition = importlib.import_module("bisheng.dsh.api.router")
    runtime = runtime_port()
    settings = configure(monkeypatch, runtime)
    original_verify = runtime.verify_source
    verification = []
    factories = []
    sessions = SessionPort(content_safety_engine)
    service = ContentSafetyIngestService(sessions)

    def verify(raw, request_headers, method, path):
        verification.append((raw, method, path))
        return original_verify(raw, request_headers, method, path, now=content_safety_clock.now())

    def service_factory():
        factories.append(True)
        return service

    monkeypatch.setattr(runtime, "verify_source", verify)
    monkeypatch.setattr(runtime, "get_content_safety_service", service_factory)
    app = FastAPI()
    app.include_router(composition.router, prefix="/api/v1")
    return SimpleNamespace(
        app=app,
        endpoint=endpoint,
        runtime=runtime,
        settings=settings,
        verification=verification,
        factories=factories,
        sessions=sessions,
        engine=content_safety_engine,
        clock=content_safety_clock,
    )


async def post(api, raw, *, path=PATH, request_headers=None, content=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="https://bisheng.invalid"
    ) as client:
        return await client.post(
            path,
            content=raw if content is None else content,
            headers={
                "Content-Type": "application/json",
                **(headers(raw) if request_headers is None else request_headers),
            },
        )


def raw_event(api, event):
    return encode(envelope(event, api.clock))


def assert_error(response, status, code):
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"error", "request_id"}
    assert set(payload["error"]) == {"message", "type", "code"}
    assert payload["error"]["code"] == code
    assert payload["error"]["message"]
    assert str(UUID(payload["request_id"])) == payload["request_id"]
    assert response.headers["X-Request-ID"] == payload["request_id"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "COMMITTED" not in response.text


def assert_receipt(response, event, *, duplicate=False, associated=True):
    assert response.status_code == 200
    assert response.json() == {
        "event_id": event["event_id"],
        "receipt": "COMMITTED",
        "duplicate": duplicate,
        "association_status": "ASSOCIATED" if associated else "UNASSOCIATED",
        "audit_request_id": event["gateway_request_id"] if associated else None,
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert UUID(response.headers["X-Request-ID"])


def test_exact_post_is_registered_once_with_real_dsh_route(api):
    routes = [route for route in api.app.routes if getattr(route, "path", None) == PATH]
    assert len(routes) == 1
    assert routes[0].methods == {"POST"}
    assert isinstance(routes[0], DshRoute)
    assert routes[0].endpoint.__module__ == api.endpoint.__name__


async def test_direct_receipt_is_returned_only_after_real_event_and_summary_commit(api, content_safety_event):
    event = content_safety_event()
    response = await post(api, raw_event(api, event))
    assert_receipt(response, event)
    facts, audits = rows(api.engine)
    assert api.sessions.commits == 1 and len(facts) == len(audits) == 1
    assert facts[0].payload_hash == wire_hash(event)
    assert facts[0].audit_request_id == audits[0].request_id
    assert audits[0].has_sensitive_hit and audits[0].model_entered is False
    assert audits[0].model_result is None and audits[0].usage_settlement is None


async def test_pending_commit_does_not_send_a_success_response(api, content_safety_event):
    entered, release = threading.Event(), threading.Event()

    def held_commit(session):
        session.flush()
        entered.set()
        assert release.wait(3)

    api.sessions.before_commit = held_commit
    event = content_safety_event()
    work = asyncio.create_task(post(api, raw_event(api, event)))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        assert not work.done() and api.sessions.commits == 0
    finally:
        release.set()
        response = await work
    assert_receipt(response, event)
    assert api.sessions.commits == 1


async def test_lost_response_retry_returns_committed_duplicate_without_recounting(api, content_safety_event):
    event = content_safety_event()
    raw = raw_event(api, event)
    assert_receipt(await post(api, raw), event)
    api.clock.advance(1)
    assert_receipt(await post(api, raw_event(api, event)), event, duplicate=True)
    facts, audits = rows(api.engine)
    assert len(facts) == len(audits) == 1
    assert audits[0].safety_projection_version == 1 and facts[0].hit_count == 1 and audits[0].has_sensitive_hit


async def test_forwarded_event_with_unknown_backend_id_acknowledges_only_persisted_fact(api, content_safety_event):
    event = content_safety_event(
        forwarded=True,
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        backend_request_id=None,
    )
    assert_receipt(await post(api, raw_event(api, event)), event, associated=False)
    facts, audits = rows(api.engine)
    assert len(facts) == 1 and audits == []
    assert facts[0].association_status == "UNASSOCIATED"


async def test_query_cannot_override_signed_scope_or_trigger_body_read(api, content_safety_event):
    raw = raw_event(api, content_safety_event())
    consumed = []

    async def chunks():
        consumed.append(True)
        yield raw

    response = await post(api, raw, path=PATH + "?tenant_id=202&source_id=other", content=chunks())
    assert_error(response, 400, "content_safety_event_invalid")
    assert consumed == api.verification == api.factories == api.sessions.sessions == []


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
async def test_other_http_methods_cannot_ingest_or_construct_service(api, method, content_safety_event):
    raw = raw_event(api, content_safety_event())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="https://bisheng.invalid"
    ) as client:
        response = await client.request(method, PATH, content=raw, headers=headers(raw))
    assert response.status_code == 405
    assert api.verification == api.factories == api.sessions.sessions == []


@pytest.mark.parametrize(
    "credentials",
    [
        {},
        {"Authorization": "Bearer synthetic-desktop-token"},
        {"Cookie": "synthetic=browser"},
        {"X-Signature": "0" * 64},
    ],
)
async def test_user_credentials_and_invalid_signature_never_enter_ingestion(api, credentials):
    response = await post(api, b"\xffsynthetic-sensitive-body", request_headers=credentials)
    assert_error(response, 401, "content_safety_authentication_failed")
    assert api.factories == api.sessions.sessions == []
    assert "synthetic-sensitive-body" not in response.text


async def test_signed_tenant_outside_single_tenant_deployment_is_http_403(api, content_safety_event):
    api.settings.multi_tenant.enabled = False
    response = await post(api, raw_event(api, content_safety_event()))
    assert_error(response, 403, "content_safety_authentication_failed")
    assert api.factories == api.sessions.sessions == []


async def test_signed_historical_actor_uses_its_tenant_without_user_token_auth(
    api, content_safety_event, content_safety_identities
):
    event = content_safety_event(identity=content_safety_identities[1])
    raw = raw_event(api, event)
    request_headers = {
        **headers(raw),
        "Authorization": "Bearer synthetic-expired-user-token",
        "Cookie": "synthetic=old-browser",
    }
    assert_receipt(await post(api, raw, request_headers=request_headers), event)
    assert rows(api.engine, 101) == ([], [])
    facts, audits = rows(api.engine, 202)
    assert len(facts) == len(audits) == 1
    assert facts[0].tenant_id == audits[0].tenant_id == 202
    assert all(scope[0] == 202 and not scope[3] for scope in api.sessions.scopes)


@pytest.mark.parametrize("offset", [-301, 301])
async def test_signed_send_time_outside_window_maps_to_http_401(api, content_safety_event, offset):
    event = content_safety_event()
    sent_at = (api.clock.now() + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
    if offset < 0:
        event["request_started_at"] = event["occurred_at"] = sent_at
    raw = encode(envelope(event, api.clock, sent_at=sent_at))
    assert_error(await post(api, raw), 401, "content_safety_authentication_failed")
    assert api.factories == api.sessions.sessions == []


async def test_missing_shared_key_only_disables_this_receiver(api, content_safety_event):
    api.settings.sso_sync.gateway_hmac_secret = ""
    response = await post(api, raw_event(api, content_safety_event()))
    assert_error(response, 503, "content_safety_event_unavailable")
    assert api.factories == api.sessions.sessions == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", 101),
        ("user_id", "0"),
        ("model_id", "9223372036854775808"),
        ("event_id", "synthetic-sensitive-invalid-uuid"),
        ("source_id", "x" * 65),
    ],
)
async def test_signed_invalid_identifiers_return_400_without_echoing_values(api, content_safety_event, field, value):
    event = content_safety_event(**{field: value})
    response = await post(api, raw_event(api, event))
    assert_error(response, 400, "content_safety_event_invalid")
    assert api.factories == api.sessions.sessions == []
    assert "synthetic-sensitive-invalid-uuid" not in response.text
    assert "9223372036854775808" not in response.text


@pytest.mark.parametrize("fault", ["duplicate", "utf8", "depth", "unknown_field"])
async def test_signed_json_failures_are_400_and_never_enter_ingestion(api, content_safety_event, fault):
    event = content_safety_event()
    raw = raw_event(api, event)
    if fault == "duplicate":
        raw = raw.replace(b'"event":{', b'"event":{"user_id":"999",', 1)
    elif fault == "utf8":
        raw = raw.replace(b"synthetic-gateway", b"synthetic-\xff-secret")
    elif fault == "depth":
        nested = "synthetic-sensitive-value"
        for _ in range(17):
            nested = {"nested": nested}
        event["conversation"] = nested
        raw = raw_event(api, event)
    else:
        event["raw_model_body"] = "synthetic-sensitive-value"
        raw = raw_event(api, event)
    response = await post(api, raw)
    assert_error(response, 400, "content_safety_event_invalid")
    assert api.factories == api.sessions.sessions == []
    assert "synthetic-sensitive" not in response.text
    assert "raw_model_body" not in response.text


async def test_exact_64k_original_body_is_accepted_without_reserialization(api, content_safety_event):
    event = content_safety_event()
    raw = raw_event(api, event)
    raw = b"\n" + raw + b" " * (MAX_EVENT_BYTES - len(raw) - 1)
    assert len(raw) == MAX_EVENT_BYTES
    assert_receipt(await post(api, raw), event)
    assert api.verification == [(raw, "POST", PATH)]


async def test_chunked_size_limit_stops_reading_without_trusting_content_length(api):
    observed = []

    async def chunks():
        for number, chunk in enumerate([b" " * MAX_EVENT_BYTES, b" ", b"must-not-be-read"]):
            observed.append(number)
            yield chunk

    response = await post(api, b"", request_headers={"Content-Length": "1"}, content=chunks())
    assert_error(response, 413, "content_safety_event_too_large")
    assert observed == [0, 1]
    assert api.verification == api.factories == api.sessions.sessions == []


async def test_original_chunks_are_read_once_without_receive_replay_or_dto_rehash(
    api, monkeypatch, content_safety_event
):
    event = content_safety_event()
    event.pop("backend_request_id")
    event["conversation"] = {"conversation_id": " synthetic-conversation ", "request_kind": "unsupported-hint"}
    raw = b" \n" + raw_event(api, event) + b"\n"
    observed = []
    streams = []
    original_stream = Request.stream

    async def traced_stream(request):
        receive = request._receive
        streams.append(request)
        try:
            async for chunk in original_stream(request):
                yield chunk
        finally:
            assert request._receive is receive, "The endpoint must not replace ASGI receive for SSO replay"

    async def chunks():
        for number, chunk in enumerate([raw[:19], raw[19:80], raw[80:]]):
            observed.append(number)
            yield chunk

    monkeypatch.setattr(Request, "stream", traced_stream)
    assert_receipt(await post(api, raw, content=chunks()), event)
    assert observed == [0, 1, 2] and len(streams) == 1
    assert api.verification == [(raw, "POST", PATH)]
    facts, _ = rows(api.engine)
    assert facts[0].payload_hash == wire_hash(event)
    changed = {**event, "backend_request_id": None}
    assert_error(await post(api, raw_event(api, changed)), 409, "content_safety_event_conflict")


async def test_conflicting_retry_is_http_409_and_preserves_committed_fact(api, content_safety_event):
    event = content_safety_event()
    assert_receipt(await post(api, raw_event(api, event)), event)
    changed = {**event, "rule_refs": ["different-rule"]}
    response = await post(api, raw_event(api, changed))
    assert_error(response, 409, "content_safety_event_conflict")
    facts, audits = rows(api.engine)
    assert len(facts) == len(audits) == 1 and facts[0].payload_hash == wire_hash(event)


async def test_retention_rejection_is_http_410_without_creating_a_fact(api, content_safety_event):
    with tenant_session(api.engine, 101) as session:
        session.add(DshModelAuditSetting(tenant_id=101, audit_deleted_before=api.clock.now() + timedelta(seconds=1)))
        session.commit()
    response = await post(api, raw_event(api, content_safety_event()))
    assert_error(response, 410, "content_safety_event_expired")
    assert rows(api.engine) == ([], [])


async def test_commit_failure_is_http_503_without_a_success_receipt_or_partial_fact(api, content_safety_event):
    def fail_commit(_session):
        raise OperationalError("synthetic SQL contains private payload", {}, RuntimeError("synthetic-secret"))

    api.sessions.before_commit = fail_commit
    response = await post(api, raw_event(api, content_safety_event()))
    assert_error(response, 503, "content_safety_event_unavailable")
    assert "synthetic" not in response.text and "SQL" not in response.text
    assert rows(api.engine) == ([], [])


async def test_unexpected_service_assembly_failure_is_safe_http_503(api, monkeypatch, content_safety_event):
    def unavailable():
        raise RuntimeError("synthetic-sensitive-payload and credential")

    monkeypatch.setattr(api.runtime, "get_content_safety_service", unavailable)
    response = await post(api, raw_event(api, content_safety_event()))
    assert_error(response, 503, "content_safety_event_unavailable")
    assert "synthetic-sensitive" not in response.text
    assert api.sessions.sessions == []


async def test_upload_disconnect_never_fabricates_a_committed_response(api, content_safety_event):
    raw = raw_event(api, content_safety_event())
    incoming = iter(
        [
            {"type": "http.request", "body": raw[:32], "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    messages = []

    async def receive():
        return next(incoming)

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "https",
        "method": "POST",
        "path": PATH,
        "raw_path": PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers(raw).items()],
        "client": ("127.0.0.1", 1),
        "server": ("bisheng.invalid", 443),
    }
    try:
        await api.app(scope, receive, send)
    except ClientDisconnect:
        # The disconnected upload has no HTTP peer; propagating it is expected.
        pass
    assert not any(message.get("status") == 200 for message in messages)
    assert not any(b"COMMITTED" in message.get("body", b"") for message in messages)
    assert api.verification == api.factories == api.sessions.sessions == []
