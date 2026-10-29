"""Real pre-forward rejection probes; local assertions never replace live evidence.

Reuse the frozen protocol fixture's explicit0600 settings, distinct ordinary-user
PKCE, private model checks and tenant policy CAS restoration. The seven live
cases require DSH_SAFETY_E2E=1 plus all existing live protocol prerequisites.
"""

import asyncio
import json
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest

from test.dsh import test_content_safety_protocol_e2e as protocol_e2e
from test.dsh.test_content_safety_protocol_e2e import _body, _require, _uuid
from test.e2e.helpers.dsh_content_safety import LiveSafetyError, checked_json

# Explicit registration reuses the frozen real PKCE/CAS/0600 fixture.
live_protocol = protocol_e2e.live_protocol

REQUEST_LIMIT = 32 * 1024 * 1024
PUBLIC_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
CASES = [(protocol, kind) for protocol in ("chat", "responses") for kind in ("malformed", "duplicate", "unknown")]
CASES.append(("chat", "oversized"))


def _response(
    status=400, *, code="invalid_request", public=PUBLIC_ID, backend=None, identity=PUBLIC_ID, mime="application/json"
):
    headers = {"Content-Type": mime}
    if public is not None:
        headers["X-Request-ID"] = public
    if backend is not None:
        headers["X-Backend-Request-ID"] = backend
    return httpx.Response(status, headers=headers, json={"error": {"code": code}, "request_id": identity})


@pytest.mark.parametrize("protocol,kind", CASES)
def test_raw_boundary_bodies_exercise_actual_parser_edges(protocol, kind):
    """Coverage AC: AC-25, AC-26; independent JSON and byte-count construction oracle."""
    raw = _raw_request(protocol, kind, 8, "e2e-f111-live-synthetic-case", "e2e-f111-live-synthetic-conversation")
    assert isinstance(raw, bytes)
    assert b"F111_SCENARIO:e2e-f111-live-synthetic-case" in raw
    if kind == "malformed":
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)
    elif kind == "duplicate":
        pairs = json.loads(raw, object_pairs_hook=list)
        assert sum(key == "model" for key, _ in pairs) == 2
        assert [value for key, value in pairs if key == "model"] == ["bisheng:8", "bisheng:8"]
    else:
        parsed = json.loads(raw)
        if kind == "oversized":
            assert len(raw) == 33_554_433
            assert parsed["model"] == "bisheng:8"
            assert isinstance(parsed["messages"][0]["content"], str)
        elif protocol == "chat":
            assert parsed["messages"][0]["content"][0]["type"] == "unknown"
        else:
            assert parsed["input"][0]["type"] == "unknown"


def test_exact_invalid_request_response_is_accepted():
    """Coverage AC: AC-25, AC-26; the actual httpx response identity is retained."""
    assert _assert_rejection(_response()) == PUBLIC_ID


@pytest.mark.parametrize(
    "changes",
    [
        {"status": 200},
        {"status": 403},
        {"status": 413},
        {"status": 503},
        {"code": "content_blocked"},
        {"code": "check_unavailable"},
        {"code": ""},
        {"public": None},
        {"public": "invalid"},
        {"backend": ""},
        {"backend": OTHER_ID},
        {"identity": OTHER_ID},
        {"identity": ""},
        {"mime": "text/event-stream"},
        {"mime": "text/plain"},
    ],
)
def test_misattributed_or_wrong_rejection_never_passes(changes):
    """Coverage AC: AC-25, AC-26, AC-33; no forward/error/block substitution."""
    with pytest.raises(LiveSafetyError):
        _assert_rejection(_response(**changes))


@pytest.mark.parametrize("raw", [b"{invalid", b"[]"])
def test_invalid_error_envelope_is_rejected_without_echo(raw):
    """Coverage AC: AC-25; malformed error envelopes do not become success."""
    response = httpx.Response(400, headers={"Content-Type": "application/json", "X-Request-ID": PUBLIC_ID}, content=raw)
    with pytest.raises(LiveSafetyError):
        _assert_rejection(response)


