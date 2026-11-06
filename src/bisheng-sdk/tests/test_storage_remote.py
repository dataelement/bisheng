"""平台存储后端 —— 附件 API 契约的可执行快照（AC-20 / 21 / 22 / 25 / 31）。

每个形状都照 `runtime_manager/api/storage.py` 逐字构造，包括看着像 bug 的那几处：
`/meta/{key}` 不是 `/stat/`、DELETE 成功答 `200 {}`、删缺失的附件是 404、错误信封
是 `{"detail": {...}}`。
"""

from __future__ import annotations

import io

import httpx
import pytest

from bisheng_sdk import storage
from bisheng_sdk.errors import (
    AttachmentNotFoundError,
    AttachmentTooLargeError,
    InvalidAttachmentPathError,
    StorageHandleMissingError,
    StorageHandleRejectedError,
    StorageUnavailableError,
)
from tests.helpers import platform_mock as pm

ENCODED = "%E6%8A%A5%E5%91%8A/2026.pdf"


@pytest.fixture
def remote_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("BISHENG_APP_STORAGE_ENDPOINT", pm.STORAGE_ENDPOINT)
    monkeypatch.setenv("BISHENG_APP_STORAGE_TOKEN", pm.FAKE_STORAGE_TOKEN)
    monkeypatch.setenv("BISHENG_APP_STORAGE_MAX_FILE_MB", "20")
    return pm.STORAGE_ENDPOINT


@pytest.fixture
def remote(mock_transport, remote_env):
    def install(handler):
        return mock_transport(pm.RecordingTransport(handler))

    return install


def test_endpoint_without_token_is_an_incomplete_handle(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BISHENG_APP_STORAGE_ENDPOINT", pm.STORAGE_ENDPOINT)
    with pytest.raises(StorageHandleMissingError) as caught:
        storage.stat("a.txt")
    assert "不完整" in str(caught.value)


def test_put_sends_raw_bytes_with_bearer_and_content_length(remote):
    transport = remote(lambda request: httpx.Response(200, json=pm.storage_meta()))
    meta = storage.put("报告/2026.pdf", b"hello world", content_type="application/pdf")

    request = transport.last
    assert request.method == "PUT"
    assert request.url.raw_path.decode().endswith(f"/storage/objects/{ENCODED}")
    assert request.headers["Authorization"] == f"Bearer {pm.FAKE_STORAGE_TOKEN}"
    assert request.headers["Content-Type"] == "application/pdf"
    assert request.headers["Content-Length"] == "11"
    assert request.content == b"hello world"  # 原始字节，不是 multipart
    assert meta.path == "报告/2026.pdf"
    assert meta.etag == "abc123"
    assert meta.modified_at is not None


def test_put_streams_a_file_object(remote):
    transport = remote(lambda request: httpx.Response(200, json=pm.storage_meta(size=5)))
    storage.put("a.bin", io.BytesIO(b"hello"))
    assert transport.last.headers["Content-Length"] == "5"


def test_get_stat_list_delete_wire_shapes(remote):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and "/meta/" in path:
            return httpx.Response(200, json=pm.storage_meta())
        if request.method == "GET" and path.endswith("/objects"):
            cursor = request.url.params.get("cursor")
            if not cursor:
                return httpx.Response(200, json={"objects": [pm.storage_meta("a.txt")], "next_cursor": "a.txt"})
            return httpx.Response(200, json={"objects": [pm.storage_meta("b.txt")], "next_cursor": None})
        if request.method == "GET":
            return httpx.Response(200, content=b"hello world")
        if request.method == "DELETE":
            return httpx.Response(200, json={})  # 不是 204
        raise AssertionError(request.method)

    transport = remote(handler)

    assert storage.get("报告/2026.pdf") == b"hello world"
    assert storage.stat("报告/2026.pdf").size == 11
    assert [row.path for row in storage.list()] == ["a.txt", "b.txt"]  # 跟着 next_cursor 翻页
    storage.delete("报告/2026.pdf")

    meta_request = next(r for r in transport.requests if "/meta/" in r.url.path)
    assert meta_request.url.raw_path.decode().endswith(f"/storage/meta/{ENCODED}")


def test_list_query_parameters_follow_the_manager_contract(remote):
    transport = remote(lambda request: httpx.Response(200, json={"objects": [], "next_cursor": None}))
    storage.list("报告/", limit=5)
    params = transport.last.url.params
    assert params["prefix"] == "报告/"
    assert params["limit"] == "5"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            401,
            pm.manager_error_body("unauthorized", "invalid storage token for this application"),
            StorageHandleRejectedError,
        ),
        (404, pm.manager_error_body("not_found", "attachment does not exist"), AttachmentNotFoundError),
        (400, pm.manager_error_body("invalid_object_key", "reserved namespace"), InvalidAttachmentPathError),
        (413, pm.manager_error_body("payload_too_large", "too big", max_file_mb=20), AttachmentTooLargeError),
        (503, pm.manager_error_body("storage_unavailable", "minio not configured"), StorageUnavailableError),
    ],
)
def test_manager_machine_codes_map_one_to_one(remote, status, body, expected):
    remote(lambda request: httpx.Response(status, json=body))
    with pytest.raises(expected):
        storage.stat("a.txt")


