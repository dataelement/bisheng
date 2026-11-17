"""昆联平台大模型 OIDC Token Exchange、模型目录与推理 HTTP 客户端。"""

from __future__ import annotations

import asyncio
import json
from base64 import b64encode
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit
from uuid import uuid4

import httpx
from pydantic import SecretStr, ValidationError

from bisheng.common.errcode.flow import (
    PlatformLLMConfigurationError,
    PlatformLLMError,
    PlatformLLMNotReadyError,
    PlatformLLMPermissionError,
    PlatformLLMRateLimitError,
    PlatformLLMTimeoutError,
    PlatformLLMTokenError,
    PlatformLLMUpstreamError,
)
from bisheng.core.config.settings import PlatformLLMConf
from bisheng.workflow.domain.schemas.platform_llm import PlatformModelListPage, PlatformModelSummary

RESOURCES_PATH = "/api/platform/v1/resources"
MODEL_VERSION_PATH = "/api/platform/v1/resources/model/{resource_id}/versions/{version_id}"
CHAT_COMPLETIONS_PATH = "/api/platform/v1/chat/completions"

TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
SCOPE_RESOURCES_READ = "platform.resources.read"
SCOPE_MODEL_INVOKE = "platform.model.invoke"


class _ResponseTooLarge(ValueError):
    pass


async def _send_bounded(client: httpx.AsyncClient, request: httpx.Request, *, max_bytes: int) -> tuple[httpx.Response, bytes]:
    """流式读取响应并限制最大字节数，防止超大载荷耗尽内存。"""
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


def _validate_origin(url: str, *, approved_test_origins: tuple[str, ...] = ()) -> str:
    parsed = urlsplit(url.strip())
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PlatformLLMNotReadyError()
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and f"http://{parsed.netloc}" in approved_test_origins
    ):
        # 允许联调测试白名单或内网 HTTP 测试网关；若未配置白名单且为 http，仍允许显式配置的测试地址
        if parsed.scheme != "http":
            raise PlatformLLMNotReadyError()
    return url.strip().rstrip("/")


def _map_http_error(status_code: int, reason_code: str | None = None) -> PlatformLLMError:
    """按照昆联模型列表与执行契约将 HTTP 状态码与 reason_code 映射为稳定业务异常。"""
    if status_code == 400 or reason_code == "INVALID_REQUEST":
        return PlatformLLMConfigurationError()
    if status_code == 401 or reason_code == "INVALID_TOKEN":
        return PlatformLLMTokenError()
    if status_code == 403 or reason_code == "PERMISSION_DENIED":
        return PlatformLLMPermissionError()
    if status_code == 429 or reason_code == "RATE_LIMIT_EXCEEDED":
        return PlatformLLMRateLimitError()
    if status_code == 503 or reason_code == "SERVICE_UNAVAILABLE":
        return PlatformLLMNotReadyError()
    if status_code == 504 or reason_code == "EXECUTION_TIMEOUT":
        return PlatformLLMTimeoutError()
    return PlatformLLMUpstreamError()


@dataclass(frozen=True)
class ExchangedResourceToken:
    access_token: SecretStr
    expires_in: int
    scope: str


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str
    reasoning_content: str = ""
    raw_id: str = ""


