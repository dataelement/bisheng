"""HTTP 层：信封顺序、码映射两级降级、零重试、超时分档（AC-04 / 14 / 16 / 17 / 18 / 19）。"""

from __future__ import annotations

import httpx
import pytest

from bisheng_sdk import _codes, _env, _http, errors
from tests.helpers.platform_mock import FAKE_OBO


def _resp(status: int, body) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://platform.test/x"))


def test_envelope_body_is_read_before_the_status_line():
    """/api/v1 的业务错误是 HTTP 200 + 信封；先看状态行就会把它当成功（坑 7）。"""
    with pytest.raises(errors.BishengSdkError):
        _http.parse_envelope(_resp(200, {"status_code": 10500, "status_message": "boom", "data": None}))

    with pytest.raises(errors.VisitorCredentialRejectedError):
        _http.parse_envelope(_resp(401, {"status_code": 26001, "status_message": "缺凭据", "data": {}}))


def test_success_envelope_returns_data():
    assert _http.parse_envelope(_resp(200, {"status_code": 200, "status_message": "SUCCESS", "data": {"a": 1}})) == {
        "a": 1
    }


@pytest.mark.parametrize("code", [26001, 26002, 26027, 26320])
def test_credential_and_identity_codes_map_to_rejected(code: int):
    error = _codes.map_error(code, "拒绝", http_status=401, data={})
    assert isinstance(error, errors.VisitorCredentialRejectedError)
    assert error.code == code


def test_scope_missing_keeps_required_as_a_single_string():
    error = _codes.map_error(26003, "缺位", http_status=403, data={"required": "knowledge:read"})
    assert isinstance(error, errors.ScopeMissingError)
    assert error.required == "knowledge:read"
    assert "knowledge:read" in str(error)


def test_unreachable_targets_carry_the_ids():
    error = _codes.map_error(26321, "不可及", http_status=404, data={"unreachable_ids": [3, 9]})
    assert isinstance(error, errors.TargetUnreachableError)
    assert error.ids == [3, 9]


def test_capability_codes_map_to_their_own_classes():
    revoked = _codes.map_error(16273, "已收回", http_status=400, data={"capability": "财务档案", "reason": "revoked"})
    assert isinstance(revoked, errors.CapabilityRevokedError)
    assert (revoked.capability, revoked.reason) == ("财务档案", "revoked")

    facade_revoked = _codes.map_error(26322, "已收回", http_status=409, data={"knowledge_id": 12})
    assert isinstance(facade_revoked, errors.CapabilityRevokedError)
    assert facade_revoked.capability == "12"

    undeclared = _codes.map_error(16274, "未声明", http_status=400, data={"capability": "knowledge"})
    assert isinstance(undeclared, errors.CapabilityNotDeclaredError)
    assert undeclared.capability == "knowledge"


def test_permission_evaluation_outage_is_its_own_class():
    error = _codes.map_error(26030, "鉴权依赖不可用", http_status=503, data={})
    assert isinstance(error, errors.PermissionEvaluationError)
    assert "不要改小检索范围" in error.next_step


def test_unregistered_code_degrades_by_http_class_then_to_refused():
    assert isinstance(_codes.map_error(None, "", http_status=401, data=None), errors.VisitorCredentialRejectedError)
    assert isinstance(_codes.map_error(None, "", http_status=502, data=None), errors.PlatformUnreachableError)

    refused = _codes.map_error(29999, "没见过的码", http_status=403, data={"x": 1})
    assert isinstance(refused, errors.PlatformRefusedError)
    assert refused.code == 29999
    assert refused.details == {"x": 1}
    assert "没见过的码" in str(refused)


def test_connect_error_is_unreachable_and_sent_once(monkeypatch: pytest.MonkeyPatch, platform_env: str):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        _http, "client", lambda base_url, kind="retrieve": httpx.Client(base_url=base_url, transport=transport)
    )

    with pytest.raises(errors.PlatformUnreachableError):
        _http.request("retrieve", "GET", "/x", base_url=platform_env)
    assert len(calls) == 1, "零重试：重试是应用的决定，不是 SDK 的"


def test_timeouts_are_tiered():
    assert _http.timeout_for("retrieve").read == _http.RETRIEVE_READ_TIMEOUT
    assert _http.timeout_for("storage").read == _http.STORAGE_READ_TIMEOUT
    assert _http.timeout_for("retrieve").connect == _http.CONNECT_TIMEOUT


def test_trust_env_is_off_unless_explicitly_enabled(monkeypatch: pytest.MonkeyPatch):
    assert _env.trust_env() is False
    client = _http.client("http://platform.test", "retrieve")
    assert client.trust_env is False

    _http.reset_clients()
    monkeypatch.setenv("BISHENG_SDK_TRUST_ENV", "1")
    assert _http.client("http://platform.test", "retrieve").trust_env is True


def test_clients_are_pooled_per_base_url_and_kind():
    first = _http.client("http://a.test", "retrieve")
    assert _http.client("http://a.test", "retrieve") is first
    assert _http.client("http://b.test", "retrieve") is not first
    assert _http.client("http://a.test", "storage") is not first


def test_bearer_never_reaches_an_exception():
    error = _codes.map_error(26002, f"token {FAKE_OBO} invalid", http_status=401, data={"echo": FAKE_OBO})
    assert FAKE_OBO not in f"{error}{error.details}"


def test_manager_envelope_is_parsed_with_its_own_shape():
    """附件 API 的信封是 `{"detail": {...}}`，不是 backend 的 status_code（坑 26）。"""
    resp = httpx.Response(
        413,
        json={"detail": {"code": "payload_too_large", "message": "too big", "max_file_mb": 20}},
        request=httpx.Request("PUT", "http://manager.test/x"),
    )
    with pytest.raises(errors.AttachmentTooLargeError) as caught:
        _http.parse_manager_envelope(resp, path="a.bin")
    assert caught.value.limit_bytes == 20 * 1024 * 1024


def test_manager_envelope_without_detail_falls_back_by_status():
    resp = httpx.Response(500, text="boom", request=httpx.Request("GET", "http://manager.test/x"))
    with pytest.raises(errors.StorageUnavailableError):
        _http.parse_manager_envelope(resp, path="a.bin")
