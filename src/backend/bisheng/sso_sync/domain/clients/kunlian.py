"""昆联全租户只读目录客户端。与 OIDC 凭据及浏览器 Cookie 隔离。"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from bisheng.common.errcode.sso_sync import KunlianDirectorySyncError
from bisheng.core.config.sso_sync import KunlianConf

LIST_PATH = "/api/v1/integrations/user-sync/users"
DETAIL_PATH = "/api/v1/integrations/user-sync/tenants/{tenant_id}/users/{id}"
ERROR_CODES = {
    "INVALID_ARGUMENT",
    "UNAUTHENTICATED",
    "PERMISSION_DENIED",
    "NOT_FOUND",
    "SERVICE_OVERLOADED",
    "UNAVAILABLE",
    "DEADLINE_EXCEEDED",
    "INTERNAL_ERROR",
}


class _ResponseTooLarge(ValueError):
    pass


async def _send_bounded(client, request, *, max_bytes):
    """在读取阶段限制解码后的载荷。失败或超时也释放连接。"""
    response = await client.send(request, stream=True)
    try:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > max_bytes:
                raise _ResponseTooLarge("RESPONSE_TOO_LARGE")
            body.extend(chunk)
        return response, bytes(body)
    finally:
        await response.aclose()


class DirectoryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class DirectoryTenant(DirectoryContract):
    id: str = Field(min_length=1, max_length=64)
    code: str
    name: str
    status: str = Field(min_length=1, max_length=32)
    version: str = Field(max_length=256)


class DirectoryRole(DirectoryContract):
    id: str = Field(min_length=1, max_length=64)
    code: str
    name: str
    status: Literal["ACTIVE", "DISABLED"]


class DirectoryDisplayReference(DirectoryContract):
    """组织和岗位的展示摘要。不作为身份或权限事实投影。"""

    id: str = Field(min_length=1, max_length=64)
    name: str


class DirectoryUser(DirectoryContract):
    id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    member_no: str | None
    display_name: str
    login_name: None
    status: Literal["INVITED", "ACTIVE", "DISABLED", "LEFT"]
    deleted: bool
    version: str = Field(max_length=256)
    authz_version: str = Field(max_length=256)
    organization_ids: list[str]
    position_ids: list[str]
    role_ids: list[str]
    roles: list[DirectoryRole]
    extends: list = Field(max_length=0)
    tenant: DirectoryTenant
    organizations: list[DirectoryDisplayReference] = Field(default_factory=list, exclude=True, repr=False)
    positions: list[DirectoryDisplayReference] = Field(default_factory=list, exclude=True, repr=False)

    def staged_tenant(self) -> dict:
        return {
            "external_tenant_id": self.tenant_id,
            "status": self.tenant.status,
            "version": self.tenant.version,
            "summary": self.tenant.model_dump(),
        }

    def staged_member(self) -> dict:
        return {
            "external_tenant_id": self.tenant_id,
            "member_id": self.id,
            "subject": self.subject,
            "status": self.status,
            "deleted": self.deleted,
            "member_version": self.version,
            "authorization_version": self.authz_version,
            "summary": self.model_dump(
                exclude={"tenant", "id", "subject", "tenant_id", "status", "deleted", "version", "authz_version"}
            ),
        }


@dataclass(frozen=True)
class DirectoryPage:
    items: tuple[DirectoryUser, ...] = field(repr=False)
    next_page_token: str = field(repr=False)
    request_id: str | None = None


class KunlianDirectoryRequestError(KunlianDirectorySyncError):
    """可分类的稳定失败。公开响应沿用 19325。不保留上游报文。"""

    def __init__(self, status: int, code: str, request_id: str | None = None):
        super().__init__()
        self.upstream_status = status
        self.upstream_code = code
        self.request_id = request_id
        self.retryable = status in (429, 500, 503, 504)


class KunlianDirectoryClient:
    def __init__(self, config: KunlianConf, *, api_key: SecretStr, transport=None):
        origin = urlsplit(config.issuer)
        if (
            not origin.hostname
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path not in ("", "/")
            or not api_key.get_secret_value()
            or (
                origin.scheme != "https"
                and not (origin.scheme == "http" and f"http://{origin.netloc}" in config.approved_test_origins)
            )
        ):
            raise KunlianDirectoryRequestError(0, "REGISTRATION_INVALID")
        self._base = config.issuer.rstrip("/")
        if any(self._base + path not in config.endpoint_allowlist for path in (LIST_PATH, DETAIL_PATH)):
            raise KunlianDirectoryRequestError(0, "ENDPOINT_NOT_ALLOWED")
        self._api_key = api_key
        self._page_size = config.page_size
        self._retry_budget = config.get_retry_budget
        self._total_timeout = config.sync_timeout_seconds
        self._client = httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            auth=None,
            timeout=min(30.0, config.sync_timeout_seconds),
            limits=httpx.Limits(
                max_connections=config.http_pool_limit, max_keepalive_connections=config.http_pool_limit
            ),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    @staticmethod
    def _request_id(value) -> str | None:
        return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) else None

    async def _get(self, path: str, *, params=None):
        try:
            async with asyncio.timeout(self._total_timeout):
                for attempt in range(self._retry_budget + 1):
                    try:
                        request = self._client.build_request(
                            "GET",
                            self._base + path,
                            params=params,
                            headers={"X-API-Key": self._api_key.get_secret_value(), "Accept": "application/json"},
                        )
                        # 即使上游尝试设置 Cookie。后续分页也不得携带它。
                        request.headers.pop("cookie", None)
                        response, content = await _send_bounded(self._client, request, max_bytes=4 * 1024 * 1024)
                    except _ResponseTooLarge:
                        raise KunlianDirectoryRequestError(0, "PROTOCOL_ERROR") from None
                    except httpx.TransportError:
                        error = KunlianDirectoryRequestError(503, "UNAVAILABLE")
                    else:
                        try:
                            body = json.loads(content)
                        except ValueError:
                            body = None
                        request_id = self._request_id(response.headers.get("X-Request-Id"))
                        if isinstance(body, dict):
                            request_id = self._request_id(body.get("request_id")) or request_id
                        if response.status_code == 200 and isinstance(body, dict) and body.get("code") == "OK":
                            return body.get("data"), request_id
                        code = body.get("code") if isinstance(body, dict) else None
                        error = KunlianDirectoryRequestError(
                            response.status_code,
                            code if isinstance(code, str) and code in ERROR_CODES else "PROTOCOL_ERROR",
                            request_id,
                        )
                    if not error.retryable or attempt == self._retry_budget:
                        raise error
                    await asyncio.sleep(min(0.1 * (2**attempt), 2.0))
        except TimeoutError:
            raise KunlianDirectoryRequestError(504, "DEADLINE_EXCEEDED") from None

    @staticmethod
    def _user(value) -> DirectoryUser:
        try:
            user = DirectoryUser.model_validate(value)
        except ValidationError:
            raise KunlianDirectoryRequestError(200, "INVALID_DIRECTORY") from None
        if user.tenant_id != user.tenant.id:
            raise KunlianDirectoryRequestError(200, "TENANT_MISMATCH")
        return user

    async def list_users(self, *, page_token: str | None = None) -> DirectoryPage:
        if page_token is not None and (not isinstance(page_token, str) or not 1 <= len(page_token) <= 1024):
            raise KunlianDirectoryRequestError(400, "INVALID_ARGUMENT")
        params = {"page_size": self._page_size}
        if page_token is not None:
            params["page_token"] = page_token
        data, request_id = await self._get(LIST_PATH, params=params)
        if (
            not isinstance(data, dict)
            or set(data) != {"items", "next_page_token"}
            or not isinstance(data["items"], list)
            or len(data["items"]) > self._page_size
            or not isinstance(data["next_page_token"], str)
            or len(data["next_page_token"]) > 1024
        ):
            raise KunlianDirectoryRequestError(200, "INVALID_DIRECTORY", request_id)
        return DirectoryPage(tuple(self._user(value) for value in data["items"]), data["next_page_token"], request_id)

    async def get_user(self, tenant_id: str, member_id: str) -> DirectoryUser:
        if any(
            not isinstance(value, str) or not value or len(value) > 64 or value in (".", "..")
            for value in (tenant_id, member_id)
        ):
            raise KunlianDirectoryRequestError(400, "INVALID_ARGUMENT")
        path = DETAIL_PATH.format(tenant_id=quote(tenant_id, safe=""), id=quote(member_id, safe=""))
        data, _ = await self._get(path)
        user = self._user(data)
        if user.tenant_id != tenant_id or user.id != member_id:
            raise KunlianDirectoryRequestError(200, "IDENTITY_MISMATCH")
        return user


@dataclass(frozen=True)
class KunlianTokenBinding:
    """已验签的登录上下文。不包含外部令牌或目录推导字段。"""

    issuer: str
    client_id: str
    subject: str
    tenant_id: str
    workspace_id: str
    sid: str


@dataclass(frozen=True)
class KunlianTokenIdentity(KunlianTokenBinding):
    auth_time: int
    expires_at: int


@dataclass(frozen=True)
class KunlianActiveToken:
    expires_at: int


class KunlianOidcClient:
    """独立认证 HTTP 客户端。公钥有限缓存。每次内省均实际请求。"""

    def __init__(self, config: KunlianConf, *, client_secret: SecretStr, transport=None, clock=None):
        import time
        from base64 import b64encode
        from urllib.parse import quote_plus

        from bisheng.common.errcode.sso_sync import KunlianLoginInvalidError
        from bisheng.core.config.kunlian_scope import resolve_scope_pairs

        self._config = config.model_copy(deep=True)
        try:
            scope_valid = bool(
                resolve_scope_pairs(
                    config.login_scope_mode,
                    config.allowed_tenant_id,
                    config.allowed_workspace_ids,
                    config.tenant_workspace_allowlist,
                )
            )
        except ValueError:
            scope_valid = False
        origin = urlsplit(config.issuer)
        if (
            not origin.hostname
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path not in ("", "/")
            or config.issuer.endswith("/")
            or not config.client_id
            or not client_secret.get_secret_value()
            or not scope_valid
            or (
                origin.scheme != "https"
                and not (origin.scheme == "http" and f"http://{origin.netloc}" in config.approved_test_origins)
            )
        ):
            raise KunlianLoginInvalidError()
        self._urls = {
            "discovery": config.issuer + "/.well-known/openid-configuration",
            "jwks": config.issuer + "/oidc/jwks",
            "introspect": config.issuer + "/oidc/introspect",
        }
        if any(url not in config.endpoint_allowlist for url in self._urls.values()):
            raise KunlianLoginInvalidError()
        basic = quote_plus(config.client_id) + ":" + quote_plus(client_secret.get_secret_value())
        self._basic = SecretStr("Basic " + b64encode(basic.encode()).decode("ascii"))
        self._clock = clock or time.time
        self._keys = {}
        self._keys_expire_at = 0
        self._unknown_refresh_at = float("-inf")
        self._key_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            auth=None,
            timeout=config.introspection_timeout_seconds,
            limits=httpx.Limits(
                max_connections=config.http_pool_limit, max_keepalive_connections=config.http_pool_limit
            ),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    async def _json(self, name, *, token=None):
        from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = self._basic.get_secret_value()
        request = self._client.build_request(
            "POST" if token is not None else "GET",
            self._urls[name],
            headers=headers,
            data={"token": token.get_secret_value()} if token is not None else None,
        )
        request.headers.pop("cookie", None)
        try:
            # 包括连接池等待和响应读取。不重试 POST。认证故障不能切换其他端点。
            async with asyncio.timeout(self._config.introspection_timeout_seconds):
                response, content = await _send_bounded(self._client, request, max_bytes=1024 * 1024)
            if response.status_code != 200:
                raise KunlianDependencyUnavailableError()
            body = json.loads(content)
            if not isinstance(body, dict):
                raise KunlianDependencyUnavailableError()
            return body
        except (httpx.TransportError, TimeoutError, ValueError):
            raise KunlianDependencyUnavailableError() from None

    async def _refresh_keys(self):
        import jwt

        from bisheng.common.errcode.sso_sync import KunlianLoginInvalidError

        discovery = await self._json("discovery")
        if (
            discovery.get("issuer") != self._config.issuer
            or discovery.get("jwks_uri") != self._urls["jwks"]
            or discovery.get("introspection_endpoint") != self._urls["introspect"]
        ):
            raise KunlianLoginInvalidError()
        jwks = await self._json("jwks")
        rows = jwks.get("keys")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
            raise KunlianLoginInvalidError()
        keys = {}
        for row in rows:
            if not isinstance(row, dict):
                raise KunlianLoginInvalidError()
            if row.get("kty") != "RSA" or row.get("use", "sig") != "sig" or row.get("alg", "RS256") != "RS256":
                continue
            kid = row.get("kid")
            if (
                not isinstance(kid, str)
                or not 1 <= len(kid) <= 128
                or kid in keys
                or any(name in row for name in ("d", "p", "q", "dp", "dq", "qi", "oth"))
                or ("key_ops" in row and row["key_ops"] != ["verify"])
            ):
                raise KunlianLoginInvalidError()
            try:
                key = jwt.PyJWK.from_dict(row, algorithm="RS256").key
                if key.key_size < 2048:
                    raise ValueError("Unsupported key size")
            except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError):
                raise KunlianLoginInvalidError() from None
            keys[kid] = key
        if not keys:
            raise KunlianLoginInvalidError()
        self._keys = keys
        self._keys_expire_at = self._clock() + 300

    async def _key(self, kid):
        from bisheng.common.errcode.sso_sync import KunlianLoginInvalidError

        async with self._key_lock:
            if self._clock() >= self._keys_expire_at:
                await self._refresh_keys()
            elif kid not in self._keys and self._clock() - self._unknown_refresh_at >= 30:
                # 每个客户端最多每 30 秒一次未知 kid 刷新。并发请求共用这一预算。
                self._unknown_refresh_at = self._clock()
                await self._refresh_keys()
            if kid not in self._keys:
                raise KunlianLoginInvalidError()
            return self._keys[kid]

    async def verify_id_token(self, token: SecretStr, *, expected_nonce: str) -> KunlianTokenIdentity:
        from hmac import compare_digest

        import jwt

        from bisheng.common.errcode.sso_sync import KunlianLoginInvalidError

        try:
            raw = token.get_secret_value()
            if not raw or len(raw) > 32768 or not isinstance(expected_nonce, str) or not expected_nonce:
                raise ValueError("Invalid token")
            header = jwt.get_unverified_header(raw)
            if (
                header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 128
                or any(name in header for name in ("jku", "x5u", "jwk", "crit"))
                or header.get("typ", "JWT") != "JWT"
            ):
                raise ValueError("Unsupported JOSE header")
            key = await self._key(header["kid"])
            claims = jwt.decode(
                raw,
                key,
                algorithms=["RS256"],
                audience=self._config.client_id,
                issuer=self._config.issuer,
                options={
                    "require": [
                        "iss",
                        "sub",
                        "aud",
                        "iat",
                        "nbf",
                        "exp",
                        "nonce",
                        "sid",
                        "auth_time",
                        "tenant_id",
                        "workspace_id",
                    ],
                    "verify_iat": False,
                    "verify_nbf": False,
                    "verify_exp": False,
                },
            )
            if any(type(claims[name]) is not int or claims[name] < 0 for name in ("iat", "nbf", "exp", "auth_time")):
                raise ValueError("Invalid timestamps")
            now = self._clock()
            if (
                claims["exp"] <= now
                or claims["exp"] <= claims["iat"]
                or claims["nbf"] > now + 30
                or claims["iat"] > now + 30
                or claims["auth_time"] > claims["iat"] + 30
            ):
                raise ValueError("Invalid time window")
            audience = claims["aud"]
            if ((isinstance(audience, list) and len(audience) > 1) or "azp" in claims) and claims.get(
                "azp"
            ) != self._config.client_id:
                raise ValueError("Invalid authorized party")
            if (
                not isinstance(claims["nonce"], str)
                or not compare_digest(claims["nonce"].encode(), expected_nonce.encode())
                or not self._config.allows_scope(claims["tenant_id"], claims["workspace_id"])
                or any(
                    not isinstance(claims[name], str) or not 1 <= len(claims[name]) <= size
                    for name, size in (("sub", 128), ("sid", 256), ("workspace_id", 128))
                )
            ):
                raise ValueError("Identity mismatch")
            return KunlianTokenIdentity(
                self._config.issuer,
                self._config.client_id,
                claims["sub"],
                claims["tenant_id"],
                claims["workspace_id"],
                claims["sid"],
                claims["auth_time"],
                claims["exp"],
            )
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise KunlianLoginInvalidError() from None

    async def introspect(self, token: SecretStr, *, expected: KunlianTokenBinding) -> KunlianActiveToken:
        from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError, KunlianSessionExpiredError

        if not token.get_secret_value() or len(token.get_secret_value()) > 32768:
            raise KunlianIdentityUnavailableError()
        body = await self._json("introspect", token=token)
        if body.get("active") is False:
            raise KunlianSessionExpiredError()
        comparisons = {
            "client_id": expected.client_id,
            "iss": expected.issuer,
            "sub": expected.subject,
            "tenant_id": expected.tenant_id,
            "workspace_id": expected.workspace_id,
            "sid": expected.sid,
            "token_type": "Bearer",
        }
        if (
            body.get("active") is not True
            or expected.client_id != self._config.client_id
            or expected.issuer != self._config.issuer
            or not self._config.allows_scope(expected.tenant_id, expected.workspace_id)
            or any(body.get(name) != value for name, value in comparisons.items())
            or type(body.get("exp")) is not int
        ):
            raise KunlianIdentityUnavailableError()
        if body["exp"] <= self._clock():
            raise KunlianSessionExpiredError()
        return KunlianActiveToken(body["exp"])
