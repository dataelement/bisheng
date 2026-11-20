"""昆联平台资源网关共享 HTTP 原语（Token Exchange、统一资源列表、固定版本详情与错误上下文提取）。"""

from __future__ import annotations

import asyncio
import json
from base64 import b64encode
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit
from uuid import uuid4

import httpx
from loguru import logger
from pydantic import SecretStr

RESOURCES_PATH = "/api/platform/v1/resources"
WORKFLOW_CALLBACK_TOKEN_PATH = "/oidc/workflow-callback/token"
OIDC_INTROSPECT_PATH = "/oidc/introspect"

TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
SCOPE_RESOURCES_READ = "platform.resources.read"
SCOPE_AGENT_INVOKE = "platform.agent.invoke"
SCOPE_KNOWLEDGE_RETRIEVE = "platform.knowledge.retrieve"


class ResponseTooLargeError(ValueError):
    """响应体超出配置上限。"""


class KunlianClientError(Exception):
    """昆联资源共享客户端异常基类，由各领域客户端映射为业务错误码。"""


class KunlianNotConfiguredError(KunlianClientError):
    """资源网关或 OIDC 配置缺失或非法。"""


class KunlianBadRequestError(KunlianClientError):
    """本地参数或上游请求参数校验失败。"""


class KunlianInvalidTokenError(KunlianClientError):
    """主体凭证或资源令牌缺失/失效。"""


class KunlianTimeoutError(KunlianClientError):
    """请求上游超时。"""


class KunlianUpstreamError(KunlianClientError):
    """传输异常、响应体过大或报文格式不符合预期。"""


class KunlianHttpStatusError(KunlianClientError):
    """上游返回非成功 HTTP 状态码或非 200 envelope status_code。"""

    def __init__(self, status_code: int, reason_code: str | None = None, trace_id: str | None = None):
        super().__init__(f"kunlian http error status={status_code} reason={reason_code}")
        self.status_code = status_code
        self.reason_code = reason_code
        self.trace_id = trace_id


@dataclass(frozen=True)
class ExchangedResourceToken:
    access_token: SecretStr
    expires_in: int
    scope: str


@dataclass(frozen=True)
class KunlianErrorContext:
    status_code: int
    reason_code: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class KunlianResourcesPage:
    raw_items: list[dict[str, Any]]
    page_size: int
    has_more: bool
    next_cursor: str | None
    trace_id: str | None = None


def sanitize_log_field(value: Any, *, max_len: int = 128) -> str:
    """过滤换行与控制字符并截断，避免伪造日志或泄露长载荷。"""
    if value is None:
        return ""
    cleaned = "".join(ch if 32 <= ord(ch) < 127 or ord(ch) > 159 else " " for ch in str(value)).strip()
    return cleaned[:max_len]


def validate_resource_origin(url: str, *, approved_test_origins: tuple[str, ...] = ()) -> str:
    """校验资源网关基地址合法性（禁止携带凭证、query、fragment）。"""
    parsed = urlsplit(url.strip())
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise KunlianNotConfiguredError()
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and f"http://{parsed.netloc}" in approved_test_origins
    ):
        if parsed.scheme != "http":
            raise KunlianNotConfiguredError()
    return url.strip().rstrip("/")


async def send_bounded(
    client: httpx.AsyncClient, request: httpx.Request, *, max_bytes: int
) -> tuple[httpx.Response, bytes]:
    """流式读取响应并限制最大字节数，防止超大载荷耗尽内存。"""
    response = await client.send(request, stream=True)
    try:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > max_bytes:
                raise ResponseTooLargeError("RESPONSE_TOO_LARGE")
            body.extend(chunk)
        return response, bytes(body)
    finally:
        await response.aclose()


