"""T007 — HTTP client, the two envelope shapes, and the pre-flight probe."""

from __future__ import annotations

import io

import httpx
import pytest

from bisheng_cli import __version__
from bisheng_cli.errors import (
    EXIT_AUTH,
    EXIT_FORBIDDEN,
    EXIT_NOT_ENABLED,
    EXIT_PLATFORM_TOO_OLD,
    EXIT_UNREACHABLE,
    CliError,
)
from bisheng_cli.http import (
    CONNECT_TIMEOUT,
    NGINX_PROXY_READ_TIMEOUT,
    READ_TIMEOUT,
    UPLOAD_READ_TIMEOUT,
    PlatformClient,
    parse_envelope,
    probe,
)
from bisheng_cli.output import Emitter
from tests.helpers.platform_mock import (
    FAKE_KEY,
    PlatformMock,
    env_legacy,
    env_ok,
    v1_envelope,
    v2_error,
    versions_404,
    versions_ok,
)

BASE = "http://platform.test"


def _client(mock: PlatformMock, **kw) -> PlatformClient:
    return PlatformClient(BASE, api_key=FAKE_KEY, transport=mock.transport, **kw)


def test_envelope_parsed_body_status_code_first_then_http_status() -> None:
    # /api/v1 answers HTTP 200 with the verdict in the body. Reading the status
    # line first would classify every v1 business error as a success.
    ok_status_bad_body = httpx.Response(200, json={"status_code": 16207, "status_message": "layer off", "data": {}})
    with pytest.raises(CliError) as excinfo:
        parse_envelope(ok_status_bad_body)
    assert excinfo.value.code == 16207
    assert excinfo.value.exit_code == EXIT_NOT_ENABLED

    # And a real 503 whose body names 26030 must translate as 26030, not as a
    # generic "some 5xx".
    bad_status_known_body = v2_error(26030, "auth service down")
    with pytest.raises(CliError) as excinfo:
        parse_envelope(bad_status_known_body)
    assert excinfo.value.code == 26030


def test_v1_http200_business_error_is_treated_as_error() -> None:
    mock = PlatformMock().get("/api/v1/env", v1_envelope(None, status_code=20001, status_message="tenant disabled"))
    with pytest.raises(CliError) as excinfo:
        _client(mock).get_json("/api/v1/env")
    assert excinfo.value.code == 20001


@pytest.mark.parametrize(
    ("code", "http_status", "expected_exit"),
    [(26002, 401, EXIT_AUTH), (26003, 403, EXIT_FORBIDDEN), (26030, 503, EXIT_UNREACHABLE)],
)
def test_v2_real_http_401_403_503_parsed_with_envelope_body(code: int, http_status: int, expected_exit: int) -> None:
    mock = PlatformMock().get("/api/v2/auth/whoami", v2_error(code, "nope"))
    with pytest.raises(CliError) as excinfo:
        _client(mock).get_json("/api/v2/auth/whoami")
    assert excinfo.value.code == code
    assert excinfo.value.exit_code == expected_exit


def test_v1_success_returns_data_payload() -> None:
    mock = PlatformMock().get("/api/v1/env", env_ok())
    data = _client(mock).get_json("/api/v1/env")
    assert data["open_platform_enabled"] is True


def test_probe_versions_404_and_env_open_platform_false_exits_8() -> None:
    mock = PlatformMock().get("/api/v1/dev-toolkit/versions", versions_404())
    mock.get("/api/v1/env", env_ok(open_platform_enabled=False))
    with pytest.raises(CliError) as excinfo:
        probe(_client(mock))
    assert excinfo.value.exit_code == EXIT_NOT_ENABLED
    assert "开放能力层" in excinfo.value.message


def test_probe_versions_404_and_env_without_open_platform_flag_exits_9() -> None:
    mock = PlatformMock().get("/api/v1/dev-toolkit/versions", versions_404())
    mock.get("/api/v1/env", env_legacy())
    with pytest.raises(CliError) as excinfo:
        probe(_client(mock))
    assert excinfo.value.exit_code == EXIT_PLATFORM_TOO_OLD
    assert "版本" in excinfo.value.message


