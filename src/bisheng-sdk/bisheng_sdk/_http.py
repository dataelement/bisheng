"""与平台的 HTTP 往来：连接池、分档超时、两种信封、零重试（design D11）。

本文件最要命的一条规则是 :func:`parse_envelope` 的解析顺序：**先读 body，再看
状态行**。`/api/v1` 一律答 HTTP 200 并把结论放在信封的 `status_code` 里，
`/api/v2` 则既有真状态、又保留信封。先看状态行会把 v1 的业务错误当成功；只看
body 会把 v2 的 401 当没有信封（坑 7）。

**零重试**是刻意的：PUT 非幂等，而 AC-16 明令"不本地重试成更小的范围"——重试
是应用的决定，不是 SDK 的。

`trust_env=False` 同样是刻意的：托管容器里的代理变量会把平台调用送进被封的出站，
开发机上的公网代理会劫持内网地址。需要时用 `BISHENG_SDK_TRUST_ENV=1` 显式打开。
"""

from __future__ import annotations

import threading
from typing import Any

import httpx

from bisheng_sdk import _codes, _env
from bisheng_sdk.errors import PlatformUnreachableError

CONNECT_TIMEOUT = 5.0
#: 检索是每请求同步调用，读超时不能长到把应用自己的请求拖死。
RETRIEVE_READ_TIMEOUT = 30.0
#: 附件可能是几十 MB，上传下载给足时间。
STORAGE_READ_TIMEOUT = 120.0
VERSIONS_READ_TIMEOUT = 10.0

_READ_TIMEOUTS = {
    "retrieve": RETRIEVE_READ_TIMEOUT,
    "storage": STORAGE_READ_TIMEOUT,
    "versions": VERSIONS_READ_TIMEOUT,
}

_lock = threading.Lock()
_clients: dict[tuple[str, str], httpx.Client] = {}
_aclients: dict[tuple[str, str], httpx.AsyncClient] = {}


def timeout_for(kind: str) -> httpx.Timeout:
    read = _READ_TIMEOUTS.get(kind, RETRIEVE_READ_TIMEOUT)
    return httpx.Timeout(read, connect=CONNECT_TIMEOUT, read=read, write=read, pool=CONNECT_TIMEOUT)


def client(base_url: str, kind: str = "retrieve") -> httpx.Client:
    """按 (base_url, kind) 复用的同步客户端（连接池活在进程内）。"""
    key = (base_url, kind)
    with _lock:
        existing = _clients.get(key)
        if existing is not None:
            return existing
        created = httpx.Client(base_url=base_url, timeout=timeout_for(kind), trust_env=_env.trust_env())
        _clients[key] = created
        return created


def aclient(base_url: str, kind: str = "retrieve") -> httpx.AsyncClient:
    key = (base_url, kind)
    with _lock:
        existing = _aclients.get(key)
        if existing is not None:
            return existing
        created = httpx.AsyncClient(base_url=base_url, timeout=timeout_for(kind), trust_env=_env.trust_env())
        _aclients[key] = created
        return created


def reset_clients() -> None:
    """丢弃连接池。测试与"环境变量变了"之后用；生产路径不调用。"""
    with _lock:
        for pooled in _clients.values():
            try:
                pooled.close()
            except Exception:  # pragma: no cover - 关闭失败不该影响调用方
                pass
        _clients.clear()
        _aclients.clear()


def request(
    kind: str,
    method: str,
    url: str,
    *,
    base_url: str,
    bearer: str | None = None,
    headers: dict[str, str] | None = None,
    json: Any = None,
    content: Any = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    """发一次请求。连接 / 超时类失败统一成 `PlatformUnreachableError`。"""
    try:
        return client(base_url, kind).request(
            method,
            url,
            headers=_headers_for(bearer, headers),
            json=json,
            content=content,
            params=params,
        )
    except httpx.HTTPError as exc:
        raise _unreachable(base_url, exc)


async def arequest(
    kind: str,
    method: str,
    url: str,
    *,
    base_url: str,
    bearer: str | None = None,
    headers: dict[str, str] | None = None,
    json: Any = None,
    content: Any = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    try:
        return await aclient(base_url, kind).request(
            method,
            url,
            headers=_headers_for(bearer, headers),
            json=json,
            content=content,
            params=params,
        )
    except httpx.HTTPError as exc:
        raise _unreachable(base_url, exc)


def _headers_for(bearer: str | None, extra: dict[str, str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if extra:
        headers.update({name: value for name, value in extra.items() if value is not None})
    return headers


def _unreachable(base_url: str, exc: httpx.HTTPError) -> PlatformUnreachableError:
    # 异常文本里可能带 URL，不带凭据；`BishengSdkError` 仍会过一遍掩码。
    return PlatformUnreachableError(f"连接平台 {base_url} 失败：{type(exc).__name__}: {exc}")


def parse_envelope(resp: httpx.Response) -> Any:
    """返回信封的 `data`，或抛出翻译后的异常。顺序见模块 docstring。"""
    body = _json_or_none(resp)

    if isinstance(body, dict) and "status_code" in body:
        status_code = body.get("status_code")
        if isinstance(status_code, int) and status_code != 200:
            raise _codes.map_error(
                status_code,
                str(body.get("status_message") or ""),
                http_status=resp.status_code,
                data=body.get("data"),
            )
        return body.get("data")

    if resp.status_code >= 400:
        raise _codes.map_error(
            None,
            _text_excerpt(resp),
            http_status=resp.status_code,
            data=None,
        )
    return body


def parse_manager_envelope(resp: httpx.Response, *, path: str = "") -> Any:
    """runtime-manager 的附件 API：成功返 JSON，失败读 `{"detail": {...}}`。"""
    if resp.status_code < 400:
        return _json_or_none(resp)

    body = _json_or_none(resp)
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        raise _codes.map_storage_error(
            _as_str(detail.get("code")),
            str(detail.get("message") or ""),
            http_status=resp.status_code,
            detail=detail,
            path=path,
        )
    # FastAPI 的默认校验错误（`detail` 是列表）与任何非 JSON 响应都落这里。
    raise _codes.map_storage_error(
        None,
        _text_excerpt(resp),
        http_status=resp.status_code,
        detail=detail if isinstance(detail, dict) else None,
        path=path,
    )


def _json_or_none(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _text_excerpt(resp: httpx.Response) -> str:
    try:
        return resp.text[:200]
    except Exception:  # pragma: no cover - defensive
        return ""