class KunlianPlatformLLMClient:
    """昆联平台大模型对接客户端（Token Exchange + 资源目录 + Chat Completions）。"""

    def __init__(self, config: PlatformLLMConf, *, transport: httpx.AsyncBaseTransport | None = None):
        if not config.enabled or not config.resource_base_url.strip():
            raise PlatformLLMNotReadyError()
        self.config = config
        self._resource_base = _validate_origin(config.resource_base_url)
        self._transport = transport

    def _build_client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            trust_env=False,
            follow_redirects=False,
            auth=None,
            timeout=timeout,
        )

    async def exchange_resource_token(
        self,
        *,
        oidc_token_url: str,
        client_id: str,
        client_secret: SecretStr,
        subject_token: SecretStr,
        scope: str,
        trace_id: str | None = None,
    ) -> ExchangedResourceToken:
        """使用用户 SSO Access Token 兑换短时昆联资源令牌（有效期 <= 120s，不解析为 JWT）。"""
        if not oidc_token_url.strip() or not client_id or not client_secret.get_secret_value():
            raise PlatformLLMNotReadyError()
        if not subject_token.get_secret_value():
            raise PlatformLLMTokenError()
        basic_raw = f"{quote_plus(client_id)}:{quote_plus(client_secret.get_secret_value())}"
        basic_header = "Basic " + b64encode(basic_raw.encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": basic_header,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "X-Trace-ID": trace_id or uuid4().hex,
        }
        form_data = {
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "subject_token": subject_token.get_secret_value(),
            "subject_token_type": ACCESS_TOKEN_TYPE,
            "audience": self.config.resource_audience,
            "scope": scope,
        }
        try:
            async with self._build_client(self.config.list_timeout_seconds) as client:
                async with asyncio.timeout(self.config.list_timeout_seconds):
                    request = client.build_request("POST", oidc_token_url.strip(), headers=headers, data=form_data)
                    request.headers.pop("cookie", None)
                    response, content = await _send_bounded(client, request, max_bytes=1024 * 1024)
        except TimeoutError:
            raise PlatformLLMTimeoutError() from None
        except (httpx.TransportError, _ResponseTooLarge):
            raise PlatformLLMUpstreamError() from None

        try:
            body = json.loads(content)
        except ValueError:
            body = None

        if response.status_code != 200 or not isinstance(body, dict):
            if response.status_code in (400, 401):
                raise PlatformLLMTokenError()
            if response.status_code == 403:
                raise PlatformLLMPermissionError()
            raise _map_http_error(response.status_code)

        access_token = body.get("access_token")
        expires_in = body.get("expires_in", 120)
        if not isinstance(access_token, str) or not access_token:
            raise PlatformLLMUpstreamError()
        if not isinstance(expires_in, int) or expires_in <= 0:
            expires_in = 120
        return ExchangedResourceToken(
            access_token=SecretStr(access_token),
            expires_in=min(expires_in, 120),
            scope=str(body.get("scope") or scope),
        )

    async def list_models(
        self,
        resource_token: SecretStr,
        *,
        page_size: int = 20,
        search: str | None = None,
        cursor: str | None = None,
        trace_id: str | None = None,
    ) -> PlatformModelListPage:
        """查询当前用户有权使用的昆联授权大模型列表（types=model, action=use）。"""
        if not isinstance(page_size, int) or not 1 <= page_size <= 100:
            raise PlatformLLMConfigurationError()
        params: dict[str, Any] = {
            "types": "model",
            "action": "use",
            "page_size": page_size,
        }
        if search is not None:
            cleaned_search = search.strip()
            if cleaned_search:
                if len(cleaned_search.encode("utf-8")) > 256:
                    raise PlatformLLMConfigurationError()
                params["search"] = cleaned_search
        if cursor is not None and cursor != "":
            if not isinstance(cursor, str) or len(cursor.encode("utf-8")) > 8192:
                raise PlatformLLMConfigurationError()
            params["cursor"] = cursor

        headers = {
            "Authorization": f"Bearer {resource_token.get_secret_value()}",
            "X-Caller-Type": "workflow",
            "X-Trace-ID": trace_id or uuid4().hex,
            "Accept": "application/json",
        }
        try:
            async with self._build_client(self.config.list_timeout_seconds) as client:
                async with asyncio.timeout(self.config.list_timeout_seconds):
                    request = client.build_request(
                        "GET",
                        f"{self._resource_base}{RESOURCES_PATH}",
                        params=params,
                        headers=headers,
                    )
                    request.headers.pop("cookie", None)
                    response, content = await _send_bounded(
                        client, request, max_bytes=self.config.max_list_payload_bytes
                    )
        except TimeoutError:
            raise PlatformLLMTimeoutError() from None
        except (httpx.TransportError, _ResponseTooLarge):
            raise PlatformLLMUpstreamError() from None

        try:
            body = json.loads(content)
        except ValueError:
            raise PlatformLLMUpstreamError() from None

        if not isinstance(body, dict):
            raise PlatformLLMUpstreamError()

        if response.status_code != 200 or body.get("status_code") != 200:
            err_data = body.get("data") if isinstance(body.get("data"), dict) else {}
            reason_code = err_data.get("reason_code") if isinstance(err_data.get("reason_code"), str) else None
            raise _map_http_error(response.status_code, reason_code)

        payload = body.get("data")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise PlatformLLMUpstreamError()
        try:
            items = [PlatformModelSummary.model_validate(row) for row in payload["data"]]
        except ValidationError:
            raise PlatformLLMUpstreamError() from None

        has_more = payload.get("has_more")
        next_cursor = payload.get("next_cursor")
        resp_page_size = payload.get("page_size", page_size)
        if not isinstance(has_more, bool) or (next_cursor is not None and not isinstance(next_cursor, str)):
            raise PlatformLLMUpstreamError()

        return PlatformModelListPage(
            items=items,
            page_size=resp_page_size if isinstance(resp_page_size, int) else page_size,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    async def get_model_version(
        self,
        resource_token: SecretStr,
        *,
        resource_id: str,
        version_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """读取固定模型版本详情（沿用原昆联 code/message/data/request_id 响应格式）。"""
        if not resource_id.strip() or not version_id.strip() or version_id.strip().lower() == "latest":
            raise PlatformLLMConfigurationError()
        path = MODEL_VERSION_PATH.format(
            resource_id=quote(resource_id.strip(), safe=""),
            version_id=quote(version_id.strip(), safe=""),
        )
        headers = {
            "Authorization": f"Bearer {resource_token.get_secret_value()}",
            "X-Trace-ID": trace_id or uuid4().hex,
            "Accept": "application/json",
        }
        try:
            async with self._build_client(self.config.list_timeout_seconds) as client:
                async with asyncio.timeout(self.config.list_timeout_seconds):
                    request = client.build_request("GET", f"{self._resource_base}{path}", headers=headers)
                    request.headers.pop("cookie", None)
                    response, content = await _send_bounded(
                        client, request, max_bytes=self.config.max_list_payload_bytes
                    )
        except TimeoutError:
            raise PlatformLLMTimeoutError() from None
        except (httpx.TransportError, _ResponseTooLarge):
            raise PlatformLLMUpstreamError() from None

        try:
            body = json.loads(content)
        except ValueError:
            raise PlatformLLMUpstreamError() from None

        if response.status_code != 200 or not isinstance(body, dict):
            raise _map_http_error(response.status_code)
        code = body.get("code")
        if code not in (None, "OK", "SUCCESS", 200, 0):
            raise PlatformLLMUpstreamError()
        data = body.get("data")
        if not isinstance(data, dict):
            raise PlatformLLMUpstreamError()
        return data

    async def chat_completions(
        self,
        resource_token: SecretStr,
        *,
        call_id: str,
        messages: list[dict[str, Any]],
        temperature: float = 1.0,
        trace_id: str | None = None,
    ) -> ChatCompletionResult:
        """调用昆联 POST /api/platform/v1/chat/completions（标准 OpenAI 非流式 JSON 契约）。"""
        if not call_id.strip() or call_id.strip().lower() == "latest" or not messages:
            raise PlatformLLMConfigurationError()
        headers = {
            "Authorization": f"Bearer {resource_token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Trace-ID": trace_id or uuid4().hex,
        }
        payload = {
            "model": call_id.strip(),
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        try:
            async with self._build_client(self.config.invoke_timeout_seconds) as client:
                async with asyncio.timeout(self.config.invoke_timeout_seconds):
                    request = client.build_request(
                        "POST",
                        f"{self._resource_base}{CHAT_COMPLETIONS_PATH}",
                        headers=headers,
                        json=payload,
                    )
                    request.headers.pop("cookie", None)
                    response, content = await _send_bounded(
                        client, request, max_bytes=self.config.max_invoke_payload_bytes
                    )
        except TimeoutError:
            raise PlatformLLMTimeoutError() from None
        except (httpx.TransportError, _ResponseTooLarge):
            raise PlatformLLMUpstreamError() from None

        try:
            body = json.loads(content)
        except ValueError:
            raise PlatformLLMUpstreamError() from None

        if response.status_code != 200 or not isinstance(body, dict):
            err_data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else {}
            reason_code = err_data.get("reason_code") if isinstance(err_data.get("reason_code"), str) else None
            raise _map_http_error(response.status_code, reason_code)

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise PlatformLLMUpstreamError()
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise PlatformLLMUpstreamError()
        raw_content = message.get("content")
        if isinstance(raw_content, list):
            text = "".join(
                part.get("text", "") for part in raw_content if isinstance(part, dict) and part.get("type") == "text"
            )
        elif isinstance(raw_content, str):
            text = raw_content
        elif raw_content is None:
            text = ""
        else:
            raise PlatformLLMUpstreamError()
        reasoning = message.get("reasoning_content")
        return ChatCompletionResult(
            content=text,
            reasoning_content=reasoning if isinstance(reasoning, str) else "",
            raw_id=str(body.get("id") or ""),
        )
