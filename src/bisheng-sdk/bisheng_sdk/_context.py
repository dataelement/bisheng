"""当前请求的注入头快照，存在一个 `ContextVar` 里（design D3）。

为什么是 `ContextVar` 而不是线程局部变量或进程全局：asyncio 下线程局部失效，
进程全局会让并发处理两个用户的请求互相串扰（AC-09）。`ContextVar` 的语义恰好
就是我们要的——新任务复制父上下文、新线程从空开始，于是"后台线程里没有访问者"
是标准库替我们保证的，不是 SDK 兜出来的。
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from bisheng_sdk import _headers

_current: ContextVar[dict[str, str] | None] = ContextVar("bisheng_sdk_request_headers", default=None)


def bind(snapshot: dict[str, str]) -> Token:
    """把本请求的快照放进上下文；返回的 token 用于 :func:`reset`。"""
    return _current.set(dict(snapshot))


def reset(token: Token) -> None:
    """请求结束时复位。

    ⚠️ 必须在 **同一个** 上下文里 reset。Starlette 的 `BaseHTTPMiddleware` 把
    `call_next` 放进独立任务，token 跨任务 reset 会抛
    `ValueError: Token was created in a different Context`——这就是
    `auth.ASGIMiddleware` 必须是纯 ASGI 可调用的原因（design 坑 14）。
    """
    try:
        _current.reset(token)
    except ValueError:
        # 上下文已经不是当初 set 的那个（例如调用方把 reset 放进了别的任务）。
        # 与其让应用在正常请求路径上崩，不如清空——语义上等价于"请求结束了"。
        _current.set(None)


def clear() -> None:
    """丢掉当前上下文里的快照（测试与显式收尾用）。"""
    _current.set(None)


def current() -> dict[str, str] | None:
    return _current.get()


def access_token() -> str | None:
    """本请求的访问者凭据（`X-BiSheng-Access-Token` 的值），没有则 ``None``。

    它**只**活在上下文里：`Identity` 上没有这个字段，进程级环境变量里也没有
    （spec 决议-2 / AC-04）。
    """
    snapshot = _current.get()
    if not snapshot:
        return None
    return snapshot.get(_headers.HEADER_ACCESS_TOKEN) or None
