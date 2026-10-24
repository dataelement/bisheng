"""Read existing test-owned HTTP audit facts; do not claim fault/SQL recovery.

Set DSH_SAFETY_E2E=1 and DSH_E2E_RECOVERY_EVIDENCE_FILE to an owned 0600,
<=16KiB JSON manifest. Required top-level keys: schema_version=1, run_id,
tenant_id=1, user_id, server_id and requests. Each request has protocol
(CHAT/RESPONSES), stream (boolean), request_id (canonical UUID), conversation_id
(run prefix), model_id, model_name (actual audit name), scenario
(NORMAL/INPUT_BLOCKED/OUTPUT_BLOCKED), safety_state (DISABLED/PASSED/BLOCKED).
The four NORMAL protocol/mode records are mandatory. Block records are optional
real prior evidence, never fabricated placeholders. No live model request, PKCE,
SQL, signature, original body access or setting mutation is performed here.
"""

import asyncio
import json
import os
import re
import uuid
from datetime import UTC, datetime
from hashlib import sha256

import httpx
import pytest
import pytest_asyncio

from test.e2e.helpers.auth import auth_headers
from test.e2e.helpers.dsh_content_safety import (
    LiveSafetyError,
    LiveSafetyHTTP,
    LiveSafetySettings,
    _private_file,
    checked_json,
    wait_until,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("DSH_SAFETY_E2E") != "1", reason="Explicit live DSH safety environment required"),
]
MODES = [("CHAT", False), ("CHAT", True), ("RESPONSES", False), ("RESPONSES", True)]
TOP_KEYS = {"schema_version", "run_id", "tenant_id", "user_id", "server_id", "requests"}
REQUEST_KEYS = {
    "protocol",
    "stream",
    "request_id",
    "conversation_id",
    "model_id",
    "model_name",
    "scenario",
    "safety_state",
}
EVENT_KEYS = {
    "schema_version",
    "source_id",
    "event_id",
    "gateway_request_id",
    "backend_request_id",
    "session_id",
    "protocol",
    "event_kind",
    "event_version",
    "request_started_at",
    "occurred_at",
    "received_at",
    "stage_results",
    "stage_versions",
    "policy_version",
    "builtin_digest",
    "hit_count",
    "hit_count_truncated",
    "rule_refs",
    "forwarded",
    "drain_status",
    "conversation",
    "association_status",
    "audit_request_id",
    "user_id",
    "model_id",
}
ROW_STABLE = (
    "request_id",
    "user_id",
    "model_id",
    "model_name",
    "provider_name",
    "conversation_id",
    "started_at",
    "record_origin",
    "model_entered",
    "model_started_at",
    "source_id",
    "gateway_request_id",
    "content_safety_state",
    "stage_results",
    "stage_versions",
    "has_sensitive_hit",
    "input_sensitive_hit",
    "output_sensitive_hit",
    "model_result",
    "response_result",
    "audit_status",
    "usage_settlement",
    "effective_mode",
)


def require(condition, message):
    if not condition:
        raise LiveSafetyError(message)


def positive(value):
    return type(value) is int and 0 < value <= 2**63 - 1


def canonical_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Recovery evidence contains duplicate JSON keys")
        result[key] = value
    return result