def extract_error_context(
    response: httpx.Response,
    body: Any,
    *,
    request_trace_id: str | None = None,
) -> KunlianErrorContext:
    """从昆联异常响应体与响应头提取 reason_code 与 trace_id。"""
    status_code = response.status_code
    reason_code: str | None = None
    trace_id: str | None = None
    if isinstance(body, dict):
        if isinstance(body.get("status_code"), int) and status_code == 200:
            status_code = body["status_code"]
        err_data = body.get("data")
        if isinstance(err_data, dict):
            if isinstance(err_data.get("reason_code"), str) and err_data["reason_code"].strip():
                reason_code = err_data["reason_code"].strip()
            if isinstance(err_data.get("trace_id"), str) and err_data["trace_id"].strip():
                trace_id = err_data["trace_id"].strip()
        err_obj = body.get("error")
        if reason_code is None and isinstance(err_obj, dict):
            if isinstance(err_obj.get("code"), str) and err_obj["code"].strip():
                reason_code = err_obj["code"].strip()
            elif isinstance(err_obj.get("type"), str) and err_obj["type"].strip():
                reason_code = err_obj["type"].strip()
        if trace_id is None and isinstance(body.get("request_id"), str) and body["request_id"].strip():
            trace_id = body["request_id"].strip()
    if trace_id is None:
        header_trace = (
            response.headers.get("X-Trace-ID")
            or response.headers.get("x-trace-id")
            or response.headers.get("X-Request-ID")
            or response.headers.get("x-request-id")
        )
        if isinstance(header_trace, str) and header_trace.strip():
            trace_id = header_trace.strip()
    if trace_id is None and request_trace_id:
        trace_id = request_trace_id
    return KunlianErrorContext(status_code=status_code, reason_code=reason_code, trace_id=trace_id)


def build_async_client(
    *, timeout: float, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        auth=None,
        timeout=timeout,
    )


