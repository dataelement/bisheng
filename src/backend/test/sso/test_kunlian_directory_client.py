"""T013 覆盖 AC-05, AC-15, AC-16, AC-19, AC-24。仅使用 MockTransport。"""

from importlib import import_module

import httpx
import pytest
from pydantic import SecretStr

from bisheng.common.errcode.sso_sync import KunlianDirectorySyncError
from bisheng.core.config.sso_sync import KunlianConf

BASE = "https://fixture.example"
LIST = "/api/v1/integrations/user-sync/users"
DETAIL = "/api/v1/integrations/user-sync/tenants/{tenant_id}/users/{id}"


def item():
    return {
        "id": "member-1",
        "subject": "subject-1",
        "tenant_id": "tenant-1",
        "member_no": None,
        "display_name": "示例",
        "login_name": None,
        "status": "ACTIVE",
        "deleted": False,
        "version": "opaque-z",
        "authz_version": "opaque-a",
        "organization_ids": [],
        "position_ids": [],
        "role_ids": [],
        "roles": [],
        "extends": [],
        "tenant": {"id": "tenant-1", "code": "fixture", "name": "示例", "status": "ACTIVE", "version": "v3"},
    }


def payload(items=None, cursor=""):
    return {
        "code": "OK",
        "message": "success",
        "request_id": "fixture-request",
        "data": {"items": [item()] if items is None else items, "next_page_token": cursor},
    }


@pytest.fixture
def client_type():
    try:
        module = import_module("bisheng.sso_sync.domain.clients.kunlian")
    except ModuleNotFoundError as exc:
        if exc.name not in ("bisheng.sso_sync.domain.clients", "bisheng.sso_sync.domain.clients.kunlian"):
            raise
        pytest.fail("T014 directory client is not implemented", pytrace=False)
    return module.KunlianDirectoryClient


def config(**kwargs):
    return KunlianConf(issuer=BASE, endpoint_allowlist=[BASE + LIST, BASE + DETAIL], get_retry_budget=1, **kwargs)


async def test_exact_headers_pagination_and_member_id_detail(client_type):
    requests = []

    def respond(request):
        requests.append(request)
        forbidden = {"authorization", "cookie", "origin", "sec-fetch-site", "x-tenant-id", "x-user-id"}
        assert not forbidden.intersection(request.headers)
        assert request.headers["X-API-Key"] == "fixture-key"
        if len(requests) == 3:
            assert request.url.path.endswith("/tenant-1/users/member-1")
            assert not request.url.query
            return httpx.Response(200, json={"code": "OK", "data": item(), "request_id": "detail"})
        assert set(request.url.params) <= {"page_token", "page_size"}
        return httpx.Response(
            200,
            json=payload(cursor="opaque cursor" if len(requests) == 1 else ""),
            headers={"Set-Cookie": "untrusted=must-not-return"},
        )

    async with client_type(
        config(), api_key=SecretStr("fixture-key"), transport=httpx.MockTransport(respond)
    ) as client:
        first = await client.list_users()
        assert first.items[0].subject == "subject-1" and first.items[0].id == "member-1"
        assert first.items[0].version == "opaque-z"
        await client.list_users(page_token=first.next_page_token)
        await client.get_user("tenant-1", "member-1")
    assert dict(requests[0].url.params) == {"page_size": "20"}
    assert requests[1].url.params["page_token"] == "opaque cursor"


async def test_oversized_directory_page_is_closed_before_full_buffering(client_type):
    """AC-16, AC-19:超预算页立即失败且不继续读取整个目录载荷。"""

    class LargeBody(httpx.AsyncByteStream):
        reads = 0
        closed = False

        async def __aiter__(self):
            for _ in range(16):
                self.reads += 1
                yield b"x" * (512 * 1024)

        async def aclose(self):
            self.closed = True

    stream = LargeBody()
    async with client_type(
        config(),
        api_key=SecretStr("synthetic-directory-key"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    ) as client:
        with pytest.raises(KunlianDirectorySyncError):
            await client.list_users()
    assert stream.reads <= 9 and stream.closed


@pytest.mark.parametrize(
    "status,code", [(400, "INVALID_ARGUMENT"), (401, "UNAUTHENTICATED"), (403, "PERMISSION_DENIED"), (404, "NOT_FOUND")]
)
async def test_permanent_error_is_not_retried_or_empty_success(client_type, status, code):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"code": code, "message": "untrusted-message", "data": None})

    async with client_type(
        config(), api_key=SecretStr("fixture-key"), transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(KunlianDirectorySyncError) as caught:
            await client.list_users()
    assert caught.value.upstream_status == status and caught.value.upstream_code == code
    assert len(calls) == 1 and "untrusted-message" not in str(caught.value)


@pytest.mark.parametrize("bad", ["html", "redirect", "missing_identity", "bad_cursor", "tenant_mismatch"])
async def test_invalid_or_untrusted_response_rejects_whole_page(client_type, bad):
    def respond(request):
        if bad == "html":
            return httpx.Response(403, text="<html>denied</html>")
        if bad == "redirect":
            return httpx.Response(302, headers={"Location": "https://untrusted.example/"})
        data = payload()
        if bad == "missing_identity":
            del data["data"]["items"][0]["subject"]
        if bad == "bad_cursor":
            data["data"]["next_page_token"] = "x" * 1025
        if bad == "tenant_mismatch":
            data["data"]["items"][0]["tenant"]["id"] = "other-tenant"
        return httpx.Response(200, json=data)

    async with client_type(
        config(), api_key=SecretStr("fixture-key"), transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(KunlianDirectorySyncError):
            await client.list_users()


async def test_transient_failure_has_bounded_retry_and_empty_success_is_real(client_type):
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"code": "SERVICE_OVERLOADED", "data": None})
        return httpx.Response(200, json=payload(items=[]))

    async with client_type(
        config(), api_key=SecretStr("fixture-key"), transport=httpx.MockTransport(respond)
    ) as client:
        result = await client.list_users()
    assert result.items == () and result.next_page_token == "" and len(calls) == 2