def read_manifest(path, run_id):
    """Reuse the frozen file guard; retain only bounded, nonsecret selectors."""
    raw = _private_file(path)
    try:
        value = json.loads(raw, object_pairs_hook=unique_json)
    except (ValueError, UnicodeError):
        raise LiveSafetyError("Recovery evidence is not strict JSON") from None
    require(isinstance(value, dict) and set(value) == TOP_KEYS, "Recovery evidence schema is invalid")
    require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["run_id"] == run_id
        and value["tenant_id"] == 1
        and type(value["tenant_id"]) is int
        and positive(value["user_id"])
        and positive(value["server_id"]),
        "Recovery evidence identity or deployment does not match this run",
    )
    rows = value["requests"]
    require(isinstance(rows, list) and 4 <= len(rows) <= 12, "Recovery evidence requires four to twelve real requests")
    ids, scenarios, models = set(), set(), {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == REQUEST_KEYS, "Recovery request schema is invalid")
        require(
            row["protocol"] in {"CHAT", "RESPONSES"}
            and type(row["stream"]) is bool
            and canonical_uuid(row["request_id"])
            and positive(row["model_id"])
            and isinstance(row["conversation_id"], str)
            and len(row["conversation_id"]) <= 256
            and row["conversation_id"].startswith(f"e2e-f111-live-{run_id}-")
            and isinstance(row["model_name"], str)
            and len(row["model_name"]) <= 2048,
            "Recovery request is outside this test run",
        )
        require(row["scenario"] in {"NORMAL", "INPUT_BLOCKED", "OUTPUT_BLOCKED"}, "Unknown recovery scenario")
        require(
            (row["scenario"] == "NORMAL" and row["safety_state"] in {"DISABLED", "PASSED"} and bool(row["model_name"]))
            or (row["scenario"] != "NORMAL" and row["safety_state"] == "BLOCKED"),
            "Recovery scenario has an invalid expected state",
        )
        key = (row["protocol"], row["stream"], row["scenario"])
        require(row["request_id"] not in ids and key not in scenarios, "Recovery requests are duplicate or ambiguous")
        require(
            models.setdefault(row["protocol"], row["model_id"]) == row["model_id"], "Recovery model mapping changed"
        )
        ids.add(row["request_id"])
        scenarios.add(key)
    require(
        all((protocol, stream, "NORMAL") in scenarios for protocol, stream in MODES), "Four normal modes are required"
    )
    require(len(set(models.values())) == 2, "Chat and Responses must use their distinct owned models")
    return value, sha256(raw).hexdigest()


def aware(value):
    try:
        require(
            isinstance(value, str)
            and re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|\+00:00)", value
            ),
            "Audit timestamp is not RFC3339 UTC",
        )
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0, "Audit timestamp is not UTC")
        return stamp
    except (ValueError, TypeError, AttributeError):
        raise LiveSafetyError("Audit timestamp is invalid") from None


def stages(value, versions, *, event_version=None):
    require(isinstance(value, dict) and set(value) == {"input", "output"}, "Safety stage shape changed")
    require(isinstance(versions, dict) and set(versions) == {"input", "output"}, "Safety version shape changed")
    for direction in ("input", "output"):
        version = versions[direction]
        require(
            value[direction] in {"UNREPORTED", "PASSED", "BLOCKED", "ERROR", "DISABLED", "NOT_APPLICABLE"}
            and type(version) is int
            and 0 <= version <= 2**63 - 1
            and ((value[direction] == "UNREPORTED") == (version == 0))
            and (event_version is None or version <= event_version),
            "Safety stage version is inconsistent",
        )


