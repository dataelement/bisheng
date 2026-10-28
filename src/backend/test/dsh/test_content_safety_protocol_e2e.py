"""Live Gateway → Backend → synthetic Provider regression; never an ASGI substitute.

Explicit DSH_SAFETY_E2E=1, frozen helper parameters, exclusive-provider permission,
METADATA/CONTENT audit and two test-owned models are required. Run serially with
--junitxml to retain nonsecret request/counter evidence. Deployment-off, isolated
no-Gateway and destructive capacity/recovery checks require their own environment.
"""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from test.e2e.helpers.auth import auth_headers
from test.e2e.helpers.dsh import logout_desktop_session
from test.e2e.helpers.dsh_content_safety import (
    LiveSafetyError,
    LiveSafetyHTTP,
    LiveSafetySettings,
    SafetyPolicyLease,
    checked_json,
    wait_until,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("DSH_SAFETY_E2E") != "1", reason="Explicit live DSH safety environment required"),
]
MODES = [("chat", False), ("chat", True), ("responses", False), ("responses", True)]
NOTICE = "This request was stopped by the test content policy."


def _require(condition, message):
    if not condition:
        raise LiveSafetyError(message)


def _uuid(value):
    try:
        result = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise LiveSafetyError("Model response did not provide a valid request identifier") from None
    _require(result == value.lower(), "Model response returned a noncanonical request identifier")
    return result


def _request_ids(response):
    """Synthetic errors keep a public Gateway ID alongside the known backend ID."""
    public = _uuid(response.headers.get("x-request-id"))
    backend = _uuid(response.headers["x-backend-request-id"]) if "x-backend-request-id" in response.headers else None
    return public, backend, backend or public


def _events(response):
    """Decode observed SSE without repairing JSON, tools or sequence numbers."""
    _require(response.status_code == 200, "Streaming model request did not start successfully")
    _require(response.headers.get("content-type", "").startswith("text/event-stream"), "Expected native SSE")
    try:
        wire = response.content.decode("utf-8")
        frames = wire.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
        result = []
        for frame in frames:
            data = "\n".join(line[5:].removeprefix(" ") for line in frame.splitlines() if line.startswith("data:"))
            if data:
                result.append("[DONE]" if data == "[DONE]" else json.loads(data))
        _require(bool(result), "Model stream contained no protocol events")
        return result
    except (UnicodeError, ValueError):
        raise LiveSafetyError("Model stream contained invalid UTF-8 or JSON") from None


def _body(response):
    try:
        result = response.json()
    except ValueError:
        raise LiveSafetyError("Model request returned invalid JSON") from None
    _require(isinstance(result, dict), "Model request returned an invalid envelope")
    return result


def _text(response, protocol, stream):
    if not stream:
        body = _body(response)
        if protocol == "chat":
            return body["choices"][0]["message"].get("content") or ""
        return "".join(
            part.get("text", "") for item in body["output"] if item["type"] == "message" for part in item["content"]
        )
    events = _events(response)
    if protocol == "chat":
        return "".join(
            choice.get("delta", {}).get("content", "") or ""
            for event in events
            if isinstance(event, dict)
            for choice in event.get("choices", [])
        )
    return "".join(
        event["delta"]
        for event in events
        if isinstance(event, dict) and event.get("type") == "response.output_text.delta"
    )


