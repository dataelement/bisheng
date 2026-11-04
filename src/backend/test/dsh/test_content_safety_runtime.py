"""Coverage AC: AC-03, AC-26, AC-35, AC-42, AC-43.

Exercise the production signature/runtime boundary with original synthetic wire
bytes and real ingestion sessions. No authentication or ingestion implementation
is supplied by the tests; HTTP body streaming belongs to its later endpoint task.
"""

import importlib
import json
import subprocess
import sys
import textwrap
from dataclasses import FrozenInstanceError
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from starlette.datastructures import Headers

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import (
    DshContentSafetyAuthError,
    DshContentSafetyConflictError,
    DshContentSafetyInvalidEventError,
    DshContentSafetyTooLargeError,
    DshContentSafetyUnavailableError,
)
from bisheng.core.config.multi_tenant import MultiTenantConf
from bisheng.core.config.settings import SystemLoginMethod
from bisheng.core.config.sso_sync import SSOSyncConf
from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.dsh.domain.schemas.content_safety import MAX_EVENT_BYTES
from bisheng.dsh.domain.services.content_safety_ingest import ContentSafetyIngestService, VerifiedSource
from bisheng.sso_sync.domain.services.hmac_auth import compute_signature
from test.dsh.test_content_safety_ingest import SessionPort, rows
from test.dsh.test_content_safety_repository import wire_hash

SHARED_KEY = "f111-synthetic-shared-key"
PATH = "/api/v1/internal/dsh/content-safety-events"


def runtime_port():
    return importlib.import_module("bisheng.dsh.content_safety_runtime")


def configure(monkeypatch, runtime, *, key=SHARED_KEY, header="X-Signature", multi_tenant=True, login_settings=True):
    settings = SimpleNamespace(
        sso_sync=SSOSyncConf(gateway_hmac_secret=key, signature_header=header),
        multi_tenant=MultiTenantConf(enabled=multi_tenant),
    )
    if login_settings:
        settings.system_login_method = SystemLoginMethod(bisheng_pro=False)
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    return settings


def envelope(raw_event, clock, *, sent_at=None):
    timestamp = sent_at or clock.now().isoformat().replace("+00:00", "Z")
    return {"sent_at": timestamp, "event": raw_event}


def encode(value, **options):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False, **options).encode("utf8")


def headers(raw, *, key=SHARED_KEY, header="X-Signature", method="POST", path=PATH):
    return Headers({header: compute_signature(method, path, raw, key)})


def verify(runtime, raw, clock, *, request_headers=None, method="POST", path=PATH):
    return runtime.verify_source(
        raw, headers(raw) if request_headers is None else request_headers, method, path, now=clock.now()
    )


def assert_verified(verified, raw_event):
    assert isinstance(verified.verified_source, VerifiedSource)
    assert verified.verified_source.source_id == raw_event["source_id"]
    assert verified.verified_source.tenant_id == int(raw_event["tenant_id"])
    assert verified.raw_event == raw_event


@pytest.mark.parametrize("header", ["X-Signature", "X-Synthetic-Safety-Signature", ""])
def test_existing_sso_shared_key_and_configurable_header_authenticate_original_wire(
    monkeypatch, content_safety_event, content_safety_clock, header
):
    runtime = runtime_port()
    configure(monkeypatch, runtime, header=header)
    raw_event = content_safety_event()
    raw = encode(envelope(raw_event, content_safety_clock))
    verified = verify(runtime, raw, content_safety_clock, request_headers=headers(raw, header=header or "X-Signature"))
    assert_verified(verified, raw_event)
    with pytest.raises(FrozenInstanceError):
        verified.verified_source = VerifiedSource("other", 202)


@pytest.mark.parametrize("login_settings", [True, False])
def test_sso_login_disabled_or_unconfigured_does_not_disable_shared_key_receiver(
    monkeypatch, content_safety_event, content_safety_clock, login_settings
):
    runtime = runtime_port()
    configure(monkeypatch, runtime, login_settings=login_settings)
    raw_event = content_safety_event()
    assert_verified(verify(runtime, encode(envelope(raw_event, content_safety_clock)), content_safety_clock), raw_event)