async def exchange_resource_token(
    *,
    oidc_token_url: str,
    client_id: str,
    client_secret: SecretStr,
    subject_token: SecretStr,
    audience: str,
    scope: str,
    timeout_seconds: float,
    trace_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ExchangedResourceToken:
    """使用用户 SSO Access Token 兑换短时昆联资源令牌（有效期 <= 120s，不解析为 JWT）。"""
    if not oidc_token_url.strip() or not client_id or not client_secret.get_secret_value():
        raise KunlianNotConfiguredError()
    if not subject_token.get_secret_value():
        raise KunlianInvalidTokenError()

    req_trace = trace_id or uuid4().hex
    basic_raw = f"{quote_plus(client_id)}:{quote_plus(client_secret.get_secret_value())}"
    basic_header = "Basic " + b64encode(basic_raw.encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": basic_header,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "X-Trace-ID": req_trace,
    }
    form_data = {
        "grant_type": TOKEN_EXCHANGE_GRANT,
        "subject_token": subject_token.get_secret_value(),
        "subject_token_type": ACCESS_TOKEN_TYPE,
        "audience": audience,
        "scope": scope,
    }
    try:
        async with build_async_client(timeout=timeout_seconds, transport=transport) as client:
            async with asyncio.timeout(timeout_seconds):
                request = client.build_request("POST", oidc_token_url.strip(), headers=headers, data=form_data)
                request.headers.pop("cookie", None)
                response, content = await send_bounded(client, request, max_bytes=1024 * 1024)
    except TimeoutError:
        raise KunlianTimeoutError() from None
    except (httpx.TransportError, ResponseTooLargeError):
        raise KunlianUpstreamError() from None

    try:
        body = json.loads(content)
    except ValueError:
        body = None

    if response.status_code != 200 or not isinstance(body, dict):
        ctx = extract_error_context(response, body, request_trace_id=req_trace)
        logger.warning(
            "kunlian token exchange failed status={} reason_code={} trace_id={}",
            ctx.status_code,
            sanitize_log_field(ctx.reason_code),
            sanitize_log_field(ctx.trace_id),
        )
        if response.status_code in (400, 401):
            raise KunlianInvalidTokenError()
        raise KunlianHttpStatusError(response.status_code, ctx.reason_code, ctx.trace_id)

    access_token = body.get("access_token")
    expires_in = body.get("expires_in", 120)
    if not isinstance(access_token, str) or not access_token:
        raise KunlianUpstreamError()
    if not isinstance(expires_in, int) or expires_in <= 0:
        expires_in = 120
    return ExchangedResourceToken(
        access_token=SecretStr(access_token),
        expires_in=min(expires_in, 120),
        scope=str(body.get("scope") or scope),
    )


def resolve_workflow_callback_token_url(oidc_token_url: str) -> str:
    """从 OIDC Token 地址或 Issuer 推导 /oidc/workflow-callback/token 地址。"""
    cleaned = (oidc_token_url or "").strip().rstrip("/")
    if not cleaned:
        raise KunlianNotConfiguredError()
    if cleaned.endswith(WORKFLOW_CALLBACK_TOKEN_PATH):
        return cleaned
    if cleaned.endswith("/oidc/token"):
        return cleaned[: -len("/oidc/token")] + WORKFLOW_CALLBACK_TOKEN_PATH
    if "/oidc/" in cleaned:
        return cleaned.split("/oidc/", 1)[0].rstrip("/") + WORKFLOW_CALLBACK_TOKEN_PATH
    return cleaned + WORKFLOW_CALLBACK_TOKEN_PATH


async def exchange_workflow_callback_token(
    *,
    oidc_token_url: str,
    client_id: str,
    client_secret: SecretStr,
    context_id: str,
    remote_session_id: str,
    scope: str = SCOPE_AGENT_INVOKE,
    timeout_seconds: float = 15.0,
    trace_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ExchangedResourceToken:
    """使用已确认的 Workflow Session 与 context_id 向昆联兑换回调令牌（/oidc/workflow-callback/token）。"""
    callback_url = resolve_workflow_callback_token_url(oidc_token_url)
    if not client_id or not client_secret.get_secret_value():
        raise KunlianNotConfiguredError()
    clean_ctx = (context_id or "").strip()
    clean_sess = (remote_session_id or "").strip()
    if not clean_ctx or not clean_sess:
        raise KunlianInvalidTokenError()

    req_trace = trace_id or uuid4().hex
    basic_raw = f"{quote_plus(client_id)}:{quote_plus(client_secret.get_secret_value())}"
    basic_header = "Basic " + b64encode(basic_raw.encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": basic_header,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "X-Trace-ID": req_trace,
    }
    form_data = {
        "context_id": clean_ctx,
        "remote_session_id": clean_sess,
        "scope": scope,
    }
    try:
        async with build_async_client(timeout=timeout_seconds, transport=transport) as client:
            async with asyncio.timeout(timeout_seconds):
                request = client.build_request("POST", callback_url, headers=headers, data=form_data)
                request.headers.pop("cookie", None)
                response, content = await send_bounded(client, request, max_bytes=1024 * 1024)
    except TimeoutError:
        raise KunlianTimeoutError() from None
    except (httpx.TransportError, ResponseTooLargeError):
        raise KunlianUpstreamError() from None

    try:
        body = json.loads(content)
    except ValueError:
        body = None

    if response.status_code != 200 or not isinstance(body, dict):
        ctx = extract_error_context(response, body, request_trace_id=req_trace)
        logger.warning(
            "kunlian workflow callback token exchange failed status={} reason_code={} trace_id={} session_id={}",
            ctx.status_code,
            sanitize_log_field(ctx.reason_code),
            sanitize_log_field(ctx.trace_id),
            sanitize_log_field(clean_sess),
        )
        if response.status_code in (400, 401):
            raise KunlianInvalidTokenError()
        raise KunlianHttpStatusError(response.status_code, ctx.reason_code, ctx.trace_id)

    payload = body.get("data") if isinstance(body.get("data"), dict) and "access_token" not in body else body
    access_token = payload.get("access_token") if isinstance(payload, dict) else None
    expires_in = payload.get("expires_in", 120) if isinstance(payload, dict) else 120
    if not isinstance(access_token, str) or not access_token.strip():
        raise KunlianUpstreamError()
    if not isinstance(expires_in, int) or expires_in <= 0:
        expires_in = 120
    resolved_scope = payload.get("scope") if isinstance(payload, dict) else None
    return ExchangedResourceToken(
        access_token=SecretStr(access_token.strip()),
        expires_in=min(expires_in, 120),
        scope=str(resolved_scope or scope),
    )


def resolve_oidc_introspect_url(oidc_token_url: str) -> str:
    """从 OIDC Token 地址或 Issuer 推导 /oidc/introspect 地址。"""
    cleaned = (oidc_token_url or "").strip().rstrip("/")
    if not cleaned:
        raise KunlianNotConfiguredError()
    if cleaned.endswith(OIDC_INTROSPECT_PATH):
        return cleaned
    if cleaned.endswith("/oidc/token"):
        return cleaned[: -len("/oidc/token")] + OIDC_INTROSPECT_PATH
    if "/oidc/" in cleaned:
        return cleaned.split("/oidc/", 1)[0].rstrip("/") + OIDC_INTROSPECT_PATH
    return cleaned + OIDC_INTROSPECT_PATH


@dataclass(frozen=True)
class WorkflowExecutionIntrospection:
    """昆联 POST /oidc/introspect 返回的 Workflow 执行令牌核验结果。"""

    context_id: str
    external_user_id: str
    external_tenant_id: str | None = None
    user_account: str | None = None
    workflow_id: str | None = None
    workflow_version_id: str | None = None
    scope: str = ""
    raw_claims: dict[str, Any] | None = None


async def introspect_workflow_execution_token(
    *,
    oidc_token_url: str,
    client_id: str,
    client_secret: SecretStr,
    token: str,
    expected_audience: str | None = None,
    expected_workflow_version_id: str | int | None = None,
    require_workflow_execution_grant: bool = True,
    timeout_seconds: float = 15.0,
    trace_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> WorkflowExecutionIntrospection:
    """调用昆联 POST /oidc/introspect 核验执行令牌并提取 context_id 与主体标识。"""
    introspect_url = resolve_oidc_introspect_url(oidc_token_url)
    if not client_id or not client_secret.get_secret_value():
        raise KunlianNotConfiguredError()
    clean_token = (token or "").strip()
    if not clean_token:
        raise KunlianInvalidTokenError()

    req_trace = trace_id or uuid4().hex
    basic_raw = f"{quote_plus(client_id)}:{quote_plus(client_secret.get_secret_value())}"
    basic_header = "Basic " + b64encode(basic_raw.encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": basic_header,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "X-Trace-ID": req_trace,
    }
    try:
        async with build_async_client(timeout=timeout_seconds, transport=transport) as client:
            async with asyncio.timeout(timeout_seconds):
                request = client.build_request(
                    "POST",
                    introspect_url,
                    headers=headers,
                    data={"token": clean_token},
                )
                request.headers.pop("cookie", None)
                response, content = await send_bounded(client, request, max_bytes=1024 * 1024)
    except TimeoutError:
        raise KunlianTimeoutError() from None
    except (httpx.TransportError, ResponseTooLargeError):
        raise KunlianUpstreamError() from None

    try:
        body = json.loads(content)
    except ValueError:
        body = None

    if response.status_code != 200 or not isinstance(body, dict):
        ctx = extract_error_context(response, body, request_trace_id=req_trace)
        logger.warning(
            "kunlian oidc introspect failed status={} reason_code={} trace_id={}",
            ctx.status_code,
            sanitize_log_field(ctx.reason_code),
            sanitize_log_field(ctx.trace_id),
        )
        if response.status_code in (400, 401):
            raise KunlianInvalidTokenError()
        raise KunlianHttpStatusError(response.status_code, ctx.reason_code, ctx.trace_id)

    claims = body.get("data") if isinstance(body.get("data"), dict) and "active" not in body else body
    if not isinstance(claims, dict) or claims.get("active") is not True:
        raise KunlianInvalidTokenError()

    if require_workflow_execution_grant:
        grant_kind = claims.get("grant_kind")
        if grant_kind is not None and str(grant_kind).strip() != "workflow_execution":
            raise KunlianInvalidTokenError()

    if expected_audience and expected_audience.strip():
        aud = claims.get("aud")
        if aud is not None:
            aud_values = {str(item).strip() for item in aud} if isinstance(aud, list) else {str(aud).strip()}
            if expected_audience.strip() not in aud_values:
                raise KunlianInvalidTokenError()

    claim_ver = claims.get("workflow_version_id")
    if expected_workflow_version_id is not None and claim_ver is not None:
        if str(claim_ver).strip() != str(expected_workflow_version_id).strip():
            raise KunlianInvalidTokenError()

    context_id = claims.get("context_id")
    if not isinstance(context_id, str) or not context_id.strip():
        raise KunlianInvalidTokenError()

    ext_user = None
    for key in ("sub", "external_user_id", "user_id"):
        val = claims.get(key)
        if isinstance(val, str) and val.strip():
            ext_user = val.strip()
            break
    if not ext_user:
        raise KunlianInvalidTokenError()

    ext_tenant = None
    for key in ("external_tenant_id", "tenant_id"):
        val = claims.get(key)
        if isinstance(val, str) and val.strip():
            ext_tenant = val.strip()
            break

    user_account = None
    for key in ("preferred_username", "user_account", "username"):
        val = claims.get(key)
        if isinstance(val, str) and val.strip():
            user_account = val.strip()
            break

    wf_id = claims.get("workflow_id")
    return WorkflowExecutionIntrospection(
        context_id=context_id.strip(),
        external_user_id=ext_user,
        external_tenant_id=ext_tenant,
        user_account=user_account,
        workflow_id=str(wf_id).strip() if isinstance(wf_id, str) and wf_id.strip() else None,
        workflow_version_id=str(claim_ver).strip() if claim_ver is not None else None,
        scope=str(claims.get("scope") or ""),
        raw_claims=claims,
    )


async def fetch_resources_page(
    *,
    resource_base: str,
    resource_token: SecretStr,
    resource_type: str,
    action: str | None = "use",
    type_param_name: str = "types",
    page_size: int = 20,
    search: str | None = None,
    cursor: str | None = None,
    timeout_seconds: float,
    max_payload_bytes: int,
    trace_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> KunlianResourcesPage:
    """调用 GET /api/platform/v1/resources 读取单页资源目录（兼容 status_code/data 与 code/items 两种信封）。"""
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise KunlianBadRequestError()
    param_key = "resource_type" if type_param_name == "resource_type" else "types"
    params: dict[str, Any] = {
        param_key: resource_type,
        "page_size": page_size,
    }
    if action is not None and action.strip():
        params["action"] = action.strip()
    if search is not None:
        cleaned_search = search.strip()
        if cleaned_search:
            if len(cleaned_search.encode("utf-8")) > 256:
                raise KunlianBadRequestError()
            params["search"] = cleaned_search
    if cursor is not None and cursor != "":
        if not isinstance(cursor, str) or len(cursor.encode("utf-8")) > 8192:
            raise KunlianBadRequestError()
        params["cursor"] = cursor

    req_trace = trace_id or uuid4().hex
    headers = {
        "Authorization": f"Bearer {resource_token.get_secret_value()}",
        "X-Caller-Type": "workflow",
        "X-Trace-ID": req_trace,
        "Accept": "application/json",
    }
    try:
        async with build_async_client(timeout=timeout_seconds, transport=transport) as client:
            async with asyncio.timeout(timeout_seconds):
                request = client.build_request(
                    "GET",
                    f"{resource_base}{RESOURCES_PATH}",
                    params=params,
                    headers=headers,
                )
                request.headers.pop("cookie", None)
                response, content = await send_bounded(client, request, max_bytes=max_payload_bytes)
    except TimeoutError:
        raise KunlianTimeoutError() from None
    except (httpx.TransportError, ResponseTooLargeError):
        raise KunlianUpstreamError() from None

    try:
        body = json.loads(content)
    except ValueError:
        raise KunlianUpstreamError() from None

    if not isinstance(body, dict):
        raise KunlianUpstreamError()

    status_code_field = body.get("status_code")
    code_field = body.get("code")
    envelope_failed = (
        response.status_code != 200
        or (isinstance(status_code_field, int) and status_code_field != 200)
        or (code_field is not None and code_field not in ("OK", "SUCCESS", 200, 0))
    )
    if envelope_failed:
        ctx = extract_error_context(response, body, request_trace_id=req_trace)
        logger.warning(
            "kunlian resources list failed type={} http_status={} body_status={} reason_code={} trace_id={}",
            sanitize_log_field(resource_type),
            response.status_code,
            sanitize_log_field(status_code_field if status_code_field is not None else code_field),
            sanitize_log_field(ctx.reason_code),
            sanitize_log_field(ctx.trace_id),
        )
        raise KunlianHttpStatusError(response.status_code, ctx.reason_code, ctx.trace_id)

    payload = body.get("data")
    if not isinstance(payload, dict):
        raise KunlianUpstreamError()
    raw_items = payload.get("data") if isinstance(payload.get("data"), list) else payload.get("items")
    if not isinstance(raw_items, list):
        raise KunlianUpstreamError()
    if not all(isinstance(row, dict) for row in raw_items):
        raise KunlianUpstreamError()

    next_cursor = payload.get("next_cursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise KunlianUpstreamError()
    has_more = payload.get("has_more")
    if has_more is None:
        has_more = bool(next_cursor)
    elif not isinstance(has_more, bool):
        raise KunlianUpstreamError()
    resp_page_size = payload.get("page_size", page_size)

    return KunlianResourcesPage(
        raw_items=raw_items,
        page_size=resp_page_size if isinstance(resp_page_size, int) and not isinstance(resp_page_size, bool) else page_size,
        has_more=has_more,
        next_cursor=next_cursor,
        trace_id=req_trace,
    )


async def fetch_resource_version_detail(
    *,
    resource_base: str,
    path_template: str,
    resource_token: SecretStr,
    resource_id: str,
    version_id: str,
    timeout_seconds: float,
    max_payload_bytes: int,
    trace_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """读取固定资源版本详情（兼容 Kunlian code/message/data/request_id 与标准错误 envelope）。"""
    clean_id = resource_id.strip()
    clean_ver = version_id.strip()
    if not clean_id or not clean_ver or clean_ver.lower() == "latest":
        raise KunlianBadRequestError()

    path = path_template.format(
        resource_id=quote(clean_id, safe=""),
        version_id=quote(clean_ver, safe=""),
    )
    req_trace = trace_id or uuid4().hex
    headers = {
        "Authorization": f"Bearer {resource_token.get_secret_value()}",
        "X-Trace-ID": req_trace,
        "Accept": "application/json",
    }
    try:
        async with build_async_client(timeout=timeout_seconds, transport=transport) as client:
            async with asyncio.timeout(timeout_seconds):
                request = client.build_request("GET", f"{resource_base}{path}", headers=headers)
                request.headers.pop("cookie", None)
                response, content = await send_bounded(client, request, max_bytes=max_payload_bytes)
    except TimeoutError:
        raise KunlianTimeoutError() from None
    except (httpx.TransportError, ResponseTooLargeError):
        raise KunlianUpstreamError() from None

    try:
        body = json.loads(content)
    except ValueError:
        raise KunlianUpstreamError() from None

    if response.status_code != 200 or not isinstance(body, dict):
        ctx = extract_error_context(response, body, request_trace_id=req_trace)
        logger.warning(
            "kunlian version detail failed status={} reason_code={} trace_id={}",
            response.status_code,
            sanitize_log_field(ctx.reason_code),
            sanitize_log_field(ctx.trace_id),
        )
        raise KunlianHttpStatusError(response.status_code, ctx.reason_code, ctx.trace_id)

    status_code_field = body.get("status_code")
    if isinstance(status_code_field, int) and status_code_field != 200:
        ctx = extract_error_context(response, body, request_trace_id=req_trace)
        raise KunlianHttpStatusError(status_code_field, ctx.reason_code, ctx.trace_id)

    code = body.get("code")
    if code not in (None, "OK", "SUCCESS", 200, 0):
        raise KunlianUpstreamError()
    data = body.get("data")
    if not isinstance(data, dict):
        raise KunlianUpstreamError()
    return data
