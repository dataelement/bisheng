"""版本兼容：懒探测、只比下界、成功才缓存（AC-03 / AC-05）。"""

from __future__ import annotations

import httpx
import pytest

import bisheng_sdk
from bisheng_sdk import _compat, auth
from bisheng_sdk.errors import PlatformTooOldError, PlatformUnreachableError, SdkIncompatibleError
from tests.helpers import platform_mock as pm


def _versions_transport(payload, status: int = 200):
    return pm.routes(
        {pm.VERSIONS_PATH: pm.json_response(status, {"status_code": 200, "status_message": "", "data": payload})}
    )


@pytest.mark.parametrize("local_min", ["0.1.0", "0.0.9"])
def test_compatible_when_min_is_not_above_local(mock_transport, platform_env: str, local_min: str):
    transport = mock_transport(_versions_transport(pm.versions_payload(min_compatible=local_min)))
    _compat.ensure_compatible(platform_env)
    assert len(transport.requests) == 1


def test_incompatible_names_both_versions_and_the_remedy(mock_transport, platform_env: str):
    mock_transport(_versions_transport(pm.versions_payload(min_compatible="0.3.0")))
    with pytest.raises(SdkIncompatibleError) as caught:
        _compat.ensure_compatible(platform_env)
    rendered = str(caught.value)
    assert "0.3.0" in rendered and bisheng_sdk.__version__ in rendered and "3.0.0" in rendered
    assert "重新获取" in rendered


def test_sdk_block_null_is_platform_too_old(mock_transport, platform_env: str):
    mock_transport(_versions_transport(pm.versions_payload(version=None)))
    with pytest.raises(PlatformTooOldError) as caught:
        _compat.ensure_compatible(platform_env)
    assert "开放能力层" in str(caught.value)


def test_versions_404_is_platform_too_old(mock_transport, platform_env: str):
    mock_transport(pm.routes({pm.VERSIONS_PATH: pm.json_response(404, {"detail": "Not Found"})}))
    with pytest.raises(PlatformTooOldError):
        _compat.ensure_compatible(platform_env)


def test_probe_runs_once_per_process_per_base(mock_transport, platform_env: str):
    transport = mock_transport(_versions_transport(pm.versions_payload()))
    _compat.ensure_compatible(platform_env)
    _compat.ensure_compatible(platform_env)
    assert len(transport.requests) == 1


def test_unreachable_is_not_cached(monkeypatch: pytest.MonkeyPatch, platform_env: str):
    from bisheng_sdk import _http

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        _http, "client", lambda base_url, kind="retrieve": httpx.Client(base_url=base_url, transport=transport)
    )
    for _ in range(2):
        with pytest.raises(PlatformUnreachableError):
            _compat.ensure_compatible(platform_env)
    assert len(calls) == 2


def test_auth_never_probes(platform_env: str):
    """auth 是纯上下文读取、零 I/O；`no_network` 哨兵会让任何请求当场炸。"""
    with auth.bind(pm.hosted_headers()):
        assert auth.current_user().user_id == "42"


@pytest.mark.parametrize(
    ("left", "right"),
    [("0.10.0", "0.9.9"), ("1.0.0", "0.99.99"), ("0.1.1", "0.1.0")],
)
def test_version_tuple_is_numeric_not_lexicographic(left: str, right: str):
    assert _compat.version_tuple(left) > _compat.version_tuple(right)


async def test_async_probe_shares_the_same_cache(mock_transport, platform_env: str):
    transport = mock_transport(_versions_transport(pm.versions_payload()))
    await _compat.aensure_compatible(platform_env)
    _compat.ensure_compatible(platform_env)
    assert len(transport.requests) == 1