@pytest.mark.parametrize(
    "page",
    [
        {},
        {"items": None, "next_cursor": None},
        {"items": [{}], "next_cursor": None},
        {"items": [], "next_cursor": "more"},
        {"items": []},
    ],
)
def test_incomplete_or_nonempty_audit_page_does_not_prove_absence(page):
    """Coverage AC: AC-33, AC-34; incomplete pagination cannot prove no event."""
    with pytest.raises(LiveSafetyError):
        _assert_empty_page(page)


def test_complete_empty_audit_page_proves_observed_absence():
    """Coverage AC: AC-33, AC-34; only a complete empty result is accepted."""
    _assert_empty_page({"items": [], "next_cursor": None})


def _raw_request(protocol, kind, model_id, scenario, conversation):
    if (protocol, kind) not in CASES or type(model_id) is not int or not 0 < model_id <= 2**63 - 1:
        raise LiveSafetyError("Invalid boundary request parameters")
    marker = "F111_SCENARIO:" + scenario
    payload = {
        "model": f"bisheng:{model_id}",
        "stream": False,
        "audit_context": {"conversation_id": conversation, "request_kind": "chat", "session_origin": "main"},
    }
    if protocol == "chat":
        payload["messages"] = [{"role": "user", "content": marker}]
        if kind == "unknown":
            payload["messages"][0]["content"] = [{"type": "unknown", "text": marker}]
        elif kind == "oversized":
            payload["messages"][0]["content"] = marker + " BOUNDARY_PADDING_TOKEN"
    else:
        payload["input"] = [{"role": "user", "content": marker}]
        if kind == "unknown":
            payload["input"] = [{"type": "unknown", "text": marker}]
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if kind == "malformed":
        return raw[:-1]
    if kind == "duplicate":
        return ('{"model":"bisheng:' + str(model_id) + '",').encode("ascii") + raw[1:]
    if kind == "oversized":
        token = b"BOUNDARY_PADDING_TOKEN"
        _require(raw.count(token) == 1, "Boundary padding token was ambiguous")
        padding = REQUEST_LIMIT + 1 - len(raw) + len(token)
        _require(padding > 0, "Boundary request metadata exceeded its budget")
        raw = raw.replace(token, b"a" * padding, 1)
        _require(len(raw) == REQUEST_LIMIT + 1, "Boundary request did not have the exact byte length")
    return raw


def _assert_capabilities(caps):
    _require(
        caps.get("available") is True
        and caps.get("enabled") is True
        and caps.get("configuration_ready") is True
        and isinstance(caps.get("limits"), dict)
        and type(caps["limits"].get("request_max_bytes")) is int
        and caps["limits"]["request_max_bytes"] == REQUEST_LIMIT,
        "Boundary suite requires the advertised32MiB request limit and a ready Gateway",
    )


def _assert_rejection(response):
    _require(response.status_code == 400, "Boundary request did not return HTTP400")
    _require(
        response.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json",
        "Boundary request did not return a JSON error",
    )
    _require("x-backend-request-id" not in response.headers, "Rejected request reached Backend model routing")
    public = _uuid(response.headers.get("x-request-id"))
    body = _body(response)
    error = body.get("error")
    _require(isinstance(error, dict) and error.get("code") == "invalid_request", "Boundary error code changed")
    _require(_uuid(body.get("request_id")) == public, "Boundary error identity disagrees with response header")
    return public


def _assert_empty_page(page):
    _require(
        isinstance(page, dict)
        and isinstance(page.get("items"), list)
        and not page["items"]
        and "next_cursor" in page
        and page["next_cursor"] is None,
        "Boundary rejection unexpectedly produced audit evidence or an incomplete page",
    )


def _assert_zero_calls(before, after, counts):
    _require(
        type(before.get("model_posts")) is int
        and type(after.get("model_posts")) is int
        and before["model_posts"] >= 0
        and before["model_posts"] == after["model_posts"]
        and before.get("active") == 0
        and after.get("active") == 0,
        "Boundary request changed physical upstream request counters",
    )
    _require(
        all(
            type(counts.get(key)) is int and counts[key] == 0
            for key in ("requests", "completed", "finished", "cancelled", "usage_emitted", "active")
        ),
        "Boundary request reached the attributed provider scenario",
    )