def _passed(response, protocol, stream, expected="Safe synthetic reply."):
    _require(response.status_code == 200, "Safe request failed")
    _require(_text(response, protocol, stream) == expected, "Safe response text changed")
    if not stream:
        body = _body(response)
        if protocol == "chat":
            _require(body["choices"][0]["finish_reason"] == "stop", "Safe Chat response did not finish normally")
            _require(body["usage"]["total_tokens"] == 80, "Safe Chat usage changed")
        else:
            _require(
                body["status"] == "completed" and body["usage"]["total_tokens"] == 80, "Safe Responses result changed"
            )
        return
    events = _events(response)
    if protocol == "chat":
        reasons = [
            choice.get("finish_reason")
            for event in events
            if isinstance(event, dict)
            for choice in event.get("choices", [])
            if choice.get("finish_reason")
        ]
        _require(reasons == ["stop"] and events[-1] == "[DONE]", "Safe Chat terminal order changed")
        _require(
            any(isinstance(event, dict) and (event.get("usage") or {}).get("total_tokens") == 80 for event in events),
            "Safe streamed Chat usage missing",
        )
    else:
        numbers = [event["sequence_number"] for event in events if isinstance(event, dict)]
        _require(numbers == sorted(set(numbers)), "Responses sequence changed or replayed")
        _require(
            events[0]["type"] == "response.created" and events[-1]["type"] == "response.completed",
            "Responses terminal order changed",
        )
        _require(events[-1]["response"]["usage"]["total_tokens"] == 80, "Safe streamed Responses usage missing")


def _readable_observations(events, protocol):
    """Collect delivered fixture text per item/channel without joining unrelated text."""
    domains = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        if protocol == "chat":
            for choice in event.get("choices", []):
                for channel in ("content", "reasoning_content"):
                    value = choice.get("delta", {}).get(channel)
                    if isinstance(value, str):
                        key = (choice.get("index", 0), channel)
                        domains.setdefault(key, {}).setdefault(0, []).append(value)
            continue
        kind = event.get("type", "")
        for channel in ("output_text", "refusal", "reasoning_text", "reasoning_summary_text"):
            if kind not in {f"response.{channel}.delta", f"response.{channel}.done"}:
                continue
            position = (
                event.get("summary_index", 0) if channel == "reasoning_summary_text" else event.get("content_index", 0)
            )
            key = (event.get("output_index", 0), event.get("item_id"), channel, kind.endswith(".done"))
            value = event.get("text", "") if kind.endswith(".done") else event.get("delta", "")
            if isinstance(value, str):
                domains.setdefault(key, {}).setdefault(position, []).append(value)
        items = [event["item"]] if isinstance(event.get("item"), dict) else []
        items += (event.get("response") or {}).get("output", [])
        for item in items:
            for channel in ("content", "summary"):
                parts = item.get(channel, [])
                yield "".join(part.get("text", "") for part in parts if isinstance(part.get("text", ""), str))
    for slots in domains.values():
        previous, contiguous = None, ""
        for index, pieces in sorted(slots.items()):
            if previous is not None and index != previous + 1:
                yield contiguous
                contiguous = ""
            contiguous += "".join(pieces)
            previous = index
        yield contiguous


def _blocked(response, protocol, stream, word, *, input_block=False):
    if input_block or not stream:
        body = _body(response)
        _require(
            response.status_code == 403 and body.get("error", {}).get("code") == "content_blocked",
            "Expected explicit HTTP content blocking",
        )
        _require(body["error"].get("message") == NOTICE, "Tenant blocking notice changed")
        _require(
            "choices" not in body and "output" not in body and word not in json.dumps(body, ensure_ascii=False),
            "Blocked nonstream response exposed model output",
        )
        return
    events = _events(response)
    _require(
        word not in json.dumps(events, ensure_ascii=False)
        and all(word not in text for text in _readable_observations(events, protocol)),
        "Blocked stream exposed the complete matched word",
    )
    if protocol == "chat":
        chunks = [event for event in events if isinstance(event, dict)]
        reasons = [
            choice.get("finish_reason")
            for event in chunks
            for choice in event.get("choices", [])
            if choice.get("finish_reason")
        ]
        _require(
            reasons == ["content_filter"] and events[-1] == "[DONE]", "Blocked Chat stream had an incorrect terminal"
        )
        notices = [event["content_safety"] for event in chunks if "content_safety" in event]
        _require(
            len(notices) == 1 and notices[0].get("code") == "content_blocked" and notices[0].get("message") == NOTICE,
            "Chat blocking notice missing",
        )
    else:
        errors = [event for event in events if isinstance(event, dict) and event.get("type") == "error"]
        _require(
            len(errors) == 1 and errors[0].get("code") == "content_blocked" and errors[0].get("message") == NOTICE,
            "Responses blocking error missing",
        )
        _require(
            not any(isinstance(event, dict) and event.get("type") == "response.completed" for event in events),
            "Blocked stream exposed successful completion",
        )


