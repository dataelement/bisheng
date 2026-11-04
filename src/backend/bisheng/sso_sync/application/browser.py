"""浏览器入口适配。验证结果只存当前 HTTP 请求。不缓存跨动作的允许结果。"""

import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from http.cookies import CookieError, SimpleCookie
from uuid import uuid4

import jwt
from loguru import logger
from pydantic import SecretStr, TypeAdapter, ValidationError

from bisheng.common.errcode.sso_sync import (
    KunlianDependencyUnavailableError,
    KunlianError,
    KunlianSessionExpiredError,
    KunlianTrustRejectedError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.sso_sync.domain.schemas.kunlian import KunlianActionContext

COOKIE_NAME = "access_token_cookie"
_STATE_KEY = "kunlian_verified_http"
_PROTOCOL_STATE_KEY = "kunlian_local_protocol"
_LEGACY_USER_ID = TypeAdapter(int)


@dataclass(frozen=True)
class RequestAdmission:
    cookie_digest: str = field(repr=False)
    operator: object = field(repr=False)


@dataclass(frozen=True)
class KunlianProtocolAdmission:
    reference: SecretStr = field(repr=False)
    cookie_digest: str = field(repr=False)
    browser_binding_hash: str = field(repr=False)


def _protocol_route(connection):
    return (connection.method, connection.url.path) in {
        ("GET", "/api/v1/identity-integrations/kunlian/session/csrf"),
        ("POST", "/api/v1/user/logout"),
    }


def _cookie_values(connection) -> list[str]:
    # 不用 SimpleCookie 的最后值覆盖行为。重复 Cookie 即使相同也视为歧义。
    values = []
    for line in connection.headers.getlist("cookie"):
        for pair in line.split(";"):
            name, separator, value = pair.strip().partition("=")
            if name == COOKIE_NAME and separator:
                parsed = SimpleCookie()
                try:
                    parsed.load(pair.strip())
                    values.append(parsed[name].value if name in parsed else value.strip())
                except CookieError:
                    values.append(value.strip())
    return values


class KunlianBrowserApplication:
    def __init__(self, *, config, repository, user_owner, sessions, protocol=None):
        self.config = config
        self.repository = repository
        self.user_owner = user_owner
        self.sessions = sessions
        self.protocol = protocol

    def _hint(self, raw: str) -> bool:
        from bisheng.user.domain.services.auth import is_kunlian_subject

        try:
            payload = jwt.decode(raw, options={"verify_signature": False})
            subject = payload.get("sub")
            if isinstance(subject, str):
                import json

                subject = json.loads(subject)
            return is_kunlian_subject(subject) or bool(self.config.issuer and payload.get("iss") == self.config.issuer)
        except (jwt.PyJWTError, ValueError, TypeError):
            return False

    async def _is_candidate(self, connection, auth_jwt, *, websocket=False) -> bool:
        from bisheng.user.domain.services.auth import is_kunlian_subject

        candidates = _cookie_values(connection)
        if (
            connection.headers.get("x-auth-source", "").strip().casefold() == "kunlian"
            or "x-kunlian-session" in connection.headers
        ):
            return True
        for line in connection.headers.getlist("authorization"):
            line = line.strip()
            if line.lower().startswith("bearer "):
                candidates.append(line[7:].strip())
        if websocket:
            candidates.extend(connection.query_params.getlist("t"))
        for raw in candidates:
            if self._hint(raw):
                return True
            try:
                subject = auth_jwt.decode_jwt_token(raw)
            except Exception:
                # 只用于分流。非昆联无效令牌仍交原认证路径拒绝。
                continue
            if is_kunlian_subject(subject):
                return True
            try:
                user_id = _LEGACY_USER_ID.validate_python(subject.get("user_id") if isinstance(subject, dict) else None)
            except ValidationError:
                continue
            # 只按旧依赖能解析的 ID 查来源。绝不据此构造主体。昆联仍须完整严格字段。
            if 0 < user_id <= 9223372036854775807:
                with tenant_execution_scope(1):
                    if await self.user_owner.is_reserved_external_account(
                        user_id
                    ) or await self.repository.has_local_user_binding(user_id):
                        return True
        return False

    def _strict_cookie(self, connection, auth_jwt, *, websocket=False):
        from bisheng.user.domain.services.auth import validate_kunlian_subject

        values = _cookie_values(connection)
        if (
            len(values) != 1
            or not values[0]
            or connection.headers.getlist("authorization")
            or (websocket and "t" in connection.query_params)
            or any(
                name in {"x-user-id", "x-external-id", "x-auth-source", "x-kunlian-session"}
                for name in connection.headers
            )
        ):
            raise KunlianTrustRejectedError()
        try:
            subject = auth_jwt.decode_jwt_token(values[0])
        except Exception as error:
            if isinstance(error.__context__, jwt.ExpiredSignatureError):
                raise KunlianSessionExpiredError() from None
            raise KunlianTrustRejectedError() from None
        validate_kunlian_subject(subject)
        return values[0], subject

    def _origin(self, connection, *, required: bool):
        values = connection.headers.getlist("origin")
        if not values and not required:
            return
        if len(values) != 1 or not self.config.public_origin or values[0] != self.config.public_origin:
            raise KunlianTrustRejectedError()

    async def _admit(self, connection, auth_jwt, *, websocket=False, reuse=False):
        if not await self._is_candidate(connection, auth_jwt, websocket=websocket):
            return None
        if not websocket and _protocol_route(connection):
            # 本地退出协议不能被 UserPayload 依赖误用为业务准入。
            raise KunlianTrustRejectedError()
        raw, subject = self._strict_cookie(connection, auth_jwt, websocket=websocket)
        digest = sha256(raw.encode()).hexdigest()
        cached = connection.scope.get("state", {}).get(_STATE_KEY) if reuse else None
        if isinstance(cached, RequestAdmission) and cached.cookie_digest == digest:
            return cached.operator
        write = not websocket and connection.method not in {"GET", "HEAD", "OPTIONS"}
        self._origin(connection, required=websocket or write)
        if self.sessions is None:
            raise KunlianDependencyUnavailableError()
        if write:
            csrf = connection.headers.getlist("x-csrf-token")
            if len(csrf) != 1 or re.fullmatch(r"[0-9a-f]{64}", csrf[0]) is None:
                raise KunlianTrustRejectedError()
            await self.sessions.verify_csrf(subject["kunlian_session"], csrf[0], origin=self.config.public_origin)
        action = KunlianActionContext(
            transport="WEBSOCKET" if websocket else "HTTP",
            action="browser.message" if websocket else "browser.request",
            request_id=str(uuid4()),
        )
        operator = await self.sessions.admit_kunlian_session(subject["kunlian_session"], action)
        if any(getattr(operator, key, None) != subject[key] for key in ("user_id", "tenant_id", "token_version")):
            await self.sessions.revoke_session(subject["kunlian_session"], "IDENTITY_CHANGED")
            raise KunlianSessionExpiredError()
        if reuse:
            connection.scope.setdefault("state", {})[_STATE_KEY] = RequestAdmission(digest, operator)
        return operator

    async def admit_protocol(self, request, auth_jwt):
        if not _protocol_route(request) or not await self._is_candidate(request, auth_jwt):
            return None
        raw, subject = self._strict_cookie(request, auth_jwt)
        if request.scope.get("raw_path") != request.url.path.encode("ascii") or request.url.query:
            raise KunlianTrustRejectedError()
        self._origin(request, required=request.method == "POST")
        digest = sha256(raw.encode()).hexdigest()
        cached = request.scope.get("state", {}).get(_PROTOCOL_STATE_KEY)
        if isinstance(cached, KunlianProtocolAdmission) and cached.cookie_digest == digest:
            return cached
        values = []
        for line in request.headers.getlist("cookie"):
            for pair in line.split(";"):
                name, separator, value = pair.strip().partition("=")
                if name == "kunlian_browser_binding" and separator:
                    values.append(value)
        if len(values) != 1 or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", values[0]) is None:
            raise KunlianTrustRejectedError()
        if self.protocol is None:
            raise KunlianDependencyUnavailableError()
        binding_hash = sha256(values[0].encode()).hexdigest()
        await self.protocol.validate_local_subject(subject["kunlian_session"], subject, binding_hash)
        admission = KunlianProtocolAdmission(SecretStr(subject["kunlian_session"]), digest, binding_hash)
        request.scope.setdefault("state", {})[_PROTOCOL_STATE_KEY] = admission
        return admission

    async def admit_http(self, request, auth_jwt):
        return await self._safe_admit(request, auth_jwt, reuse=True)

    async def admit_websocket(self, websocket, auth_jwt):
        return await self._safe_admit(websocket, auth_jwt, websocket=True)

    async def _safe_admit(self, connection, auth_jwt, **kwargs):
        try:
            return await self._admit(connection, auth_jwt, **kwargs)
        except KunlianError:
            raise
        except Exception:
            logger.error("Kunlian browser admission rejected: DEPENDENCY_UNAVAILABLE")
            raise KunlianDependencyUnavailableError() from None


async def get_browser_application(connection):
    application = getattr(connection.app.state, "kunlian_browser_application", None)
    if application is not None:
        return application
    from bisheng.sso_sync.application.runtime import get_runtime_provider

    return await get_runtime_provider(connection.app).browser_application()


async def resolve_browser_identity(connection, auth_jwt=None, *, websocket=False):
    # 匿名请求不解析秘密或访问目录表。其他凭据通道由调用入口先分流。
    if (
        not any(_cookie_values(connection))
        and not connection.headers.get("authorization")
        and not (websocket and "t" in connection.query_params)
    ):
        return None
    from bisheng.user.domain.services.auth import AuthJwt

    try:
        application = await get_browser_application(connection)
        auth_jwt = auth_jwt or AuthJwt(req=None if websocket else connection)
        return await (
            application.admit_websocket(connection, auth_jwt)
            if websocket
            else application.admit_http(connection, auth_jwt)
        )
    except KunlianError:
        raise
    except Exception:
        logger.error("Kunlian browser runtime unavailable")
        raise KunlianDependencyUnavailableError() from None


async def resolve_browser_protocol(request, auth_jwt=None):
    if not _protocol_route(request) or (not any(_cookie_values(request)) and not request.headers.get("authorization")):
        return None
    from bisheng.user.domain.services.auth import AuthJwt

    try:
        application = await get_browser_application(request)
        return await application.admit_protocol(request, auth_jwt or AuthJwt(req=request))
    except KunlianError:
        raise
    except Exception:
        logger.error("Kunlian local protocol runtime unavailable")
        raise KunlianDependencyUnavailableError() from None


@asynccontextmanager
async def admitted_request_scope(operator):
    # 只有已验证的操作主体能设置业务租户。退出时恢复原环境。
    from bisheng.core.context.tenant import set_visible_tenant_ids

    with tenant_execution_scope(operator.tenant_id):
        set_visible_tenant_ids(
            None if getattr(operator, "is_global_super", False) else frozenset({1, operator.tenant_id})
        )
        yield


@asynccontextmanager
async def browser_entry_scope(operator):
    if getattr(operator, "auth_source", None) == "kunlian":
        async with admitted_request_scope(operator):
            yield
    else:
        yield


def websocket_message_admission(websocket, initial_user):
    if getattr(initial_user, "auth_source", None) != "kunlian":
        return None
    initial = getattr(initial_user, "_runtime_credential_reference", None)
    if not isinstance(initial, dict) or initial.get("kind") != "kunlian_session":
        raise KunlianTrustRejectedError()
    frozen_reference = initial.get("reference")

    @asynccontextmanager
    async def admit():
        from bisheng.common.chat.client import ChatMessageExecution

        current = await resolve_browser_identity(websocket, websocket=True)
        runtime = getattr(current, "_runtime_credential_reference", None)
        if (
            current is None
            or not isinstance(runtime, dict)
            or (
                runtime.get("reference") != frozen_reference
                or current.user_id != initial_user.user_id
                or current.tenant_id != initial_user.tenant_id
            )
        ):
            raise KunlianTrustRejectedError()
        causal = {
            "kind": "kunlian_causal",
            "user_id": current.user_id,
            "tenant_id": current.tenant_id,
            "binding_id": runtime["binding_id"],
            "session_hash": runtime["session_hash"],
            "request_id": str(uuid4()),
        }
        async with admitted_request_scope(current):
            yield ChatMessageExecution(operator=current, execution_snapshot=None, causal_context=causal)

    return admit
