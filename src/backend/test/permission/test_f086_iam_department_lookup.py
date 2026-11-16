"""IAM transport stays GET-only, exact-ID, bounded, and free of credentials in evidence."""

import hashlib

import httpx
import pytest

from bisheng.permission.domain.services.department_recovery_plan import RecoveryRuntimeError
from scripts.iam_department_lookup import IamDepartmentLookup, IamLookupError


@pytest.fixture
def configuration(monkeypatch):
    monkeypatch.setenv("BS_DEPARTMENT_IAM_APP_ID", "test-app")
    monkeypatch.setenv("BS_DEPARTMENT_IAM_APP_SECRET", "test-only-value")
    return {"base_url": "https://iam.test", "bisheng_source": "wecom", "max_qps": 5}


async def test_get_exact_large_id_ignores_first_and_extra_descendant(configuration):
    requests = []

    def response(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/openapi_v2/qywx_department/list"
        assert dict(request.url.params) == {"department_id": "4294956307"}
        assert request.headers["X-App-Token"] == hashlib.sha256(b"test-apptest-only-value123").hexdigest()
        return httpx.Response(
            200,
            json={
                "errcode": 0,
                "department": [
                    {"id": "other", "parentid": "0", "enable": 1},
                    {"id": "4294956307", "parentid": "17531470", "enable": 1, "private": "not exported"},
                ],
            },
        )

    lookup = IamDepartmentLookup(configuration, transport=httpx.MockTransport(response), clock=lambda: 123)
    try:
        row = await lookup.department("4294956307")
        assert row == {"id": "4294956307", "parentid": "17531470", "enable": 1}
        assert await lookup.department("4294956307") == row and len(requests) == 1
        assert "test-only-value" not in str(row)
        with pytest.raises(IamLookupError, match="INVALID_OR_ROOT"):
            await lookup.department("0")
        assert len(requests) == 1
    finally:
        await lookup.close()


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"department": []}, "ID_MISSING"),
        ({"errcode": "error", "errmsg": "sensitive upstream text"}, "NOT_SUCCESS"),
        ({"errcode": 0, "department": [{"id": "9", "parentid": "1", "enable": 1}] * 2}, "DUPLICATE"),
        ({"errcode": 0, "department": [{"id": "9", "enable": 1}]}, "PARENT_ID_INVALID"),
        ({"errcode": 0, "department": [{"id": "9", "parentid": "1"}]}, "ENABLE_MISSING"),
        ({"errcode": 0, "department": [{"id": "8", "parentid": "1", "enable": 1}]}, "ID_MISSING"),
    ],
)
async def test_bad_payloads_block_without_returning_raw_body(configuration, payload, reason):
    lookup = IamDepartmentLookup(
        configuration, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(IamLookupError, match=reason) as error:
            await lookup.department("9")
        assert "sensitive" not in str(error.value)
    finally:
        await lookup.close()


async def test_redirect_response_limit_and_request_budget(configuration):
    for response, reason in (
        (httpx.Response(302, headers={"location": "https://other.test"}), "STATUS_302"),
        (httpx.Response(200, content=b"x" * 128), "RESPONSE_TOO_LARGE"),
    ):
        lookup = IamDepartmentLookup(configuration, transport=httpx.MockTransport(lambda r, value=response: value))
        lookup.max_response_bytes = 64
        try:
            with pytest.raises(IamLookupError, match=reason):
                await lookup.department("9")
            assert lookup.calls == 1
            lookup.calls = lookup.max_requests
            with pytest.raises(RecoveryRuntimeError, match="REQUEST_LIMIT"):
                await lookup.department("10")
        finally:
            await lookup.close()


@pytest.mark.parametrize(
    "override",
    [
        {"base_url": "https://user:password@iam.test"},
        {"base_url": "https://iam.test?secret=x"},
        {"timeout_seconds": float("nan")},
        {"max_qps": float("inf")},
        {"bisheng_source": ""},
    ],
)
def test_invalid_configuration_refused(configuration, override):
    with pytest.raises(IamLookupError):
        IamDepartmentLookup(configuration | override)