@dataclass
class Exchange:
    response: httpx.Response
    protocol: str
    stream: bool
    conversation: str
    scenario: str
    counts: dict
    global_delta: int
    response_request_id: str
    backend_request_id: str | None
    audit_request_id: str
    active_at_client_end: int


class ProtocolRun:
    """Feature-specific requests and assertions use the frozen real HTTP ports."""

    def __init__(self, http, tokens, profile, record):
        self.http, self.tokens, self.profile, self.record = http, tokens, profile, record
        self.word = "f111blocked" + uuid.uuid4().hex[:12]
        self.scenarios = []
        self.rates = {}

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.tokens["access_token"]}

    def model(self, protocol):
        return self.http.settings.chat_model_id if protocol == "chat" else self.http.settings.responses_model_id

    def payload(self, protocol, stream, scenario, conversation, *, matched=False):
        prompt = f"F111_SCENARIO:{scenario}" + (" " + self.word if matched else "")
        result = {
            "model": f"bisheng:{self.model(protocol)}",
            "stream": stream,
            "audit_context": {"conversation_id": conversation, "request_kind": "chat", "session_origin": "main"},
        }
        if protocol == "chat":
            result["messages"] = [{"role": "user", "content": prompt}]
            if stream:
                result["stream_options"] = {"include_usage": True}
        else:
            result["input"] = [{"role": "user", "content": prompt}]
            result["store"] = False
        return result

    async def used(self):
        result = checked_json(
            await self.http.native.get(f"{self.http.settings.api_base}/dsh/usage", headers=self.headers), unified=False
        )
        _require(
            type(result.get("used")) is int and result.get("quota_state") in {"available", "exhausted"},
            "Personal usage ledger is unavailable",
        )
        return result["used"]

    async def exchange(self, protocol, stream, *, matched=False, configure=None, mutate=None):
        identifier = self.http.settings.prefix + uuid.uuid4().hex[:16]
        await self.http.provider_scenario(identifier, **({"text": "Safe synthetic reply."} | (configure or {})))
        self.scenarios.append(identifier)
        conversation = identifier + "-conversation"
        payload = self.payload(protocol, stream, identifier, conversation, matched=matched)
        if mutate:
            mutate(payload)
        before = await self.http.provider_totals()
        _require(before["active"] == 0, "Another model request was active in the exclusive provider")
        response = await self.http.native.post(
            f"{self.http.settings.api_base}/dsh/{'chat/completions' if protocol == 'chat' else 'responses'}",
            headers=self.headers,
            json=payload,
        )

        observed = await self.http.provider_counts(identifier)

        async def counters():
            return {
                "global": await self.http.provider_totals(),
                "scenario": await self.http.provider_counts(identifier),
            }

        after = await wait_until(
            counters, lambda item: item["global"]["active"] == 0 and item["scenario"]["active"] == 0, timeout=40
        )
        delta = after["global"]["model_posts"] - before["model_posts"]
        response_id, backend_id, audit_id = _request_ids(response)
        self.record(
            "f111_request",
            json.dumps(
                {
                    "request_id": audit_id,
                    "response_request_id": response_id,
                    "backend_request_id": backend_id,
                    "scenario": identifier,
                    "protocol": protocol,
                    "stream": stream,
                    "status": response.status_code,
                    "global_delta": delta,
                    "scenario_counts": after["scenario"],
                    "active_at_client_end": observed["active"],
                },
                sort_keys=True,
            ),
        )
        return Exchange(
            response,
            protocol,
            stream,
            conversation,
            identifier,
            after["scenario"],
            delta,
            response_id,
            backend_id,
            audit_id,
            observed["active"],
        )

    async def audit(self, exchange, state, *, external=False):
        _require(
            (external and exchange.backend_request_id is None)
            or (not external and exchange.backend_request_id is not None),
            "Model/external audit requires the corresponding backend/public identity",
        )
        _require(
            exchange.audit_request_id == (exchange.response_request_id if external else exchange.backend_request_id),
            "Selected audit identity contradicts response headers",
        )

        async def read():
            page = checked_json(
                await self.http.admin.get(
                    f"{self.http.settings.api_base}/dsh/admin/model-audit/requests",
                    params={"tenant_id": 1, "conversation_id": exchange.conversation, "limit": 100},
                )
            )
            rows = page.get("items", [])
            _require(
                len(rows) <= 1 and page.get("next_cursor") is None, "One HTTP request produced duplicate audit records"
            )
            if not rows:
                return None
            return checked_json(
                await self.http.admin.get(
                    f"{self.http.settings.api_base}/dsh/admin/model-audit/requests/{rows[0]['request_id']}",
                    params={"tenant_id": 1},
                )
            )

        row = await wait_until(
            read,
            lambda value: (
                isinstance(value, dict)
                and value.get("content_safety_state") == state
                and value.get("details_status") == "AVAILABLE"
                and (
                    external
                    or (
                        value.get("usage_settlement") == "SETTLED"
                        and isinstance(value.get("usage"), dict)
                        and value["usage"].get("input_tokens") == 30
                        and value["usage"].get("output_tokens") == 50
                        and value["usage"].get("total_tokens") == 80
                    )
                )
            ),
            timeout=90,
        )
        _require(row["request_id"] == exchange.audit_request_id, "Response and audit request identifiers disagree")
        _require(
            row["user_id"] == int(self.profile["user"]["id"]) and row["model_id"] == self.model(exchange.protocol),
            "Audit belongs to another identity or model",
        )
        _require(row["record_origin"] == ("EXTERNAL_SAFETY" if external else "MODEL"), "Audit origin was fabricated")
        expected_stages = {
            "input": "BLOCKED" if external else "PASSED",
            "output": "NOT_APPLICABLE" if external else state,
        }
        _require(row["stage_results"] == expected_stages, "Safety stages changed")
        _require(
            all(type(value) is int and value > 0 for value in row["stage_versions"].values()),
            "Observed stage versions missing",
        )
        if external:
            _require(
                row["model_entered"] is False and row["audit_status"] == "NOT_APPLICABLE",
                "Input block fabricated model execution",
            )
            _require(
                all(
                    row[key] is None
                    for key in ("model_started_at", "model_result", "response_result", "usage_settlement", "usage")
                ),
                "Input block fabricated usage or terminal axes",
            )
        else:
            _require(
                row["model_entered"] is True and row["model_result"] == "SUCCEEDED", "Actual model execution was lost"
            )
            _require(
                row["usage"]["total_tokens"] == 80
                and row["usage"]["input_tokens"] == 30
                and row["usage"]["output_tokens"] == 50,
                "Reliable provider usage was lost or replaced",
            )
        details = checked_json(
            await self.http.admin.get(
                f"{self.http.settings.api_base}/dsh/admin/model-audit/requests/{exchange.audit_request_id}/content-safety-events",
                params={"tenant_id": 1, "limit": 100},
            )
        )
        _require(details["details_status"] == "AVAILABLE" and bool(details["items"]), "Safety event evidence missing")
        _require(
            all(item["forwarded"] is (not external) for item in details["items"]), "Event forwarding facts disagree"
        )
        _require(
            all(
                not {"tenant_id", "payload", "payload_hash", "custom_words"} & item.keys() for item in details["items"]
            ),
            "Safety query leaked private event fields",
        )
        self.record(
            "f111_audit",
            json.dumps(
                {
                    "request_id": row["request_id"],
                    "response_request_id": exchange.response_request_id,
                    "backend_request_id": exchange.backend_request_id,
                    "origin": row["record_origin"],
                    "state": row["content_safety_state"],
                    "stages": row["stage_results"],
                    "usage": row["usage"],
                    "events": [item["event_id"] for item in details["items"]],
                },
                sort_keys=True,
            ),
        )
        return row

    async def confirm_provider(self, exchange, expected):
        _require(
            exchange.global_delta == expected and exchange.counts["requests"] == expected,
            "Physical and attributed upstream request counts disagree",
        )
        if expected:
            _require(
                exchange.counts["completed"] == 1 and exchange.counts["usage_emitted"] == 1,
                "Synthetic model did not finish with reliable usage",
            )

    async def confirm_charge(self, before, protocol, *, called=True):
        expected = before + ((80 * self.rates[protocol] + 99) // 100 if called else 0)
        _require(
            await wait_until(self.used, lambda value: value == expected, timeout=40) == expected,
            "Personal allowance charge changed",
        )


@pytest_asyncio.fixture
async def live_protocol(record_property, request):
    if os.environ.get("DSH_E2E_EXCLUSIVE_PROVIDER") != "1" or os.environ.get("PYTEST_XDIST_WORKER"):
        raise pytest.UsageError("Live protocol tests require an exclusive Provider and serial pytest execution")
    user_file = os.environ.get("DSH_E2E_USER_SESSION_FILE")
    user_id = os.environ.get("DSH_E2E_USER_ID", "")
    if not user_file or not user_id.isascii() or not user_id.isdecimal() or not 0 < int(user_id) <= 2**63 - 1:
        raise pytest.UsageError(
            "Live protocol tests require an explicit ordinary-user session and positive user identifier"
        )
    settings = LiveSafetySettings.from_env()
    user_settings = LiveSafetySettings.from_env(dict(os.environ) | {"DSH_E2E_SESSION_FILE": user_file})
    _require(
        user_settings.platform_token != settings.platform_token, "Model user and management sessions must be separate"
    )
    async with LiveSafetyHTTP(settings) as http:
        capability_response = await http.admin.get(
            settings.api_base.removesuffix("/api/v1") + "/api/sensitive/dsh/capabilities", params={"tenant_id": 1}
        )
        envelope = _body(capability_response)
        if envelope.get("status_code", envelope.get("statusCode")) == 11001:
            raise pytest.UsageError("Deployment license is unavailable (11001); live model tests have not started")
        capabilities = checked_json(capability_response)
        _require(
            capabilities.get("available") is True and capabilities.get("enabled") is True,
            "Gateway safety checks are not available/enabled",
        )
        mode = checked_json(
            await http.admin.get(settings.api_base + "/dsh/admin/model-audit/settings", params={"tenant_id": 1})
        )
        _require(mode.get("mode") in {"METADATA", "CONTENT"}, "Native audit metadata must be enabled before this test")
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as identity_client:
            user_info = checked_json(
                await identity_client.get(
                    settings.api_base + "/user/info", headers=auth_headers(user_settings.platform_token)
                )
            )
        _require(
            user_info.get("is_global_super") is False and user_info.get("leaf_tenant_id") == 1,
            "Selected model actor must be a non-global user in tenant one",
        )
        _require(
            user_info.get("user_id") == int(user_id), "Platform user identity does not match the selected test actor"
        )
        tokens = await http.desktop_session(user_settings.platform_token)
        run = None
        try:
            profile = checked_json(
                await http.native.get(
                    settings.api_base + "/dsh/profile", headers={"Authorization": "Bearer " + tokens["access_token"]}
                ),
                unified=False,
            )
            _require(
                profile["tenant"]["id"] == "1" and profile["user"]["id"] == user_id,
                "This live suite requires the selected single-tenant deployment",
            )
            run = ProtocolRun(http, tokens, profile, record_property)
            if getattr(request, "param", None) == "unicode":
                run.word = "界🚀敏" + uuid.uuid4().hex[:8]
            catalog = checked_json(
                await http.native.get(settings.api_base + "/dsh/models", headers=run.headers), unified=False
            )
            for protocol in ("chat", "responses"):
                model = next((row for row in catalog["data"] if row["id"] == f"bisheng:{run.model(protocol)}"), None)
                _require(
                    model is not None and model.get("display_name", "").startswith(settings.prefix),
                    "Selected model was not verified as test-owned",
                )
                _require(
                    model["capabilities"].get("streaming") is True and model["capabilities"].get("tools") is True,
                    "Test model lacks required streaming/tool capabilities",
                )
                if protocol == "responses":
                    _require(
                        model["capabilities"].get("responses") is True, "Test model is not native Responses capable"
                    )
                http.owned.register("model", run.model(protocol), model["display_name"])
                visibility = checked_json(
                    await http.admin.get(f"{settings.api_base}/dsh/admin/models/{run.model(protocol)}/visibility")
                )
                _require(visibility["everyone"] is False, "Test model must have explicit private visibility")
                run.rates[protocol] = int(Decimal(visibility["credit_multiplier"]) * 100)
            async with SafetyPolicyLease(http) as lease:
                await lease.save(
                    enabled=True,
                    input_enabled=True,
                    output_enabled=True,
                    words_types=["2"],
                    custom_words=run.word,
                    auto_reply=NOTICE,
                )
                # The contract allows five seconds for other policy-cache readers to expire.
                await asyncio.sleep(5.25)
                yield run
        finally:
            try:
                if run is not None:
                    for identifier in run.scenarios:
                        counts = await wait_until(
                            lambda identifier=identifier: http.provider_counts(identifier),
                            lambda value: value["active"] == 0,
                            timeout=40,
                        )
                        record_property("f111_provider_final", json.dumps(counts, sort_keys=True))
                        http.owned.require("scenario", identifier, identifier)
                        checked_json(
                            await http.control.delete(
                                f"{settings.provider_control_url}/__control/scenarios/{identifier}"
                            ),
                            unified=False,
                        )
                        removed = await http.control.get(
                            f"{settings.provider_control_url}/__control/scenarios/{identifier}"
                        )
                        _require(
                            removed.status_code == 400
                            and _body(removed).get("error", {}).get("code") == "test_invalid",
                            "Provider scenario cleanup did not persist",
                        )
            finally:
                await logout_desktop_session(http.native, tokens["access_token"], api_base=settings.api_base)


@pytest.mark.parametrize("protocol,stream", MODES)
async def test_safe_request_preserves_protocol_order_and_actual_usage(live_protocol, protocol, stream):
    """Coverage AC: AC-01, AC-02, AC-20, AC-22, AC-23, AC-28, AC-32."""
    run = live_protocol
    before = await run.used()
    exchange = await run.exchange(protocol, stream)
    _passed(exchange.response, protocol, stream)
    await run.confirm_provider(exchange, 1)
    await run.audit(exchange, "PASSED")
    await run.confirm_charge(before, protocol)


@pytest.mark.parametrize("protocol,stream", MODES)
async def test_input_block_has_no_upstream_execution_or_charge(live_protocol, protocol, stream):
    """Coverage AC: AC-01, AC-20, AC-27, AC-30, AC-32. A positive control proves marker preservation."""
    run = live_protocol
    before = await run.used()
    positive = await run.exchange(protocol, stream)
    _passed(positive.response, protocol, stream)
    await run.confirm_provider(positive, 1)
    await run.audit(positive, "PASSED")
    await run.confirm_charge(before, protocol)
    before = await run.used()
    blocked = await run.exchange(protocol, stream, matched=True)
    _blocked(blocked.response, protocol, stream, run.word, input_block=True)
    await run.confirm_provider(blocked, 0)
    await run.audit(blocked, "BLOCKED", external=True)
    await run.confirm_charge(before, protocol, called=False)


@pytest.mark.parametrize("protocol,stream", MODES)
async def test_output_block_keeps_real_execution_and_provider_usage(live_protocol, protocol, stream):
    """Coverage AC: AC-01, AC-22, AC-28, AC-29, AC-30, AC-32, AC-57."""
    run = live_protocol
    before = await run.used()
    exchange = await run.exchange(
        protocol,
        stream,
        configure={
            "text": "Safe prefix " + run.word + " hidden tail" * 12,
            "fragment_bytes": 1,
            "delay_ms": 100 if stream else 0,
        },
    )
    _blocked(exchange.response, protocol, stream, run.word)
    if stream:
        _require(exchange.active_at_client_end == 1, "Fixture did not prove an active upstream after client blocking")
    await run.confirm_provider(exchange, 1)
    await run.audit(exchange, "BLOCKED")
    await run.confirm_charge(before, protocol)


@pytest.mark.parametrize("channel", ["text", "summary", "content"])
@pytest.mark.parametrize("observation", ["final_only", "changed_final", "original_delta"])
async def test_responses_each_text_observation_is_checked(live_protocol, channel, observation):
    """Coverage AC: AC-20, AC-21, AC-22, AC-23, AC-28, AC-29, AC-32."""
    run = live_protocol
    configure = {
        "kind": "text" if channel == "text" else "reasoning",
        "reasoning_channel": "summary" if channel == "text" else channel,
    }
    if observation == "final_only":
        configure |= {"emit_deltas": False, "final_parts": [run.word]}
    elif observation == "changed_final":
        configure |= {"parts": ["Safe delta"], "done_parts": ["Safe done"], "final_parts": [run.word]}
    else:
        configure |= {"parts": [run.word], "done_parts": ["Safe done"], "final_parts": ["Safe final"]}
    before = await run.used()
    exchange = await run.exchange("responses", True, configure=configure)
    _blocked(exchange.response, "responses", True, run.word)
    await run.confirm_provider(exchange, 1)
    await run.audit(exchange, "BLOCKED")
    await run.confirm_charge(before, "responses")


@pytest.mark.parametrize("channel", ["text", "summary", "content"])
@pytest.mark.parametrize("stream", [False, True])
async def test_adjacent_response_parts_preserve_one_logical_text(live_protocol, channel, stream):
    """Coverage AC: AC-20, AC-21, AC-22, AC-23, AC-28, AC-29, AC-32."""
    run = live_protocol
    middle = len(run.word) // 2
    configure = {
        "kind": "text" if channel == "text" else "reasoning",
        "reasoning_channel": "summary" if channel == "text" else channel,
        "parts": [run.word[:middle], "", run.word[middle:]],
        "fragment_bytes": 1,
    }
    before = await run.used()
    exchange = await run.exchange("responses", stream, configure=configure)
    _blocked(exchange.response, "responses", stream, run.word)
    await run.confirm_provider(exchange, 1)
    await run.audit(exchange, "BLOCKED")
    await run.confirm_charge(before, "responses")


def _tool_request(protocol, payload):
    function = {
        "name": "lookup",
        "description": "A safe synthetic test function",
        "parameters": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
    }
    payload["tools"] = [{"type": "function", **({"function": function} if protocol == "chat" else function)}]
    payload["tool_choice"] = "required"


def _tool_arguments(response, protocol, stream):
    if not stream:
        body = _body(response)
        return (
            body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
            if protocol == "chat"
            else body["output"][0]["arguments"]
        )
    events = _events(response)
    if protocol == "chat":
        _require(events[-1] == "[DONE]", "Safe tool stream did not finish")
        return "".join(
            (call.get("function", {}).get("arguments") or "")
            for event in events
            if isinstance(event, dict)
            for choice in event.get("choices", [])
            for call in (choice.get("delta", {}).get("tool_calls") or [])
        )
    _require(events[-1]["type"] == "response.completed", "Safe tool stream did not finish")
    return "".join(
        event["delta"]
        for event in events
        if isinstance(event, dict) and event.get("type") == "response.function_call_arguments.delta"
    )


@pytest.mark.parametrize("protocol,stream", MODES)
async def test_tool_arguments_only_cross_the_barrier_after_checking(live_protocol, protocol, stream):
    """Coverage AC: AC-20, AC-22, AC-24, AC-28, AC-29, AC-30, AC-32."""
    run = live_protocol
    before = await run.used()
    positive = await run.exchange(
        protocol,
        stream,
        configure={"kind": "tool", "arguments": '{"value":"safe"}'},
        mutate=lambda body: _tool_request(protocol, body),
    )
    _require(
        positive.response.status_code == 200
        and json.loads(_tool_arguments(positive.response, protocol, stream)) == {"value": "safe"},
        "Safe complete object tool arguments changed",
    )
    await run.confirm_provider(positive, 1)
    await run.audit(positive, "PASSED")
    await run.confirm_charge(before, protocol)
    before = await run.used()
    blocked = await run.exchange(
        protocol,
        stream,
        configure={"kind": "tool", "arguments": json.dumps({"value": run.word}), "fragment_bytes": 1},
        mutate=lambda body: _tool_request(protocol, body),
    )
    _blocked(blocked.response, protocol, stream, run.word)
    if stream:
        events = _events(blocked.response)
        if protocol == "chat":
            _require(
                not any(
                    choice.get("delta", {}).get("tool_calls")
                    for event in events
                    if isinstance(event, dict)
                    for choice in event.get("choices", [])
                ),
                "Unchecked Chat tool arguments escaped",
            )
        else:
            _require(
                not any(
                    event.get("type", "").startswith("response.function_call_arguments")
                    for event in events
                    if isinstance(event, dict)
                ),
                "Unchecked Responses tool arguments escaped",
            )
    await run.confirm_provider(blocked, 1)
    await run.audit(blocked, "BLOCKED")
    await run.confirm_charge(before, protocol)


@pytest.mark.parametrize("protocol", ["chat", "responses"])
async def test_history_and_internal_requests_are_checked_without_merging_messages(live_protocol, protocol):
    """Coverage AC: AC-20, AC-21, AC-27, AC-30. Internal use cannot bypass full history."""
    run = live_protocol
    middle = len(run.word) // 2

    def separate(payload):
        key = "messages" if protocol == "chat" else "input"
        payload[key] = [
            {"role": "user", "content": run.word[:middle]},
            {"role": "user", "content": run.word[middle:]},
            *payload[key],
        ]
        payload["audit_context"]["request_kind"] = "compaction"

    before = await run.used()
    positive = await run.exchange(protocol, False, mutate=separate)
    _passed(positive.response, protocol, False)
    await run.confirm_provider(positive, 1)
    await run.audit(positive, "PASSED")
    await run.confirm_charge(before, protocol)

    def history(payload):
        key = "messages" if protocol == "chat" else "input"
        payload[key] = [{"role": "system", "content": run.word}, *payload[key]]
        payload["audit_context"]["request_kind"] = "session-title"

    before = await run.used()
    blocked = await run.exchange(protocol, False, mutate=history)
    _blocked(blocked.response, protocol, False, run.word, input_block=True)
    await run.confirm_provider(blocked, 0)
    await run.audit(blocked, "BLOCKED", external=True)
    await run.confirm_charge(before, protocol, called=False)


@pytest.mark.parametrize("live_protocol", ["unicode"], indirect=True)
@pytest.mark.parametrize("protocol", ["chat", "responses"])
async def test_supplementary_plane_word_cannot_escape_transport_fragments(live_protocol, protocol):
    """Coverage AC: AC-20, AC-22, AC-29, AC-30, AC-32."""
    run = live_protocol
    before = await run.used()
    exchange = await run.exchange(
        protocol, True, configure={"text": "Safe prefix " + run.word + " hidden tail", "fragment_bytes": 1}
    )
    _blocked(exchange.response, protocol, True, run.word)
    await run.confirm_provider(exchange, 1)
    await run.audit(exchange, "BLOCKED")
    await run.confirm_charge(before, protocol)
