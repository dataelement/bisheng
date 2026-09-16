"""读平台注入的访问者身份——**唯一「写错了应用照样跑」的静默失败点**。

一行到位：

    from bisheng_sdk import auth

    user = auth.current_user()     # 无注入身份即抛错，绝不返回 None / 匿名

这里没有登录页、没有签发或校验凭据的 API、没有 ``as_user`` 之类覆盖身份的参数。
伪造注入头无效是**入口拓扑**保证的（线上应用容器仅经 app-proxy 可达且 app-proxy
剥掉伪造头，本地迷你代理同理），SDK 不验签、也不持有任何验签密钥材料——验签会把
密钥分发进应用容器，新增一个泄漏面，而验签失败与"没有注入"在应用侧毫无区别。

把当前请求交给 SDK 有三种接法，指南与技能包只教这三种：

1. **ASGI**（FastAPI / Starlette）：``app.add_middleware(auth.ASGIMiddleware)``
2. **WSGI**（Flask 等）：``app.wsgi_app = auth.WSGIMiddleware(app.wsgi_app)``
3. **显式绑定**（Streamlit、没有中间件钩子的框架、测试）：
   ``with auth.bind(headers): ...``

中间件**不拒绝**没有注入头的请求：健康探活照常进入应用，只有真的调用
:func:`current_user` 的那一刻才抛错（AC-07 的落点在读取处）。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from bisheng_sdk import _context, _headers
from bisheng_sdk.errors import PlatformIdentityMissingError

__all__ = ("ASGIMiddleware", "Identity", "WSGIMiddleware", "bind", "current_user", "from_headers")


@dataclass(frozen=True)
class Identity:
    """当前访问者。字段即平台注入的那一组，原样透传、不推导、不补全。

    两处容易踩：

    * **所有标识都是 ``str``。** ``bisheng dev`` 期的 ``user_id`` 是**服务账号
      id**，与平台 ``user`` 表不是一张表——当成 ``user.id`` 去 join 会得到错的人。
    * **``subject_kind`` 线上的字面值是 ``"human"``**（不是 ``natural_person``）；
      ``dev`` 期取决于 ``login`` 用的密钥：服务账号密钥 → ``"service_account"``、
      个人访问令牌 → ``"human"``。

    没有 ``access_token`` 字段：访问者凭据只活在请求上下文里，供 retrieve 读取，
    不上对象、不进日志（AC-04）。
    """

    user_id: str
    user_name: str = ""
    tenant_id: str = ""
    dept_id: str | None = None
    dept_name: str | None = None
    dept_path: str | None = None
    subject_kind: str = _headers.DEFAULT_SUBJECT_KIND
    app_id: str = ""
    request_id: str | None = None

    @property
    def is_service_account(self) -> bool:
        """本地 `bisheng dev` 期常见；页面角标「本地开发 · 服务账号」用它。"""
        return self.subject_kind == "service_account"


def _parse_identity(snapshot: Mapping[str, str]) -> Identity:
    user_id = (snapshot.get(_headers.HEADER_USER_ID) or "").strip()
    if not user_id:
        raise PlatformIdentityMissingError()

    def text(name: str) -> str:
        return _headers.decode_value(snapshot.get(name) or "")

    def optional(name: str) -> str | None:
        # 缺失的头是「不发」而不是「发空串」——服务账号没有部门（design 坑 2）。
        raw = snapshot.get(name)
        if raw is None or raw == "":
            return None
        return _headers.decode_value(raw)

    return Identity(
        user_id=user_id,
        user_name=text(_headers.HEADER_USER_NAME),
        tenant_id=(snapshot.get(_headers.HEADER_TENANT_ID) or ""),
        dept_id=optional(_headers.HEADER_DEPT_ID),
        dept_name=optional(_headers.HEADER_DEPT_NAME),
        dept_path=optional(_headers.HEADER_DEPT_PATH),
        subject_kind=(snapshot.get(_headers.HEADER_SUBJECT_KIND) or _headers.DEFAULT_SUBJECT_KIND),
        app_id=(snapshot.get(_headers.HEADER_APP_ID) or ""),
        request_id=(snapshot.get(_headers.HEADER_REQUEST_ID) or None),
    )


def current_user() -> Identity:
    """当前请求的访问者。没有注入身份就抛 :class:`PlatformIdentityMissingError`。

    健康探活端点、后台任务、单元测试裸调用会遇到这条错误——这是**刻意的**：
    健康端点不该问"谁在访问"，后台任务没有访问者。不提供"宽松模式"开关，否则
    静默失败点就又回来了。
    """
    snapshot = _context.current()
    if not snapshot:
        raise PlatformIdentityMissingError()
    return _parse_identity(snapshot)


def from_headers(headers: Iterable[tuple[str, str]] | Mapping[str, str]) -> Identity:
    """纯函数版：直接从一组头解析身份，不碰上下文。

    用于握手回调等一次性场景。它和 :func:`current_user` 用同一套解析，所以
    "自己读头"与"用 SDK"的结果不会有两套口径。
    """
    return _parse_identity(_headers.snapshot(headers))


@contextmanager
def bind(headers: Iterable[tuple[str, str]] | Mapping[str, str]) -> Iterator[None]:
    """在一段代码内把这组头当作当前请求的注入头。

    Streamlit 每次 rerun 是**新线程、空上下文**，请求头只能从
    ``st.context.headers`` 拿，因此要在脚本顶部绑定（design 坑 13）。
    """
    token = _context.bind(_headers.snapshot(headers))
    try:
        yield
    finally:
        _context.reset(token)


class ASGIMiddleware:
    """纯 ASGI 中间件：把本请求的注入头放进上下文，请求结束即复位。

    ⚠️ **不要**改成继承 Starlette 的 ``BaseHTTPMiddleware``：它在独立任务里跑
    ``call_next``，ContextVar 在任务边界只复制不回传，第二个请求起 ``reset``
    会抛 ``ValueError: Token was created in a different Context``（坑 14）。

    WebSocket 取握手 scope 的头（AC-09）；连接的授权有效期与到期断开由平台入口
    负责，SDK 不续期。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = _context.bind(_headers.snapshot(scope.get("headers") or []))
        try:
            await self.app(scope, receive, send)
        finally:
            _context.reset(token)


class _ResetOnClose:
    """WSGI 响应体的包装：迭代完（或服务器 close 时）才复位上下文。"""

    def __init__(self, body, token) -> None:
        self._body = body
        self._token = token

    def __iter__(self):
        return iter(self._body)

    def close(self) -> None:
        try:
            closer = getattr(self._body, "close", None)
            if closer is not None:
                closer()
        finally:
            _context.reset(self._token)


class WSGIMiddleware:
    """WSGI 版：从 ``environ`` 的 ``HTTP_X_BISHENG_*`` 还原同一份快照。"""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        token = _context.bind(_headers.wsgi_snapshot(environ))
        try:
            result = self.app(environ, start_response)
        except BaseException:
            _context.reset(token)
            raise
        # 上下文要活到响应**迭代完**为止，不是活到视图函数返回为止：一个流式
        # 响应（`yield` 出来的生成器）会在返回之后才真正跑业务代码，那时再调
        # `current_user()` 必须仍拿得到身份。
        return _ResetOnClose(result, token)