def test_probe_env_unreachable_exits_7() -> None:
    mock = PlatformMock().get("/api/v1/dev-toolkit/versions", versions_404())
    mock.get("/api/v1/env", httpx.ConnectError("refused"))
    with pytest.raises(CliError) as excinfo:
        probe(_client(mock))
    assert excinfo.value.exit_code == EXIT_UNREACHABLE


def test_probe_stops_before_whoami_when_layer_absent() -> None:
    # AC-05's "login is unusable in this environment" is paid for right here:
    # the probe decides before any credential ever leaves the machine.
    mock = PlatformMock().get("/api/v1/dev-toolkit/versions", versions_404())
    mock.get("/api/v1/env", env_ok(open_platform_enabled=False))
    with pytest.raises(CliError):
        probe(_client(mock))
    assert "/api/v2/auth/whoami" not in mock.paths_called()


def test_min_compatible_greater_than_local_warns_but_does_not_block() -> None:
    mock = PlatformMock().get("/api/v1/dev-toolkit/versions", versions_ok(cli_version="9.9.9", min_compatible="9.9.9"))
    err = io.StringIO()
    emitter = Emitter(stdout=io.StringIO(), stderr=err, is_tty=False)
    result = probe(_client(mock, emitter=emitter))
    assert result.versions is not None
    assert result.warning and "9.9.9" in result.warning
    assert "警告" in err.getvalue()


def test_min_compatible_equal_to_local_does_not_warn() -> None:
    mock = PlatformMock().get("/api/v1/dev-toolkit/versions", versions_ok(min_compatible=__version__))
    assert probe(_client(mock)).warning is None


def test_no_scopes_cached_between_calls() -> None:
    mock = PlatformMock().get("/api/v2/auth/whoami", v1_envelope({"scopes": ["app:manage"]}))
    client = _client(mock)
    client.get_json("/api/v2/auth/whoami")
    client.get_json("/api/v2/auth/whoami")
    # Two calls, two round trips: a cached scope set is how "the admin ticked the
    # box but the CLI still says no" happens.
    assert mock.paths_called().count("/api/v2/auth/whoami") == 2
    assert not [name for name in vars(client) if "scope" in name.lower()]


def test_proxy_env_detected_and_named_in_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")
    mock = PlatformMock().get("/api/v1/env", httpx.ConnectError("refused"))
    with pytest.raises(CliError) as excinfo:
        _client(mock).get_json("/api/v1/env")
    text = excinfo.value.message + excinfo.value.next_step
    assert "ALL_PROXY" in text and "NO_PROXY" in text
    assert excinfo.value.exit_code == EXIT_UNREACHABLE


def test_no_proxy_flag_disables_env_trust() -> None:
    mock = PlatformMock().get("/api/v1/env", env_ok())
    client = _client(mock, trust_env=False)
    assert client.trust_env is False
    client.get_json("/api/v1/env")


def test_upload_read_timeout_is_240s_below_nginx_300s() -> None:
    # The CLI must time out first; otherwise the user gets nginx's 504 with no
    # idea which side gave up.
    assert UPLOAD_READ_TIMEOUT == 240.0
    assert UPLOAD_READ_TIMEOUT < NGINX_PROXY_READ_TIMEOUT == 300.0
    assert CONNECT_TIMEOUT == 10.0 and READ_TIMEOUT == 60.0


def test_bearer_header_masked_in_verbose_log() -> None:
    err = io.StringIO()
    emitter = Emitter(stdout=io.StringIO(), stderr=err, verbose=True, is_tty=False)
    mock = PlatformMock().get("/api/v1/env", env_ok())
    _client(mock, emitter=emitter).get_json("/api/v1/env")
    text = err.getvalue()
    assert FAKE_KEY not in text
    assert "/api/v1/env" in text and "200" in text


def test_authorization_header_is_sent_when_key_present() -> None:
    mock = PlatformMock().get("/api/v1/env", env_ok())
    _client(mock).get_json("/api/v1/env")
    assert mock.calls[0].headers["authorization"] == f"Bearer {FAKE_KEY}"


def test_no_identity_delegation_headers_are_ever_sent() -> None:
    # 26004 exists precisely because these headers would be a CLI defect.
    mock = PlatformMock().get("/api/v1/env", env_ok())
    _client(mock).get_json("/api/v1/env")
    sent = {k.lower() for k in mock.calls[0].headers}
    assert "x-bisheng-on-behalf-of" not in sent
    assert "x-bisheng-end-user" not in sent