async def _no_audit_evidence(run, conversation, gateway_id):
    path = run.http.settings.api_base + "/dsh/admin/model-audit"
    # Both available list filters are exact; a new UUID/conversation never needs a broad tenant scan.
    for query in ({"conversation_id": conversation}, {"request_id": gateway_id}):
        page = checked_json(await run.http.admin.get(path + "/requests", params={"tenant_id": 1, "limit": 1, **query}))
        _assert_empty_page(page)
    events = checked_json(
        await run.http.admin.get(
            path + "/content-safety-events",
            params={"tenant_id": 1, "limit": 1, "gateway_request_id": gateway_id, "association_status": "UNASSOCIATED"},
        )
    )
    _assert_empty_page(events)


@pytest.mark.e2e
@pytest.mark.skipif(os.environ.get("DSH_SAFETY_E2E") != "1", reason="Explicit live DSH safety environment required")
@pytest.mark.parametrize("protocol,kind", CASES)
async def test_invalid_model_request_never_forwards_or_creates_audit(live_protocol, protocol, kind, record_property):
    """Coverage AC: AC-25, AC-26, AC-33, AC-34; real pre-forward400, no fabricated ERROR event."""
    run = live_protocol
    caps = checked_json(
        await run.http.admin.get(
            run.http.settings.api_base.removesuffix("/api/v1") + "/api/sensitive/dsh/capabilities",
            params={"tenant_id": 1},
        )
    )
    _assert_capabilities(caps)
    scenario = run.http.settings.prefix + uuid.uuid4().hex[:16]
    conversation = scenario + "-boundary"
    await run.http.provider_scenario(scenario, text="Safe unused boundary scenario.")
    run.scenarios.append(scenario)
    before = await run.http.provider_totals()
    initial = await run.http.provider_counts(scenario)
    _assert_zero_calls(before, before, initial)
    used_before = await run.used()
    raw = _raw_request(protocol, kind, run.model(protocol), scenario, conversation)
    byte_count = len(raw)
    endpoint = "chat/completions" if protocol == "chat" else "responses"
    response = await run.http.native.post(
        f"{run.http.settings.api_base}/dsh/{endpoint}",
        headers=run.headers | {"Content-Type": "application/json"},
        content=raw,
    )
    gateway_id = _assert_rejection(response)
    del raw
    # Observed absence is checked twice across a bounded interval, never interpreted as PASSED.
    for _ in range(2):
        await asyncio.sleep(1)
        after = await run.http.provider_totals()
        counts = await run.http.provider_counts(scenario)
        _assert_zero_calls(before, after, counts)
        await _no_audit_evidence(run, conversation, gateway_id)
        _require(await run.used() == used_before, "Boundary rejection changed personal allowance usage")
    record_property(
        "f111_boundary",
        json.dumps(
            {
                "protocol": protocol,
                "case": kind,
                "request_id": gateway_id,
                "body_bytes": byte_count,
                "status": response.status_code,
                "global_delta": after["model_posts"] - before["model_posts"],
                "scenario_requests": counts["requests"],
                "usage_unchanged": True,
                "absence_samples": 2,
            },
            sort_keys=True,
        ),
    )


@pytest.mark.parametrize("changed", ["global", "active", "requests", "completed", "usage_emitted", "missing"])
def test_physical_or_attributed_call_cannot_pass_zero_evidence(changed):
    """Coverage AC: AC-25, AC-26; opaque or unmarked upstream arrivals must also fail."""
    before = {"model_posts": 11, "active": 0}
    after = dict(before)
    counts = dict.fromkeys(("requests", "completed", "finished", "cancelled", "usage_emitted", "active"), 0)
    if changed == "global":
        after["model_posts"] += 1
    elif changed == "active":
        after["active"] = 1
    elif changed == "missing":
        del counts["requests"]
    else:
        counts[changed] = 1
    with pytest.raises(LiveSafetyError):
        _assert_zero_calls(before, after, counts)