def validate_event_shape(event):
    """Check the public metadata contract without cleaning or dropping returned fields."""
    require(isinstance(event, dict) and set(event) == EVENT_KEYS, "Safety event whitelist changed")
    require(type(event["schema_version"]) is int and event["schema_version"] == 1, "Invalid event schema version")
    require(
        isinstance(event["source_id"], str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", event["source_id"]),
        "Invalid event source identifier",
    )
    for key in ("event_id", "gateway_request_id", "backend_request_id", "session_id", "audit_request_id"):
        require(
            (event[key] is None and key not in {"event_id", "gateway_request_id"}) or canonical_uuid(event[key]),
            "Invalid event UUID",
        )
    for key in ("user_id", "model_id"):
        value = event[key]
        require(
            isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) and positive(int(value)),
            "Invalid event actor/model identifier",
        )
    for key in ("policy_version", "hit_count"):
        require(type(event[key]) is int and 0 <= event[key] <= 2**63 - 1, "Invalid bounded event counter")
    require(
        positive(event["event_version"])
        and event["protocol"] in {"CHAT", "RESPONSES"}
        and event["event_kind"] in {"DECISION", "FINAL", "DRAIN"}
        and event["association_status"] in {"ASSOCIATED", "UNASSOCIATED"},
        "Invalid event discriminator",
    )
    require(type(event["forwarded"]) is bool and type(event["hit_count_truncated"]) is bool, "Invalid event boolean")
    require(
        isinstance(event["builtin_digest"], str) and re.fullmatch(r"[0-9a-f]{64}", event["builtin_digest"]),
        "Invalid builtin digest",
    )
    require(
        event["drain_status"] in {"NOT_REQUIRED", "RUNNING", "FINISHED", "TIMED_OUT", "LIMITED", "DISCONNECTED"},
        "Invalid drain state",
    )
    refs = event["rule_refs"]
    require(
        isinstance(refs, list)
        and len(refs) <= 20
        and all(isinstance(ref, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", ref) for ref in refs),
        "Event exposed unbounded or raw rule references",
    )
    hints = event["conversation"]
    if hints is None:
        return
    require(
        isinstance(hints, dict)
        and not set(hints) - {"conversation_id", "request_kind", "session_origin", "parent_conversation_id"},
        "Safety event exposed unexpected nested conversation fields",
    )
    try:
        require(
            len(json.dumps(hints, ensure_ascii=False, separators=(",", ":")).encode("utf8")) <= 4096,
            "Safety conversation exceeds its bound",
        )
    except (TypeError, ValueError, UnicodeError):
        raise LiveSafetyError("Invalid safety conversation encoding") from None
    for key in ("conversation_id", "parent_conversation_id"):
        value = hints.get(key)
        require(value is None or (isinstance(value, str) and 1 <= len(value) <= 256), "Invalid conversation identifier")
    require(
        hints.get("request_kind") in {None, "chat", "compaction", "session-title"}
        and hints.get("session_origin") in {None, "main", "subagent"},
        "Invalid conversation discriminator",
    )
    parent = hints.get("parent_conversation_id")
    require(
        parent is None
        or (
            bool(hints.get("conversation_id"))
            and hints.get("session_origin") == "subagent"
            and parent != hints["conversation_id"]
        ),
        "Invalid parent conversation hint",
    )


def validate_snapshot(row, events, expected, manifest):
    require(
        row["request_id"] == expected["request_id"]
        and row["user_id"] == manifest["user_id"]
        and row["model_id"] == expected["model_id"]
        and row["model_name"] == expected["model_name"]
        and row["conversation_id"] == expected["conversation_id"]
        and row["association_status"] == "ASSOCIATED",
        "Audit identity or owned request association changed",
    )
    require(row["content_safety_state"] == expected["safety_state"], "Audit safety state differs from real evidence")
    require(row["details_status"] == "AVAILABLE" and events, "Persisted safety details are unavailable")
    require(not {"tenant_id", "payload", "payload_hash", "custom_words"} & row.keys(), "Audit exposed private facts")
    aware(row["started_at"])
    stages(row["stage_results"], row["stage_versions"])
    external = expected["scenario"] == "INPUT_BLOCKED"
    expected_stages = (
        {"input": "BLOCKED", "output": "NOT_APPLICABLE"}
        if external
        else {"input": "PASSED", "output": row["stage_results"]["output"]}
        if expected["scenario"] == "OUTPUT_BLOCKED"
        else {"input": expected["safety_state"], "output": expected["safety_state"]}
    )
    require(row["stage_results"] == expected_stages, "Audit phase results changed")
    require(row["has_sensitive_hit"] is (expected["scenario"] != "NORMAL"), "Audit hit summary changed")
    require(
        row["input_sensitive_hit"] is external
        and row["output_sensitive_hit"] is (expected["scenario"] == "OUTPUT_BLOCKED"),
        "Audit directional hit summary changed",
    )
    if external:
        require(
            row["record_origin"] == "EXTERNAL_SAFETY"
            and row["model_entered"] is False
            and row["audit_status"] == "NOT_APPLICABLE"
            and all(
                row[key] is None
                for key in (
                    "effective_mode",
                    "model_started_at",
                    "model_result",
                    "response_result",
                    "usage_settlement",
                    "usage",
                )
            ),
            "External safety audit fabricated model execution or usage",
        )
    else:
        require(
            row["record_origin"] == "MODEL"
            and row["model_entered"] is True
            and row["model_result"] == "SUCCEEDED"
            and row["usage_settlement"] == "SETTLED"
            and isinstance(row["usage"], dict)
            and all(
                row["usage"].get(key) == value
                for key, value in (("input_tokens", 30), ("output_tokens", 50), ("total_tokens", 80))
            ),
            "Actual model execution or reliable usage was lost",
        )
        aware(row["model_started_at"])
    if expected["scenario"] == "NORMAL":
        require(
            row["response_result"] == "COMPLETED" and row["audit_status"] == "NORMAL",
            "Normal request did not preserve completed delivery and healthy audit",
        )
    ids, versions = set(), set()
    for event in events:
        validate_event_shape(event)
        require(
            canonical_uuid(event["event_id"]) and event["event_id"] not in ids and positive(event["event_version"]),
            "Safety events are duplicate or invalid",
        )
        key = (event["source_id"], event["gateway_request_id"], event["event_version"])
        require(key not in versions, "Request version has multiple exposed facts")
        ids.add(event["event_id"])
        versions.add(key)
        require(
            event["schema_version"] == 1
            and event["protocol"] == expected["protocol"]
            and event["source_id"] == row["source_id"]
            and event["gateway_request_id"] == row["gateway_request_id"]
            and event["backend_request_id"] == (None if external else row["request_id"])
            and event["audit_request_id"] == row["request_id"]
            and event["association_status"] == "ASSOCIATED"
            and event["user_id"] == str(manifest["user_id"])
            and event["model_id"] == str(expected["model_id"])
            and event["forwarded"] is (not external),
            "Safety event identity or forwarding changed",
        )
        stages(event["stage_results"], event["stage_versions"], event_version=event["event_version"])
        start, observed, _received = (aware(event[key]) for key in ("request_started_at", "occurred_at", "received_at"))
        # Gateway observations share a clock; backend receipt may have permitted skew.
        require((observed - start).total_seconds() >= -5, "Safety observation times changed")
        for direction in ("input", "output"):
            require(
                row["stage_versions"][direction] >= event["stage_versions"][direction], "Audit phase version regressed"
            )
            if event["stage_results"][direction] == "BLOCKED":
                require(row[f"{direction}_sensitive_hit"] is True, "Audit lost a persisted hit")
    for direction in ("input", "output"):
        latest = max(event["stage_versions"][direction] for event in events)
        require(row["stage_versions"][direction] == latest, "Audit phase version has no exposed event")
        require(
            all(
                event["stage_results"][direction] == row["stage_results"][direction]
                for event in events
                if event["stage_versions"][direction] == latest
            ),
            "Latest persisted phase disagrees with the audit summary",
        )
    return {
        "row": {key: row[key] for key in ROW_STABLE},
        "usage": {key: row["usage"][key] for key in ("input_tokens", "output_tokens", "total_tokens")}
        if row["usage"]
        else None,
        "events": {event["event_id"]: event for event in events},
    }


class Readback:
    def __init__(self, http, manifest):
        self.http, self.manifest = http, manifest
        self.base = http.settings.api_base + "/dsh/admin/model-audit"

    async def get(self, path, **params):
        response = await self.http.admin.get(self.base + path, params={"tenant_id": 1, **params})
        require(response.headers.get("cache-control") == "no-store", "Audit read is cacheable")
        return checked_json(response)

    async def read(self, expected):
        page = await self.get(
            "/requests", request_id=expected["request_id"], conversation_id=expected["conversation_id"], limit=100
        )
        require(
            len(page.get("items", [])) <= 1 and page.get("next_cursor") is None,
            "Request list is duplicate or unbounded",
        )
        if not page.get("items"):
            return None
        listed = page["items"][0]
        require(
            all(listed.get(key) == expected[key] for key in ("request_id", "model_id", "model_name", "conversation_id"))
            and listed.get("user_id") == self.manifest["user_id"],
            "Request list returned another identity or owned request",
        )
        row = await self.get("/requests/" + expected["request_id"])
        if any(listed.get(key) != row.get(key) for key in ROW_STABLE) or listed.get("usage") != row.get("usage"):
            return None
        if row.get("details_status") in {"PENDING", "UNREPORTED"}:
            return None
        events, cursors, cursor = [], set(), None
        for _ in range(4):
            page = await self.get(
                f"/requests/{expected['request_id']}/content-safety-events",
                limit=100,
                **({"cursor": cursor} if cursor else {}),
            )
            require(page.get("details_status") == "AVAILABLE", "Safety event details are unavailable")
            require(isinstance(page.get("items"), list) and len(page["items"]) <= 100, "Safety event page changed")
            events.extend(page["items"])
            cursor = page.get("next_cursor")
            if cursor is None:
                return row, events
            require(isinstance(cursor, str) and len(cursor) <= 2048 and cursor not in cursors, "Event cursor cycled")
            cursors.add(cursor)
        raise LiveSafetyError("Owned request exceeded the bounded event evidence limit")

    @staticmethod
    def complete(value, expected):
        if value is None:
            return False
        row, events = value
        if row.get("content_safety_state") != expected["safety_state"] or not events:
            return False
        if expected["scenario"] == "NORMAL" and (
            row.get("response_result") != "COMPLETED" or row.get("audit_status") != "NORMAL"
        ):
            return False
        if expected["scenario"] != "INPUT_BLOCKED":
            if row.get("usage_settlement") != "SETTLED" or not isinstance(row.get("usage"), dict):
                return False
            if any(
                row["usage"].get(key) != amount
                for key, amount in (("input_tokens", 30), ("output_tokens", 50), ("total_tokens", 80))
            ):
                return False
        terminal = (
            "FINAL"
            if expected["scenario"] == "NORMAL"
            else ("DRAIN" if expected["scenario"] == "OUTPUT_BLOCKED" and expected["stream"] else "DECISION")
        )
        return any(event.get("event_kind") == terminal for event in events)


@pytest_asyncio.fixture
async def recovery_readback(record_property):
    path = os.environ.get("DSH_E2E_RECOVERY_EVIDENCE_FILE")
    run_id = os.environ.get("DSH_E2E_RUN_ID")
    if not path or not run_id:
        raise pytest.UsageError("Recovery audit reads require an explicit evidence manifest and run identifier")
    manifest, digest = read_manifest(path, run_id)
    settings = LiveSafetySettings.from_env(require_models=False)
    user_file = os.environ.get("DSH_E2E_USER_SESSION_FILE")
    if not user_file:
        raise pytest.UsageError("Recovery audit reads require the selected ordinary-user session")
    user_settings = LiveSafetySettings.from_env(
        dict(os.environ) | {"DSH_E2E_SESSION_FILE": user_file}, require_models=False
    )
    require(user_settings.platform_token != settings.platform_token, "Recovery actor and admin must be separate")
    async with LiveSafetyHTTP(settings) as http:
        actor = checked_json(await http.admin.get(settings.api_base + "/user/info"))
        require(positive(actor.get("user_id")), "Management identity is unavailable")
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as browser:
            user = checked_json(
                await browser.get(settings.api_base + "/user/info", headers=auth_headers(user_settings.platform_token))
            )
        require(
            user.get("user_id") == manifest["user_id"]
            and user.get("leaf_tenant_id") == 1
            and user.get("is_global_super") is False,
            "Selected request actor does not match the deployment",
        )
        server = checked_json(
            await http.admin.get(settings.api_base + "/llm/info", params={"server_id": manifest["server_id"]})
        )
        require(
            server.get("id") == manifest["server_id"]
            and isinstance(server.get("name"), str)
            and server["name"].startswith(settings.prefix),
            "Provider is not owned by this test run",
        )
        models = server.get("models")
        require(isinstance(models, list), "Owned provider model metadata is unavailable")
        for protocol in ("CHAT", "RESPONSES"):
            model_id = next(row["model_id"] for row in manifest["requests"] if row["protocol"] == protocol)
            model = next((model for model in models if model.get("id") == model_id), None)
            require(
                model is not None
                and isinstance(model.get("name"), str)
                and model["name"].startswith(settings.prefix)
                and isinstance(model.get("model_name"), str)
                and bool(model["model_name"].strip()),
                "Model is not owned by this provider/run",
            )
            expected_name = server["name"].strip() + " / " + model["model_name"].strip()
            require(
                all(
                    row["scenario"] == "INPUT_BLOCKED" or row["model_name"] == expected_name
                    for row in manifest["requests"]
                    if row["protocol"] == protocol
                ),
                "Audit model name is not the owned model",
            )
            configured_id = settings.chat_model_id if protocol == "CHAT" else settings.responses_model_id
            require(configured_id is None or configured_id == model_id, "Manifest selected another configured model")
            visibility = checked_json(
                await http.admin.get(
                    f"{settings.api_base}/dsh/admin/models/{model_id}/visibility", params={"tenant_id": 1}
                )
            )
            require(visibility.get("everyone") is False, "Owned model must remain private")
        scenarios = {row["scenario"] for row in manifest["requests"]}
        record_property(
            "f111_recovery_boundaries",
            json.dumps(
                {
                    "manifest_sha256": digest,
                    "read_only_http": True,
                    "sql_verified": False,
                    "outbox_verified": False,
                    "replay_verified": False,
                    "missing_prior_scenarios": sorted({"INPUT_BLOCKED", "OUTPUT_BLOCKED"} - scenarios),
                    "not_run": [
                        "OFF",
                        "METADATA",
                        "lost_ack",
                        "restart",
                        "reorder",
                        "conflict",
                        "retention",
                        "watermark",
                    ],
                },
                sort_keys=True,
            ),
        )
        yield Readback(http, manifest)


@pytest.mark.parametrize("protocol,stream", MODES)
async def test_owned_persisted_audit_and_event_metadata_remain_consistent(
    recovery_readback, record_property, protocol, stream
):
    """Coverage AC: AC-33, AC-34, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-58.

    Assert readback only; retry/SQL/Outbox acceptance requires separate real faults.
    """
    reader = recovery_readback
    records = [row for row in reader.manifest["requests"] if row["protocol"] == protocol and row["stream"] is stream]
    for expected in records:
        first = await wait_until(
            lambda expected=expected: reader.read(expected),
            lambda value, expected=expected: reader.complete(value, expected),
            timeout=90,
        )
        snapshot = validate_snapshot(*first, expected, reader.manifest)
        await asyncio.sleep(0.5)
        second = await reader.read(expected)
        require(second is not None and reader.complete(second, expected), "Committed audit became unavailable")
        repeated = validate_snapshot(*second, expected, reader.manifest)
        require(
            snapshot["row"] == repeated["row"] and snapshot["usage"] == repeated["usage"],
            "Committed summary changed during repeat read",
        )
        require(
            all(repeated["events"].get(key) == value for key, value in snapshot["events"].items()),
            "Persisted immutable event changed or disappeared",
        )
        record_property(
            "f111_recovery_http",
            json.dumps(
                {
                    "request_id": expected["request_id"],
                    "scenario": expected["scenario"],
                    "protocol": protocol,
                    "stream": stream,
                    "state": expected["safety_state"],
                    "origin": first[0]["record_origin"],
                    "usage": snapshot["usage"],
                    "event_ids": sorted(repeated["events"]),
                    "repeat_reads": 2,
                    "checked_at": datetime.now(UTC).isoformat(),
                },
                sort_keys=True,
            ),
        )
