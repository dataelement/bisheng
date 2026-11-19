"""昆联平台大模型 OIDC Token Exchange、模型目录与推理 HTTP 客户端。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
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
from bisheng.workflow.domain.clients.kunlian_resources import (
    ACCESS_TOKEN_TYPE as ACCESS_TOKEN_TYPE,
)
from bisheng.workflow.domain.clients.kunlian_resources import (
    RESOURCES_PATH as RESOURCES_PATH,
)
from bisheng.workflow.domain.clients.kunlian_resources import (
    SCOPE_RESOURCES_READ as SCOPE_RESOURCES_READ,
)
from bisheng.workflow.domain.clients.kunlian_resources import (
    TOKEN_EXCHANGE_GRANT as TOKEN_EXCHANGE_GRANT,
)
from bisheng.workflow.domain.clients.kunlian_resources import (
    ExchangedResourceToken,
    KunlianBadRequestError,
    KunlianHttpStatusError,
    KunlianInvalidTokenError,
    KunlianNotConfiguredError,
    KunlianTimeoutError,
    ResponseTooLargeError,
    build_async_client,
    extract_error_context,
    fetch_resource_version_detail,
    fetch_resources_page,
    validate_resource_origin,
)
from bisheng.workflow.domain.clients.kunlian_resources import (
    exchange_resource_token as shared_exchange_resource_token,
)
from bisheng.workflow.domain.clients.kunlian_resources import (
    send_bounded as _send_bounded,
)
from bisheng.workflow.domain.schemas.platform_llm import PlatformModelListPage, PlatformModelSummary

MODEL_VERSION_PATH = "/api/platform/v1/resources/model/{resource_id}/versions/{version_id}"
CHAT_COMPLETIONS_PATH = "/api/platform/v1/chat/completions"

SCOPE_MODEL_INVOKE = "platform.model.invoke"

_ResponseTooLarge = ResponseTooLargeError


def _validate_origin(url: str, *, approved_test_origins: tuple[str, ...] = ()) -> str:
    try:
        return validate_resource_origin(url, approved_test_origins=approved_test_origins)
    except KunlianNotConfiguredError:
        raise PlatformLLMNotReadyError() from None


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


def _map_shared_error(exc: Exception) -> PlatformLLMError:
    if isinstance(exc, KunlianNotConfiguredError):
        return PlatformLLMNotReadyError()
    if isinstance(exc, KunlianBadRequestError):
        return PlatformLLMConfigurationError()
    if isinstance(exc, KunlianInvalidTokenError):
        return PlatformLLMTokenError()
    if isinstance(exc, KunlianTimeoutError):
        return PlatformLLMTimeoutError()
    if isinstance(exc, KunlianHttpStatusError):
        return _map_http_error(exc.status_code, exc.reason_code)
    return PlatformLLMUpstreamError()


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
        return build_async_client(timeout=timeout, transport=self._transport)

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
        try:
            return await shared_exchange_resource_token(
                oidc_token_url=oidc_token_url,
                client_id=client_id,
                client_secret=client_secret,
                subject_token=subject_token,
                audience=self.config.resource_audience,
                scope=scope,
                timeout_seconds=self.config.list_timeout_seconds,
                trace_id=trace_id,
                transport=self._transport,
            )
        except Exception as exc:
            if isinstance(exc, KunlianHttpStatusError):
                if exc.status_code in (400, 401):
                    raise PlatformLLMTokenError() from None
                if exc.status_code == 403:
                    raise PlatformLLMPermissionError() from None
            raise _map_shared_error(exc) from None

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
        try:
            page = await fetch_resources_page(
                resource_base=self._resource_base,
                resource_token=resource_token,
                resource_type="model",
                action="use",
                page_size=page_size,
                search=search,
                cursor=cursor,
                timeout_seconds=self.config.list_timeout_seconds,
                max_payload_bytes=self.config.max_list_payload_bytes,
                trace_id=trace_id,
                transport=self._transport,
            )
        except Exception as exc:
            raise _map_shared_error(exc) from None

        try:
            items = [PlatformModelSummary.model_validate(row) for row in page.raw_items]
        except ValidationError:
            raise PlatformLLMUpstreamError() from None

        return PlatformModelListPage(
            items=items,
            page_size=page.page_size,
            has_more=page.has_more,
            next_cursor=page.next_cursor,
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
        try:
            return await fetch_resource_version_detail(
                resource_base=self._resource_base,
                path_template=MODEL_VERSION_PATH,
                resource_token=resource_token,
                resource_id=resource_id,
                version_id=version_id,
                timeout_seconds=self.config.list_timeout_seconds,
                max_payload_bytes=self.config.max_list_payload_bytes,
                trace_id=trace_id,
                transport=self._transport,
            )
        except Exception as exc:
            raise _map_shared_error(exc) from None

    async def chat_completions(
        self,
        resource_token: SecretStr,
        *,
        call_id: str,
        messages: list[dict[str, Any]],
        workflow_run_id: str | None = None,
        node_run_id: str | None = None,
        trace_id: str | None = None,
    ) -> ChatCompletionResult:
        """调用昆联 POST /api/platform/v1/chat/completions（标准 OpenAI 非流式 JSON 契约）。"""
        if not call_id.strip() or call_id.strip().lower() == "latest" or not messages:
            raise PlatformLLMConfigurationError()
        req_trace = trace_id or uuid4().hex
        wf_run = (workflow_run_id or "").strip() or req_trace
        nd_run = (node_run_id or "").strip() or uuid4().hex
        headers = {
            "Authorization": f"Bearer {resource_token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Trace-ID": req_trace,
        }
        payload = {
            "model": call_id.strip(),
            "messages": messages,
            "stream": False,
            "metadata": {
                "workflow_run_id": wf_run,
                "node_run_id": nd_run,
            },
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
            ctx = extract_error_context(response, body, request_trace_id=req_trace)
            raise _map_http_error(response.status_code, ctx.reason_code)

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