def test_delete_of_a_missing_attachment_is_404_not_silent_success(remote):
    remote(lambda request: httpx.Response(404, json=pm.manager_error_body("not_found", "missing")))
    with pytest.raises(AttachmentNotFoundError):
        storage.delete("a.txt")


def test_list_during_an_outage_raises_instead_of_returning_an_empty_list(remote):
    remote(lambda request: httpx.Response(503, json=pm.manager_error_body("storage_unavailable", "minio down")))
    with pytest.raises(StorageUnavailableError) as caught:
        storage.list()
    assert "attachment_storage" in caught.value.next_step


@pytest.fixture
def unreachable_manager(monkeypatch: pytest.MonkeyPatch, remote_env):
    """附件端点连不上——坑 27 最常见的生产故障（manager 只听 127.0.0.1）。"""
    from bisheng_sdk import _http

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        _http, "client", lambda base_url, kind="retrieve": httpx.Client(base_url=base_url, transport=transport)
    )
    monkeypatch.setattr(
        _http,
        "aclient",
        lambda base_url, kind="retrieve": httpx.AsyncClient(base_url=base_url, transport=transport),
    )


def test_connect_failure_is_a_storage_outage_not_a_platform_outage(unreachable_manager):
    """附件端点与平台 API 是两个地址、两套排查动作（坑 27）。

    翻成 `PlatformUnreachableError` 会把人支去查 `BISHENG_PLATFORM_API_BASE`，而真正
    要看的是 `runtime/status` 的 `attachment_storage` 自检项与 `RTM_APP_FACING_BASE_URL`。
    AC-25 要求这几类错误彼此可区分，这一条就是分界线。
    """
    from bisheng_sdk.errors import PlatformUnreachableError

    for call in (lambda: storage.list(), lambda: storage.stat("a.txt"), lambda: storage.put("a.txt", b"x")):
        with pytest.raises(StorageUnavailableError) as caught:
            call()
        assert not isinstance(caught.value, PlatformUnreachableError)
        assert "attachment_storage" in caught.value.next_step


async def test_async_connect_failure_is_also_a_storage_outage(unreachable_manager):
    with pytest.raises(StorageUnavailableError):
        await storage.alist()


def test_client_side_cap_refuses_before_sending(remote):
    transport = remote(lambda request: httpx.Response(200, json=pm.storage_meta()))
    with pytest.raises(AttachmentTooLargeError) as caught:
        storage.put("big.bin", b"x" * (20 * 1024 * 1024 + 1))
    assert caught.value.limit_bytes == 20 * 1024 * 1024
    assert transport.requests == [], "超限的附件一个字节都不该离开本进程"


def test_meta_carries_no_bucket_key_endpoint_or_token(remote):
    remote(lambda request: httpx.Response(200, json=pm.storage_meta()))
    meta = storage.stat("报告/2026.pdf")
    fields = set(meta.__dataclass_fields__)
    assert fields == {"path", "size", "content_type", "modified_at", "etag"}
    rendered = repr(meta)
    assert pm.FAKE_STORAGE_TOKEN not in rendered
    assert "bisheng-apps" not in rendered
    assert "apps/" not in rendered


def test_app_id_is_never_sent_by_the_client(remote):
    transport = remote(lambda request: httpx.Response(200, json=pm.storage_meta()))
    storage.put("a.txt", b"x")
    request = transport.last
    # app_id 只在平台注入的 ENDPOINT 里；SDK 不拼、不改、不发。
    assert "app_id" not in request.url.params
    assert b"app_id" not in request.content
    assert all("app" not in name.lower() for name in request.headers if name.lower() != "authorization")


async def test_async_twins_have_the_same_wire_shape(remote):
    transport = remote(lambda request: httpx.Response(200, json=pm.storage_meta()))
    meta = await storage.aput("报告/2026.pdf", b"hello world")
    assert meta.path == "报告/2026.pdf"
    assert transport.last.headers["Authorization"] == f"Bearer {pm.FAKE_STORAGE_TOKEN}"


async def test_async_stat_open_and_delete(remote):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        if "/meta/" in request.url.path:
            return httpx.Response(200, json=pm.storage_meta())
        return httpx.Response(200, content=b"hello world")

    remote(handler)
    assert (await storage.astat("a.txt")).size == 11
    with await storage.aopen("a.txt") as handle:
        assert handle.read() == b"hello world"
    await storage.adelete("a.txt")