def test_zero_provider_evidence_accepts_real_initialized_counter_shape():
    """Coverage AC: AC-25, AC-26; absent model activity remains an observation, not a success stage."""
    counts = dict.fromkeys(("requests", "completed", "finished", "cancelled", "usage_emitted", "active"), 0)
    _assert_zero_calls({"model_posts": 31, "active": 0}, {"model_posts": 31, "active": 0}, counts)


async def test_audit_absence_uses_exact_supported_http_filters():
    """Coverage AC: AC-33, AC-34; exercise actual HTTP query construction and wrapped envelopes."""
    seen = []

    def receive(request):
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"status_code": 200, "data": {"items": [], "next_cursor": None}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        run = SimpleNamespace(
            http=SimpleNamespace(settings=SimpleNamespace(api_base="http://127.0.0.1:1/api/v1"), admin=client)
        )
        await _no_audit_evidence(run, "owned-conversation", PUBLIC_ID)
    path = "/api/v1/dsh/admin/model-audit"
    assert seen == [
        ("GET", path + "/requests", {"tenant_id": "1", "limit": "1", "conversation_id": "owned-conversation"}),
        ("GET", path + "/requests", {"tenant_id": "1", "limit": "1", "request_id": PUBLIC_ID}),
        (
            "GET",
            path + "/content-safety-events",
            {"tenant_id": "1", "limit": "1", "gateway_request_id": PUBLIC_ID, "association_status": "UNASSOCIATED"},
        ),
    ]


async def test_existing_native_record_fails_absence_before_event_lookup():
    """Coverage AC: AC-33, AC-34; a real HTTP row cannot be hidden by the later empty event page."""
    seen = []

    def receive(request):
        seen.append(request.url.path)
        return httpx.Response(
            200, json={"status_code": 200, "data": {"items": [{"request_id": PUBLIC_ID}], "next_cursor": None}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        run = SimpleNamespace(
            http=SimpleNamespace(settings=SimpleNamespace(api_base="http://127.0.0.1:1/api/v1"), admin=client)
        )
        with pytest.raises(LiveSafetyError):
            await _no_audit_evidence(run, "owned-conversation", PUBLIC_ID)
    assert seen == ["/api/v1/dsh/admin/model-audit/requests"]


def test_real_capability_wire_field_and_limit_are_accepted():
    """Coverage AC: AC-26; actual Gateway @JsonProperty field, not its Java record accessor."""
    response = httpx.Response(
        200,
        json={
            "status_code": 200,
            "data": {
                "available": True,
                "enabled": True,
                "configuration_ready": True,
                "builtin_digest": "a" * 64,
                "limits": {"request_max_bytes": 33_554_432},
            },
        },
    )
    _assert_capabilities(checked_json(response))


@pytest.mark.parametrize(
    "caps",
    [
        {"available": True, "enabled": True, "config_ready": True, "limits": {"request_max_bytes": REQUEST_LIMIT}},
        {
            "available": True,
            "enabled": True,
            "configuration_ready": False,
            "config_ready": True,
            "limits": {"request_max_bytes": REQUEST_LIMIT},
        },
        {
            "available": False,
            "enabled": True,
            "configuration_ready": True,
            "limits": {"request_max_bytes": REQUEST_LIMIT},
        },
        {
            "available": True,
            "enabled": False,
            "configuration_ready": True,
            "limits": {"request_max_bytes": REQUEST_LIMIT},
        },
        {"available": True, "enabled": True, "configuration_ready": True, "limits": {"request_max_bytes": True}},
        {
            "available": True,
            "enabled": True,
            "configuration_ready": True,
            "limits": {"request_max_bytes": str(REQUEST_LIMIT)},
        },
        {
            "available": True,
            "enabled": True,
            "configuration_ready": True,
            "limits": {"request_max_bytes": REQUEST_LIMIT - 1},
        },
        {"available": True, "enabled": True, "configuration_ready": True, "limits": None},
    ],
)
def test_unready_or_wrong_spelling_capability_cannot_start_boundary_requests(caps):
    """Coverage AC: AC-26; old spelling and malformed/mismatched limits fail closed."""
    response = httpx.Response(200, json={"status_code": 200, "data": caps})
    with pytest.raises(LiveSafetyError):
        _assert_capabilities(checked_json(response))
