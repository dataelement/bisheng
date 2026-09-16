"""平台存储后端 —— 托管期的附件句柄（design D8 / §4.2 ④）。

句柄 = 注入的 ``BISHENG_APP_STORAGE_ENDPOINT``（**已经包含**
``/v1/apps/{app_id}/storage``，SDK 不拼 ``app_id``）+ ``BISHENG_APP_STORAGE_TOKEN``
（每应用一把、绑定该 app，A 的令牌打 B 的 URL 是 401）。

四条反 REST 直觉、照着直觉写就会错的地方（对方源码为准，
`tests/test_contract_alignment.py` 对账）：

* 元信息在 ``/meta/{key}``，**不是** ``/stat/``；
* ``DELETE`` 成功答 **200 `{}`**，不是 204；
* 删一个不存在的附件是 **404**，不是静默成功；
* 错误信封是 manager 形状 ``{"detail": {"code", "message", …}}``，不是 backend 的
  ``{status_code, status_message, data}``。

上传 body 是**原始字节**（不是 multipart），路径逐段 percent-encode 后拼进 URL。
永不走 manager 的 HMAC 路径——那是平台后端用的。

**连不上附件服务不是"连不上平台"**：`BISHENG_APP_STORAGE_ENDPOINT` 指向的是
runtime-manager 的应用面地址，与 `BISHENG_PLATFORM_API_BASE` 是两个地址、两套排查
动作（坑 27：manager 只听 `127.0.0.1` 或没配 `RTM_APP_FACING_BASE_URL` 时应用容器
根本够不到它）。因此本模块把传输层失败一律翻成 `StorageUnavailableError`——它的
下一步指向 `runtime/status` 的 `attachment_storage` 自检项；漏翻会让附件故障看起来
像平台故障，排查从第一步就走错方向（design D6 / AC-25「彼此可区分」）。
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any
from urllib.parse import quote

from bisheng_sdk import _env, _http
from bisheng_sdk._attachment import AttachmentMeta, parse_modified_at
from bisheng_sdk._storage_local import known_length
from bisheng_sdk.errors import AttachmentTooLargeError, PlatformUnreachableError, StorageUnavailableError

DEFAULT_CONTENT_TYPE = "application/octet-stream"
#: manager 的 `limit` 上限（`MAX_LIST_LIMIT`），单页最多这么多。
MAX_PAGE = 1000


def _as_storage_outage(exc: PlatformUnreachableError) -> StorageUnavailableError:
    """传输层失败 → 附件服务不可用（不是平台不可用）。"""
    return StorageUnavailableError(exc.message, details=exc.details)


def encode_key(path: str) -> str:
    """逐段 ``quote(seg, safe="")``：服务端用 ``{key:path}`` 接，斜杠要保留为分隔符。"""
    return "/".join(quote(segment, safe="") for segment in path.split("/"))


class RemoteBackend:
    """HTTP 句柄后端。``endpoint`` 已含应用前缀，``token`` 是该应用的句柄凭据。"""

    def __init__(self, endpoint: str, token: str, max_bytes: int | None = None) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.max_bytes = max_bytes

    # -- helpers ---------------------------------------------------------

    def _objects_url(self, path: str) -> str:
        return f"{self.endpoint}/objects/{encode_key(path)}"

    def _meta_url(self, path: str) -> str:
        return f"{self.endpoint}/meta/{encode_key(path)}"

    def _check_size(self, path: str, data: Any) -> int | None:
        size = known_length(data)
        if size is not None and self.max_bytes is not None and size > self.max_bytes:
            # 平台会再判一次答 413；能在本地判出来就不必把几十 MB 送上网。
            raise AttachmentTooLargeError(path=path, limit_bytes=self.max_bytes)
        return size

    def _meta_of(self, payload: Any, fallback_path: str) -> AttachmentMeta:
        row = payload if isinstance(payload, dict) else {}
        return AttachmentMeta(
            path=str(row.get("key") or fallback_path),
            size=int(row.get("size") or 0),
            content_type=(row.get("content_type") or None),
            modified_at=parse_modified_at(row.get("last_modified")),
            etag=str(row.get("etag") or ""),
        )

    def _put_headers(self, content_type: str | None, size: int | None) -> dict[str, str]:
        headers = {"Content-Type": content_type or DEFAULT_CONTENT_TYPE}
        if size is not None:
            # 服务端先看 `Content-Length` 再看实收字节；带上它意味着超限在第一个
            # 字节离开本进程之前就被拒。
            headers["Content-Length"] = str(size)
        return headers

    def _list_params(self, prefix: str, limit: int | None, collected: int, cursor: str | None) -> dict[str, Any]:
        page = min(limit - collected, MAX_PAGE) if limit is not None else MAX_PAGE
        params: dict[str, Any] = {"prefix": prefix, "limit": max(page, 1)}
        if cursor:
            params["cursor"] = cursor
        return params

    def _absorb_page(self, payload: Any, rows: list[AttachmentMeta]) -> str | None:
        body = payload if isinstance(payload, dict) else {}
        rows.extend(self._meta_of(row, "") for row in (body.get("objects") or []))
        return body.get("next_cursor") or None

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        """一次附件 API 调用。传输层失败在这里就翻成"附件服务不可用"。"""
        try:
            return _http.request("storage", method, url, base_url=self.endpoint, bearer=self.token, **kwargs)
        except PlatformUnreachableError as exc:
            raise _as_storage_outage(exc) from exc

    async def _asend(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            return await _http.arequest("storage", method, url, base_url=self.endpoint, bearer=self.token, **kwargs)
        except PlatformUnreachableError as exc:
            raise _as_storage_outage(exc) from exc

    # -- operations ------------------------------------------------------

    def put(self, path: str, data: Any, content_type: str | None = None) -> AttachmentMeta:
        size = self._check_size(path, data)
        with _payload(data) as body:
            resp = self._send(
                "PUT",
                self._objects_url(path),
                headers=self._put_headers(content_type, size),
                content=body,
            )
        return self._meta_of(_http.parse_manager_envelope(resp, path=path), path)

    def get(self, path: str) -> bytes:
        resp = self._send("GET", self._objects_url(path))
        if resp.status_code >= 400:
            _http.parse_manager_envelope(resp, path=path)
        return resp.content

    def open(self, path: str) -> IO[bytes]:
        return io.BytesIO(self.get(path))

    def stat(self, path: str) -> AttachmentMeta:
        resp = self._send("GET", self._meta_url(path))
        return self._meta_of(_http.parse_manager_envelope(resp, path=path), path)

    def list(self, prefix: str = "", limit: int | None = None) -> list[AttachmentMeta]:
        rows: list[AttachmentMeta] = []
        cursor: str | None = None
        while True:
            resp = self._send(
                "GET",
                f"{self.endpoint}/objects",
                params=self._list_params(prefix, limit, len(rows), cursor),
            )
            cursor = self._absorb_page(_http.parse_manager_envelope(resp, path=prefix), rows)
            if not cursor or (limit is not None and len(rows) >= limit):
                break
        return rows[:limit] if limit is not None else rows

    def delete(self, path: str) -> None:
        resp = self._send("DELETE", self._objects_url(path))
        # 成功是 200 `{}`；缺失是 404 `not_found`，由信封解析抛出。
        _http.parse_manager_envelope(resp, path=path)


class AsyncRemoteBackend(RemoteBackend):
    """异步孪生：同一套 URL、同一套错误映射，只是走 `httpx.AsyncClient`。"""

    async def aput(self, path: str, data: Any, content_type: str | None = None) -> AttachmentMeta:
        size = self._check_size(path, data)
        with _payload(data) as body:
            resp = await self._asend(
                "PUT",
                self._objects_url(path),
                headers=self._put_headers(content_type, size),
                content=body,
            )
        return self._meta_of(_http.parse_manager_envelope(resp, path=path), path)

    async def aget(self, path: str) -> bytes:
        resp = await self._asend("GET", self._objects_url(path))
        if resp.status_code >= 400:
            _http.parse_manager_envelope(resp, path=path)
        return resp.content

    async def aopen(self, path: str) -> IO[bytes]:
        return io.BytesIO(await self.aget(path))

    async def astat(self, path: str) -> AttachmentMeta:
        resp = await self._asend("GET", self._meta_url(path))
        return self._meta_of(_http.parse_manager_envelope(resp, path=path), path)

    async def alist(self, prefix: str = "", limit: int | None = None) -> list[AttachmentMeta]:
        rows: list[AttachmentMeta] = []
        cursor: str | None = None
        while True:
            resp = await self._asend(
                "GET",
                f"{self.endpoint}/objects",
                params=self._list_params(prefix, limit, len(rows), cursor),
            )
            cursor = self._absorb_page(_http.parse_manager_envelope(resp, path=prefix), rows)
            if not cursor or (limit is not None and len(rows) >= limit):
                break
        return rows[:limit] if limit is not None else rows

    async def adelete(self, path: str) -> None:
        resp = await self._asend("DELETE", self._objects_url(path))
        _http.parse_manager_envelope(resp, path=path)


def from_env(endpoint: str, token: str) -> RemoteBackend:
    return RemoteBackend(endpoint, token, max_bytes=_env.storage_max_file_bytes())


def async_from_env(endpoint: str, token: str) -> AsyncRemoteBackend:
    return AsyncRemoteBackend(endpoint, token, max_bytes=_env.storage_max_file_bytes())


@contextmanager
def _payload(data: Any) -> Iterator[Any]:
    """httpx 的 `content=` 接受 bytes / 可迭代 / 文件对象；str 先编码成 UTF-8。

    本地路径由**这里**打开也由这里关闭：httpx 不会关掉调用方给的文件对象，
    交给 GC 的话，一个循环上传几千个附件的应用会先撞上文件描述符上限。
    """
    if isinstance(data, str):
        yield data.encode("utf-8")
        return
    if isinstance(data, (bytearray, memoryview)):
        yield bytes(data)
        return
    if isinstance(data, os.PathLike):
        with open(data, "rb") as handle:
            yield handle
        return
    yield data


__all__ = ("AsyncRemoteBackend", "RemoteBackend", "async_from_env", "encode_key", "from_env")