@pytest.mark.parametrize("missing_setting", [False, True])
def test_unconfigured_key_only_makes_receiver_unavailable_without_constructing_business_runtime(
    monkeypatch, content_safety_engine, content_safety_event, content_safety_clock, missing_setting
):
    runtime = runtime_port()
    settings = configure(monkeypatch, runtime, key="")
    if missing_setting:
        del settings.sso_sync
    sessions = SessionPort(content_safety_engine)
    service = runtime.get_content_safety_service(session_factory=sessions)
    assert isinstance(service, ContentSafetyIngestService) and sessions.sessions == []
    raw = encode(envelope(content_safety_event(), content_safety_clock))
    with pytest.raises(DshContentSafetyUnavailableError):
        verify(runtime, raw, content_safety_clock)
    assert sessions.sessions == []
    # Shared signing remains a pure utility; no global SSO/model startup gate is changed.
    assert len(compute_signature("POST", PATH, raw, SHARED_KEY)) == 64


def test_assembly_is_lazy_and_never_imports_model_admission_or_storage_runtime():
    # A real cold import belongs in its own process: restoring sys.modules alone
    # leaves parent-package attributes and already-imported endpoint aliases split.
    before = sys.modules.get("bisheng.dsh.content_safety_runtime")
    code = textwrap.dedent(
        """
        import builtins
        import importlib
        import sys

        original_import = builtins.__import__
        forbidden = ("bisheng.dsh.runtime", "bisheng.dsh.audit_runtime", "bisheng.dsh.tool_runtime")
        assert "bisheng.dsh.content_safety_runtime" not in sys.modules

        def guarded_import(name, *args, **kwargs):
            assert not name.startswith(forbidden), "Safety receiver must compose independently of model runtime"
            return original_import(name, *args, **kwargs)

        builtins.__import__ = guarded_import
        runtime = importlib.import_module("bisheng.dsh.content_safety_runtime")
        sessions = []

        def session_factory():
            sessions.append(True)
            raise AssertionError("Lazy assembly must not open storage")

        service = runtime.get_content_safety_service(session_factory=session_factory)
        assert isinstance(service, runtime.ContentSafetyIngestService)
        assert sessions == []
        assert not any(name.startswith(forbidden) for name in sys.modules)
        print("COLD_SAFETY_ASSEMBLY_PASS")
        """
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "COLD_SAFETY_ASSEMBLY_PASS"
    assert sys.modules.get("bisheng.dsh.content_safety_runtime") is before


@pytest.mark.parametrize("provided", [None, "", "0" * 64, "Bearer synthetic-user-token", "not-hex", "f" * 65])
def test_bad_or_user_credentials_fail_before_json_or_business_access(
    monkeypatch, content_safety_engine, content_safety_clock, provided
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    statements = []

    def observed(_connection, _cursor, statement, _parameters, _execution_context, _many):
        statements.append(statement)

    event.listen(content_safety_engine, "before_cursor_execute", observed)
    try:
        with pytest.raises(DshContentSafetyAuthError):
            verify(
                runtime,
                b"\xffsynthetic-sensitive-body",
                content_safety_clock,
                request_headers=Headers({"X-Signature": provided} if provided is not None else {}),
            )
    finally:
        event.remove(content_safety_engine, "before_cursor_execute", observed)
    assert statements == []


def test_header_hex_case_and_whitespace_match_existing_sso_contract(
    monkeypatch, content_safety_event, content_safety_clock
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    raw_event = content_safety_event()
    raw = encode(envelope(raw_event, content_safety_clock))
    signature = compute_signature("POST", PATH, raw, SHARED_KEY)
    verified = verify(
        runtime, raw, content_safety_clock, request_headers=Headers({"x-signature": " \t" + signature.upper() + " "})
    )
    assert_verified(verified, raw_event)


@pytest.mark.parametrize("offset", [-300, 300])
def test_signed_send_time_window_includes_exact_300_second_boundaries(
    monkeypatch, content_safety_event, content_safety_clock, offset
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    sent = content_safety_clock.now() + timedelta(seconds=offset)
    timestamp = sent.isoformat().replace("+00:00", "Z")
    raw_event = content_safety_event(request_started_at=timestamp, occurred_at=timestamp)
    raw = encode(envelope(raw_event, content_safety_clock, sent_at=timestamp))
    assert_verified(verify(runtime, raw, content_safety_clock), raw_event)


@pytest.mark.parametrize("offset", [-300.001, 300.001])
def test_valid_hmac_outside_send_time_window_is_not_authenticated(
    monkeypatch, content_safety_event, content_safety_clock, offset
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    timestamp = (content_safety_clock.now() + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
    raw_event = content_safety_event(request_started_at=timestamp, occurred_at=timestamp)
    raw = encode(envelope(raw_event, content_safety_clock, sent_at=timestamp))
    with pytest.raises(DshContentSafetyAuthError):
        verify(runtime, raw, content_safety_clock)


@pytest.mark.parametrize("component", ["method", "path", "body", "key"])
def test_signature_binds_uppercase_method_fixed_path_and_exact_unparsed_bytes(
    monkeypatch, content_safety_event, content_safety_clock, component
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    raw = encode(envelope(content_safety_event(), content_safety_clock))
    signature = compute_signature(
        "GET" if component == "method" else "POST",
        PATH + "/other" if component == "path" else PATH,
        raw + b" " if component == "body" else raw,
        SHARED_KEY + "-wrong" if component == "key" else SHARED_KEY,
    )
    with pytest.raises(DshContentSafetyAuthError):
        verify(runtime, raw, content_safety_clock, request_headers=Headers({"X-Signature": signature}))


def test_lowercase_method_uses_shared_uppercase_signing_rule(monkeypatch, content_safety_event, content_safety_clock):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    raw_event = content_safety_event()
    assert_verified(
        verify(runtime, encode(envelope(raw_event, content_safety_clock)), content_safety_clock, method="post"),
        raw_event,
    )


@pytest.mark.parametrize("method,path", [("GET", PATH), ("POST", PATH + "/other"), ("POST", PATH + "?tenant_id=101")])
def test_even_valid_signature_cannot_retarget_the_fixed_method_or_path(
    monkeypatch, content_safety_event, content_safety_clock, method, path
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    raw = encode(envelope(content_safety_event(), content_safety_clock))
    with pytest.raises((DshContentSafetyAuthError, DshContentSafetyInvalidEventError)):
        verify(
            runtime,
            raw,
            content_safety_clock,
            method=method,
            path=path,
            request_headers=headers(raw, method=method, path=path),
        )


def test_signature_never_uses_a_reencoded_json_body(monkeypatch, content_safety_event, content_safety_clock):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    raw_event = content_safety_event(conversation={"conversation_id": "synthetic-Ω"})
    value = envelope(raw_event, content_safety_clock)
    raw = json.dumps(value, indent=2, ensure_ascii=True).encode()
    assert raw != encode(value)
    assert_verified(verify(runtime, raw, content_safety_clock), raw_event)
    with pytest.raises(DshContentSafetyAuthError):
        verify(runtime, raw, content_safety_clock, request_headers=headers(encode(value)))


@pytest.mark.parametrize(
    "case",
    [
        "bad-utf8",
        "duplicate-envelope-key",
        "duplicate-event-key",
        "trailing-value",
        "nan",
        "extra-envelope",
        "bad-date",
    ],
)
def test_signed_malformed_json_and_envelope_are_rejected_without_echoing_payload(
    monkeypatch, content_safety_event, content_safety_clock, case
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    value = envelope(content_safety_event(), content_safety_clock)
    raw = encode(value)
    if case == "bad-utf8":
        raw += b"\xff"
    elif case == "duplicate-envelope-key":
        raw = b'{"sent_at":' + encode(value["sent_at"]) + b"," + raw[1:]
    elif case == "duplicate-event-key":
        raw = raw.replace(b'"event_version":1', b'"event_version":1,"event_version":1')
    elif case == "trailing-value":
        raw += b"{}"
    elif case == "nan":
        raw = raw.replace(b'"conversation_id":"synthetic-conversation"', b'"conversation_id":NaN')
    elif case == "extra-envelope":
        raw = encode({**value, "synthetic-sensitive-field": "synthetic-private-marker"})
    else:
        raw = encode({**value, "sent_at": "synthetic-private-invalid-date"})
    with pytest.raises(DshContentSafetyInvalidEventError) as failure:
        verify(runtime, raw, content_safety_clock)
    public = str(failure.value) + repr(failure.value)
    assert "synthetic-private" not in public and SHARED_KEY not in public
    assert compute_signature("POST", PATH, raw, SHARED_KEY) not in public


def test_oversized_signed_body_is_rejected_before_parsing_or_sql(
    monkeypatch, content_safety_engine, content_safety_clock
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    sessions = SessionPort(content_safety_engine)
    runtime.get_content_safety_service(session_factory=sessions)
    raw = b" " * (MAX_EVENT_BYTES + 1)
    with pytest.raises(DshContentSafetyTooLargeError):
        verify(runtime, raw, content_safety_clock)
    assert sessions.sessions == []


def test_signed_envelope_depth_cannot_be_hidden_inside_cleaned_optional_hints(
    monkeypatch, content_safety_event, content_safety_clock
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    nested = "synthetic"
    for _ in range(17):
        nested = [nested]
    raw = encode(envelope(content_safety_event(conversation={"conversation_id": nested}), content_safety_clock))
    with pytest.raises(DshContentSafetyInvalidEventError):
        verify(runtime, raw, content_safety_clock)


@pytest.mark.parametrize("tenant_id", [101, 202])
def test_shared_key_allows_backend_multitenant_history_without_current_identity_lookup(
    monkeypatch, content_safety_event, content_safety_clock, tenant_id
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    raw_event = content_safety_event(
        tenant_id=str(tenant_id), user_id="22", source_id="synthetic-arbitrary-deployment-source"
    )
    assert_verified(verify(runtime, encode(envelope(raw_event, content_safety_clock)), content_safety_clock), raw_event)


def test_single_tenant_deployment_accepts_only_default_tenant_scope(
    monkeypatch, content_safety_event, content_safety_clock
):
    runtime = runtime_port()
    configure(monkeypatch, runtime, multi_tenant=False)
    raw_event = content_safety_event(tenant_id=str(DEFAULT_TENANT_ID))
    assert_verified(verify(runtime, encode(envelope(raw_event, content_safety_clock)), content_safety_clock), raw_event)
    foreign = content_safety_event(tenant_id="202")
    with pytest.raises(BaseErrorCode) as failure:
        verify(runtime, encode(envelope(foreign, content_safety_clock)), content_safety_clock)
    assert failure.value.HttpStatus == 403


async def test_two_stage_verification_preserves_original_event_mapping_for_real_ingestion(
    monkeypatch, content_safety_engine, content_safety_event, content_safety_clock
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    raw_event = content_safety_event(conversation={"conversation_id": "", "request_kind": "invalid"})
    raw_event.pop("session_id")
    sessions = SessionPort(content_safety_engine)
    service = runtime.get_content_safety_service(session_factory=sessions)
    verified = verify(runtime, encode(envelope(raw_event, content_safety_clock)), content_safety_clock)
    assert_verified(verified, raw_event)
    assert "session_id" not in verified.raw_event and verified.raw_event["conversation"]["request_kind"] == "invalid"
    assert sessions.sessions == []
    receipt = await service.ingest(verified.raw_event, verified.verified_source)
    assert receipt.receipt == "COMMITTED" and receipt.event_id == raw_event["event_id"]
    assert rows(content_safety_engine)[0][0].payload_hash == wire_hash(raw_event)
    changed = {**raw_event, "session_id": None}
    changed_verified = verify(runtime, encode(envelope(changed, content_safety_clock)), content_safety_clock)
    with pytest.raises(DshContentSafetyConflictError):
        await service.ingest(changed_verified.raw_event, changed_verified.verified_source)


@pytest.mark.parametrize("field", ["request_started_at", "occurred_at"])
def test_observed_event_times_cannot_exceed_signed_send_allowance(
    monkeypatch, content_safety_event, content_safety_clock, field
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    future = (content_safety_clock.now() + timedelta(seconds=301)).isoformat().replace("+00:00", "Z")
    raw = encode(envelope(content_safety_event(**{field: future}), content_safety_clock))
    with pytest.raises(DshContentSafetyInvalidEventError):
        verify(runtime, raw, content_safety_clock)


def test_signed_history_does_not_require_current_user_or_tenant_activity(
    monkeypatch, content_safety_event, content_safety_clock
):
    runtime = runtime_port()
    configure(monkeypatch, runtime)
    historical = (content_safety_clock.now() - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    raw_event = content_safety_event(request_started_at=historical, occurred_at=historical)
    raw = encode(envelope(raw_event, content_safety_clock))
    assert_verified(verify(runtime, raw, content_safety_clock), raw_event)
