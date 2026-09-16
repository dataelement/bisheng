"""auth：读注入身份、三种接法、无注入即抛错（AC-04 / 06 / 07 / 08 / 09 / 10 / 31）。"""

from __future__ import annotations

import pytest

from bisheng_sdk import auth
from bisheng_sdk.errors import PlatformIdentityMissingError
from tests.helpers.platform_mock import FAKE_OBO, dev_headers, hosted_headers


def test_current_user_from_hosted_headers():
    with auth.bind(hosted_headers()):
        user = auth.current_user()
    assert user.user_id == "42"
    assert user.user_name == "张三"  # 注入侧 quote 过，SDK 要解回来
    assert user.tenant_id == "1"
    assert user.dept_path == "集团/财务部"  # Path 里的 / 必须保留
    assert user.subject_kind == "human"  # 线上字面值是 human，不是 natural_person
    assert user.app_id == "app-1"
    assert user.request_id == "req-1"


def test_missing_dept_headers_become_none_not_empty_string():
    with auth.bind(hosted_headers(dept=False)):
        user = auth.current_user()
    assert (user.dept_id, user.dept_name, user.dept_path) == (None, None, None)


def test_dev_service_account_identity_has_same_shape():
    with auth.bind(dev_headers()):
        user = auth.current_user()
    assert user.subject_kind == "service_account"
    assert user.is_service_account
    assert user.dept_id is None
    assert isinstance(user, auth.Identity)


def test_dev_personal_token_login_is_human_and_may_have_dept():
    """PAT `login` 时 `bisheng dev` 注入的是自然人身份——SDK 原样透传、不推导。"""
    with auth.bind(hosted_headers(user_id="9002", subject_kind="human", dept=True)):
        user = auth.current_user()
    assert user.subject_kind == "human"
    assert user.dept_id == "7"


@pytest.mark.parametrize(
    "headers",
    [
        None,
        [],
        [("X-BiSheng-Tenant-Id", "1"), ("X-BiSheng-App-Id", "app-1")],
    ],
)
def test_no_identity_raises_and_never_returns_none(headers):
    if headers is None:
        with pytest.raises(PlatformIdentityMissingError):
            auth.current_user()
        return
    with auth.bind(headers):
        with pytest.raises(PlatformIdentityMissingError):
            auth.current_user()


def test_identity_has_no_token_field_and_repr_hides_it():
    with auth.bind(hosted_headers()):
        user = auth.current_user()
    assert not hasattr(user, "access_token")
    assert "access_token" not in set(user.__dataclass_fields__)
    assert FAKE_OBO not in repr(user)


def test_no_as_user_or_login_or_verify_api():
    forbidden = {"as_user", "login", "logout", "verify", "verify_token", "impersonate", "sign", "issue"}
    assert forbidden.isdisjoint(set(dir(auth)))


@pytest.mark.parametrize(
    "name",
    ["X-BiSheng-User-Id", "x-bisheng-user-id", "X_BiSheng_User_Id", "HTTP_X_BISHENG_USER_ID"],
)
def test_header_name_normalisation(name: str):
    with auth.bind([(name, "42")]):
        assert auth.current_user().user_id == "42"


def test_ids_are_strings_not_ints():
    with auth.bind(hosted_headers()):
        user = auth.current_user()
    # dev 期的 user_id 是服务账号 id，与平台 user 表不是一张表——当 int 用会 join 到错的人。
    assert isinstance(user.user_id, str)
    assert isinstance(user.tenant_id, str)


def test_from_headers_is_pure_and_does_not_touch_context():
    user = auth.from_headers(hosted_headers())
    assert user.user_id == "42"
    with pytest.raises(PlatformIdentityMissingError):
        auth.current_user()


def test_bind_is_scoped_to_the_with_block():
    with auth.bind(hosted_headers()):
        assert auth.current_user().user_id == "42"
    with pytest.raises(PlatformIdentityMissingError):
        auth.current_user()


# --- ASGI / WSGI 接法 -----------------------------------------------------


def _asgi_scope(headers: list[tuple[str, str]], scope_type: str = "http") -> dict:
    return {
        "type": scope_type,
        "headers": [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers],
    }


async def test_asgi_middleware_sets_and_resets_per_request():
    seen: list[str] = []

    async def app(scope, receive, send):
        seen.append(auth.current_user().user_id)

    middleware = auth.ASGIMiddleware(app)
    await middleware(_asgi_scope(hosted_headers(user_id="1")), None, None)
    await middleware(_asgi_scope(hosted_headers(user_id="2")), None, None)
    assert seen == ["1", "2"]
    with pytest.raises(PlatformIdentityMissingError):
        auth.current_user()


async def test_asgi_middleware_passes_headerless_request_through():
    """探活请求照常进入应用；只有真的调 `current_user()` 才抛（AC-07 的落点）。"""
    reached = []

    async def app(scope, receive, send):
        reached.append(True)

    await auth.ASGIMiddleware(app)({"type": "http", "headers": []}, None, None)
    assert reached == [True]


async def test_asgi_middleware_handles_websocket_handshake_scope():
    seen: list[str] = []

    async def app(scope, receive, send):
        seen.append(auth.current_user().user_id)

    await auth.ASGIMiddleware(app)(_asgi_scope(hosted_headers(), "websocket"), None, None)
    assert seen == ["42"]


async def test_asgi_middleware_passes_lifespan_through_untouched():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    await auth.ASGIMiddleware(app)({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]


def test_middleware_is_not_a_starlette_basehttpmiddleware():
    """纯 ASGI 可调用：`BaseHTTPMiddleware` 会让 ContextVar 的 reset 跨任务抛错（坑 14）。"""
    bases = {base.__name__ for base in auth.ASGIMiddleware.__mro__}
    assert "BaseHTTPMiddleware" not in bases
    assert {"scope", "receive", "send"}.issubset(auth.ASGIMiddleware.__call__.__code__.co_varnames)


def test_wsgi_middleware_reads_http_x_bisheng_environ():
    seen: list[str] = []

    def app(environ, start_response):
        seen.append(auth.current_user().user_name)
        return [b"ok"]

    environ = {"HTTP_X_BISHENG_USER_ID": "42", "HTTP_X_BISHENG_USER_NAME": "%E5%BC%A0%E4%B8%89", "PATH_INFO": "/"}
    body = auth.WSGIMiddleware(app)(environ, lambda *args: None)
    assert seen == ["张三"]
    assert list(body) == [b"ok"]
    body.close()
    with pytest.raises(PlatformIdentityMissingError):
        auth.current_user()


def test_wsgi_middleware_keeps_the_identity_until_the_body_is_consumed():
    """流式响应的业务代码在视图返回之后才跑——那时 `current_user()` 仍要拿得到身份。"""
    seen: list[str] = []

    def app(environ, start_response):
        def stream():
            seen.append(auth.current_user().user_id)
            yield b"chunk"

        return stream()

    body = auth.WSGIMiddleware(app)({"HTTP_X_BISHENG_USER_ID": "42"}, lambda *args: None)
    assert list(body) == [b"chunk"]
    assert seen == ["42"]
    body.close()
