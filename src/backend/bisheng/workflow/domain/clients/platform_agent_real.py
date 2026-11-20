"""昆联平台已发布 Agent 目录与固定版本详情真实 HTTP 客户端与 Provider。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
from loguru import logger
from pydantic import SecretStr

from bisheng.common.errcode.flow import (
    PlatformAgentBadRequestError,
    PlatformAgentError,
    PlatformAgentExecutionError,
    PlatformAgentNotReadyError,
    PlatformAgentOutputError,
    PlatformAgentPermissionError,
    PlatformAgentRateLimitError,
    PlatformAgentTokenError,
    PlatformAgentUnknownError,
    PlatformAgentUpstreamError,
    PlatformAgentVersionError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError, KunlianError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.sso_sync.application.kunlian import resolve_kunlian_token_exchange_material
from bisheng.workflow.domain.clients.kunlian_resources import (
    SCOPE_AGENT_INVOKE,
    SCOPE_RESOURCES_READ,
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
    sanitize_log_field,
    send_bounded,
    validate_resource_origin,
)
from bisheng.workflow.domain.clients.kunlian_resources import (
    exchange_resource_token as shared_exchange_resource_token,
)
from bisheng.workflow.domain.schemas.platform_agent import (
    AgentInvokeResult,
    AgentReference,
    AgentVersion,
    PlatformAgentListPage,
    PlatformAgentResourceItem,
    VerifiedAgentActor,
    validate_schema,
    validate_value,
)

AGENT_VERSION_PATH = "/api/platform/v1/resources/agent/{resource_id}/versions/{version_id}"
CHAT_COMPLETIONS_PATH = "/api/platform/v1/chat/completions"


@dataclass(frozen=True)
class AgentChatCompletion:
    """昆联平台 Agent 同步对话完成响应摘要。"""

    content: str
    raw_id: str
    model: str
    finish_reason: str
    trace_id: str = ""
    request_id: str = ""


def _empty_object_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": []}


def _normalize_object_schema(raw: Any) -> dict[str, Any]:
    """将版本详情中的 input/output schema 归一化为通过节点契约校验的对象 schema。"""
    if raw is None or raw == {}:
        return _empty_object_schema()
    if not isinstance(raw, dict):
        return _empty_object_schema()
    candidate = dict(raw)
    if "type" not in candidate and isinstance(candidate.get("properties"), dict):
        candidate["type"] = "object"
    try:
        validate_schema(candidate, root_object=True)
        return candidate
    except PlatformAgentError:
        logger.debug("platform agent version detail schema incompatible; falling back to empty object schema")
        return _empty_object_schema()


def _map_http_error(status_code: int, reason_code: str | None = None) -> PlatformAgentError:
    """按照昆联 Agent 目录、版本详情与同步执行契约将 HTTP 状态码与错误码映射为稳定业务异常。"""
    normalized = reason_code.strip().upper() if isinstance(reason_code, str) and reason_code.strip() else None
    if normalized in ("IDEMPOTENCY_IN_PROGRESS", "IDEMPOTENCY_CONFLICT"):
        return PlatformAgentExecutionError()
    if status_code == 400 or normalized == "INVALID_REQUEST":
        return PlatformAgentBadRequestError()
    if status_code == 401 or normalized == "INVALID_TOKEN":
        return PlatformAgentTokenError()
    if status_code == 403 or normalized == "PERMISSION_DENIED":
        return PlatformAgentPermissionError()
    if status_code == 404 or normalized in ("NOT_FOUND", "VERSION_NOT_FOUND", "RESOURCE_NOT_FOUND"):
        return PlatformAgentVersionError()
    if status_code == 409:
        return PlatformAgentExecutionError()
    if status_code == 429 or normalized == "RATE_LIMIT_EXCEEDED":
        return PlatformAgentRateLimitError()
    if status_code == 503 or normalized == "SERVICE_UNAVAILABLE":
        return PlatformAgentNotReadyError()
    if status_code == 504 or normalized == "EXECUTION_TIMEOUT":
        return PlatformAgentUnknownError()
    return PlatformAgentUpstreamError()


def _map_shared_error(exc: Exception) -> PlatformAgentError:
    if isinstance(exc, KunlianNotConfiguredError):
        return PlatformAgentNotReadyError()
    if isinstance(exc, KunlianBadRequestError):
        return PlatformAgentBadRequestError()
    if isinstance(exc, KunlianInvalidTokenError):
        return PlatformAgentTokenError()
    if isinstance(exc, KunlianTimeoutError):
        return PlatformAgentUnknownError()
    if isinstance(exc, KunlianHttpStatusError):
        return _map_http_error(exc.status_code, exc.reason_code)
    return PlatformAgentUpstreamError()


def _map_identity_error(exc: Exception) -> PlatformAgentError:
    if isinstance(exc, PlatformAgentError):
        return exc
    if isinstance(exc, KunlianDependencyUnavailableError):
        return PlatformAgentNotReadyError()
    if isinstance(exc, KunlianError):
        return PlatformAgentTokenError()
    if isinstance(exc, UnAuthorizedError):
        return PlatformAgentPermissionError()
    return PlatformAgentUpstreamError()


def _parse_agent_item(row: dict[str, Any]) -> PlatformAgentResourceItem:
    resource_type = row.get("resource_type")
    if resource_type is not None and resource_type != "agent":
        raise PlatformAgentUpstreamError()
    resource_id = row.get("resource_id")
    version_id = row.get("version_id")
    name = row.get("name")
    if (
        not isinstance(resource_id, str)
        or not resource_id.strip()
        or not isinstance(version_id, str)
        or not version_id.strip()
        or not isinstance(name, str)
        or not name.strip()
    ):
        raise PlatformAgentUpstreamError()
    raw_actions = row.get("allowed_actions")
    allowed_actions = [str(item) for item in raw_actions] if isinstance(raw_actions, list) else []
    description = row.get("description")
    version = row.get("version")
    status = row.get("status")
    call_id = row.get("call_id")
    return PlatformAgentResourceItem(
        resource_type="agent",
        resource_id=resource_id.strip(),
        version_id=version_id.strip(),
        name=name.strip(),
        description=description if isinstance(description, str) else "",
        version=version if isinstance(version, str) else "",
        status=status if isinstance(status, str) else "",
        allowed_actions=allowed_actions,
        call_id=call_id.strip() if isinstance(call_id, str) else "",
    )


class KunlianPlatformAgentClient:
    """昆联平台已发布 Agent 目录与固定版本详情 HTTP 客户端。"""

    def __init__(self, config: PlatformAgentConf, *, transport: httpx.AsyncBaseTransport | None = None):
        if config.mode != "real" or not config.resource_base_url.strip():
            raise PlatformAgentNotReadyError()
        self.config = config
        try:
            self._resource_base = validate_resource_origin(config.resource_base_url)
        except KunlianNotConfiguredError:
            raise PlatformAgentNotReadyError() from None
        self._transport = transport

    async def exchange_resource_token(
        self,
        *,
        oidc_token_url: str,
        client_id: str,
        client_secret: SecretStr,
        subject_token: SecretStr,
        scope: str = SCOPE_RESOURCES_READ,
        trace_id: str | None = None,
    ) -> ExchangedResourceToken:
        """使用用户 SSO Access Token 兑换短时昆联资源令牌（platform.resources.read）。"""
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
                    raise PlatformAgentTokenError() from None
                if exc.status_code == 403:
                    raise PlatformAgentPermissionError() from None
            raise _map_shared_error(exc) from None

    async def list_agents(
        self,
        resource_token: SecretStr,
        *,
        page_size: int = 20,
        search: str | None = None,
        cursor: str | None = None,
        trace_id: str | None = None,
    ) -> PlatformAgentListPage:
        """查询当前用户有权使用的已发布 Agent 列表（types=agent, action=use）。"""
        try:
            page = await fetch_resources_page(
                resource_base=self._resource_base,
                resource_token=resource_token,
                resource_type="agent",
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

        items = [_parse_agent_item(row) for row in page.raw_items]
        return PlatformAgentListPage(
            items=items,
            page_size=page.page_size,
            has_more=page.has_more,
            next_cursor=page.next_cursor,
        )

    async def get_agent_version(
        self,
        resource_token: SecretStr,
        *,
        resource_id: str,
        version_id: str,
        trace_id: str | None = None,
    ) -> AgentVersion:
        """读取固定 Agent 版本详情，严禁传 latest；未返回 schema 时安全回退为空对象 schema。"""
        clean_id = resource_id.strip()
        clean_ver = version_id.strip()
        if not clean_id or not clean_ver or clean_ver.lower() == "latest":
            raise PlatformAgentVersionError()

        try:
            data = await fetch_resource_version_detail(
                resource_base=self._resource_base,
                path_template=AGENT_VERSION_PATH,
                resource_token=resource_token,
                resource_id=clean_id,
                version_id=clean_ver,
                timeout_seconds=self.config.list_timeout_seconds,
                max_payload_bytes=self.config.max_list_payload_bytes,
                trace_id=trace_id,
                transport=self._transport,
            )
        except Exception as exc:
            if isinstance(exc, KunlianBadRequestError):
                raise PlatformAgentVersionError() from None
            raise _map_shared_error(exc) from None

        resolved_id = str(data.get("resource_id") or data.get("agent_id") or clean_id).strip() or clean_id
        resolved_ver = str(data.get("version_id") or clean_ver).strip() or clean_ver
        name = str(data.get("name") or resolved_id).strip() or resolved_id
        call_id = data.get("call_id").strip() if isinstance(data.get("call_id"), str) else ""
        version = data.get("version").strip() if isinstance(data.get("version"), str) else ""
        description = data.get("description") if isinstance(data.get("description"), str) else ""
        status = data.get("status") if isinstance(data.get("status"), str) else ""
        raw_actions = data.get("allowed_actions")
        can_use = ("use" in raw_actions) if isinstance(raw_actions, list) else True
        available = bool(data.get("available", status not in ("disabled", "unavailable", "offline")))

        return AgentVersion(
            ref=AgentReference(
                agent_id=resolved_id,
                version_id=resolved_ver,
            ),
            name=name,
            input_schema=_normalize_object_schema(data.get("input_schema")),
            output_schema=_normalize_object_schema(data.get("output_schema")),
            call_id=call_id or None,
            version=version or None,
            description=description,
            status=status,
            available=available,
            can_use=can_use,
            supports_async=False,
            supports_interaction=False,
        )

    async def invoke_chat_completion(
        self,
        resource_token: SecretStr,
        *,
        call_id: str,
        messages: list[dict[str, Any]],
        workflow_run_id: str,
        node_run_id: str,
        idempotency_key: str,
        trace_id: str | None = None,
    ) -> AgentChatCompletion:
        """调用昆联 POST /api/platform/v1/chat/completions 同步执行固定版本 Agent。"""
        model_id = call_id.strip()
        if not model_id or model_id.lower() == "latest" or not messages:
            raise PlatformAgentBadRequestError()

        req_trace = (trace_id or "").strip() or uuid4().hex
        wf_run = workflow_run_id.strip() or req_trace
        nd_run = node_run_id.strip() or uuid4().hex
        idem_key = _normalize_idempotency_key(idempotency_key)

        headers = {
            "Authorization": f"Bearer {resource_token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Caller-Type": "workflow",
            "X-Trace-ID": req_trace,
            "X-Idempotency-Key": idem_key,
        }
        payload = {
            "model": model_id,
            "messages": messages,
            "stream": False,
            "metadata": {
                "workflow_run_id": wf_run,
                "node_run_id": nd_run,
            },
        }
        try:
            async with build_async_client(
                timeout=self.config.invoke_timeout_seconds,
                transport=self._transport,
            ) as client:
                async with asyncio.timeout(self.config.invoke_timeout_seconds):
                    request = client.build_request(
                        "POST",
                        f"{self._resource_base}{CHAT_COMPLETIONS_PATH}",
                        headers=headers,
                        json=payload,
                    )
                    request.headers.pop("cookie", None)
                    response, content = await send_bounded(
                        client,
                        request,
                        max_bytes=self.config.max_payload_bytes,
                    )
        except TimeoutError:
            raise PlatformAgentUnknownError() from None
        except (httpx.TransportError, ResponseTooLargeError):
            raise PlatformAgentUpstreamError() from None

        resp_trace = (
            response.headers.get("X-Trace-ID")
            or response.headers.get("x-trace-id")
            or req_trace
        )
        resp_request_id = (
            response.headers.get("X-Request-ID")
            or response.headers.get("x-request-id")
            or ""
        )

        try:
            body = json.loads(content)
        except ValueError:
            logger.warning(
                "kunlian agent invoke invalid json status={} x_trace_id={} x_request_id={} "
                "workflow_run_id={} node_run_id={}",
                response.status_code,
                sanitize_log_field(resp_trace),
                sanitize_log_field(resp_request_id),
                sanitize_log_field(wf_run),
                sanitize_log_field(nd_run),
            )
            raise PlatformAgentUpstreamError() from None

        if response.status_code != 200 or not isinstance(body, dict):
            ctx = extract_error_context(response, body, request_trace_id=req_trace)
            logger.warning(
                "kunlian agent invoke failed status={} error_code={} x_trace_id={} x_request_id={} "
                "workflow_run_id={} node_run_id={}",
                response.status_code,
                sanitize_log_field(ctx.reason_code),
                sanitize_log_field(resp_trace),
                sanitize_log_field(resp_request_id),
                sanitize_log_field(wf_run),
                sanitize_log_field(nd_run),
            )
            raise _map_http_error(response.status_code, ctx.reason_code)

        if "object" in body and body.get("object") != "chat.completion":
            raise PlatformAgentUpstreamError()
        resp_model = body.get("model")
        if isinstance(resp_model, str) and resp_model.strip() != model_id:
            raise PlatformAgentVersionError()

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise PlatformAgentUpstreamError()
        first_choice = choices[0]
        finish_reason = first_choice.get("finish_reason")
        if finish_reason != "stop":
            raise PlatformAgentUpstreamError()

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise PlatformAgentUpstreamError()
        raw_content = message.get("content")
        if isinstance(raw_content, list):
            text = "".join(
                part.get("text", "")
                for part in raw_content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        elif isinstance(raw_content, str):
            text = raw_content
        elif raw_content is None:
            text = ""
        else:
            raise PlatformAgentUpstreamError()

        raw_id = str(body.get("id") or "").strip()
        logger.info(
            "kunlian agent invoke succeeded status=200 x_trace_id={} x_request_id={} "
            "workflow_run_id={} node_run_id={} id={} model={}",
            sanitize_log_field(resp_trace),
            sanitize_log_field(resp_request_id),
            sanitize_log_field(wf_run),
            sanitize_log_field(nd_run),
            sanitize_log_field(raw_id),
            sanitize_log_field(model_id),
        )
        return AgentChatCompletion(
            content=text,
            raw_id=raw_id,
            model=resp_model.strip() if isinstance(resp_model, str) else model_id,
            finish_reason=finish_reason,
            trace_id=resp_trace,
            request_id=resp_request_id,
        )


def _normalize_idempotency_key(raw: str) -> str:
    """规范化 X-Idempotency-Key 为 16-128 位不含空格的可打印 ASCII。"""
    candidate = (raw or "").strip()
    if 16 <= len(candidate) <= 128 and all(33 <= ord(ch) <= 126 for ch in candidate):
        return candidate
    if candidate:
        return hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return uuid4().hex


def _build_agent_messages(inputs: dict, user_prompt: str | None) -> list[dict[str, Any]]:
    """从节点提示词或结构化输入组装 Chat Completions messages。"""
    raw_messages = inputs.get("messages") if isinstance(inputs, dict) else None
    if isinstance(raw_messages, list) and raw_messages and all(isinstance(m, dict) for m in raw_messages):
        return raw_messages

    prompt_text = user_prompt.strip() if isinstance(user_prompt, str) and user_prompt.strip() else ""
    extra_inputs = {k: v for k, v in (inputs or {}).items() if k != "messages"}

    if prompt_text and not extra_inputs:
        return [{"role": "user", "content": prompt_text}]
    if prompt_text and extra_inputs:
        serialized = json.dumps(extra_inputs, ensure_ascii=False)
        return [{"role": "user", "content": f"{prompt_text}\n\n{serialized}"}]

    if extra_inputs:
        for preferred in ("query", "prompt", "content", "question", "input"):
            val = extra_inputs.get(preferred)
            if len(extra_inputs) == 1 and isinstance(val, str) and val.strip():
                return [{"role": "user", "content": val.strip()}]
        return [{"role": "user", "content": json.dumps(extra_inputs, ensure_ascii=False)}]

    raise PlatformAgentBadRequestError()


def _format_agent_output(
    completion: AgentChatCompletion,
    *,
    output_schema: dict[str, Any],
) -> dict[str, Any]:
    """将 Agent 响应包装为通过 output_schema 校验的对象（优先适配声明式 schema）。"""
    if isinstance(output_schema.get("properties"), dict) and output_schema["properties"]:
        try:
            parsed = json.loads(completion.content)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            try:
                validate_value(parsed, output_schema, output=True)
                return parsed
            except PlatformAgentOutputError:
                pass
    return {
        "content": completion.content,
        "id": completion.raw_id,
        "model": completion.model,
        "finish_reason": completion.finish_reason,
    }


class RealPlatformAgentProvider:
    """昆联真实模式 PlatformAgentProvider（支持目录列表、固定版本详情与同步执行）。"""

    def __init__(
        self,
        config: PlatformAgentConf,
        *,
        client: KunlianPlatformAgentClient | None = None,
        token_material_resolver=None,
        transport: httpx.AsyncBaseTransport | None = None,
        enable_interactions: bool = False,
    ):
        self.config = config
        self.enable_interactions = enable_interactions
        self.client = client or KunlianPlatformAgentClient(config, transport=transport)
        self.token_material_resolver = token_material_resolver or resolve_kunlian_token_exchange_material

    async def _exchange_token(
        self,
        actor: VerifiedAgentActor,
        *,
        scope: str,
        trace_id: str,
        require_scope: bool = False,
    ) -> ExchangedResourceToken:
        try:
            material = await self.token_material_resolver(
                actor.user_id,
                session_reference=actor.session_reference,
                oidc_token_url=self.config.oidc_token_url,
            )
            exchanged = await self.client.exchange_resource_token(
                oidc_token_url=material.oidc_token_url,
                client_id=material.client_id,
                client_secret=material.client_secret,
                subject_token=material.subject_token,
                scope=scope,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.debug(
                "platform agent token exchange error user_id={} trace_id={} scope={} err_type={}",
                actor.user_id,
                sanitize_log_field(trace_id),
                sanitize_log_field(scope),
                type(exc).__name__,
            )
            raise _map_identity_error(exc) from None

        if require_scope and scope not in (exchanged.scope or "").split():
            logger.warning(
                "kunlian resource token missing required scope user_id={} trace_id={} expected_scope={}",
                actor.user_id,
                sanitize_log_field(trace_id),
                sanitize_log_field(scope),
            )
            raise PlatformAgentPermissionError()
        return exchanged

    async def _exchange_read_token(self, actor: VerifiedAgentActor, *, trace_id: str) -> ExchangedResourceToken:
        return await self._exchange_token(actor, scope=SCOPE_RESOURCES_READ, trace_id=trace_id)

    async def list_agents(
        self,
        actor: VerifiedAgentActor,
        cursor: str | None = None,
        *,
        page_size: int = 20,
        search: str | None = None,
    ) -> dict:
        trace_id = uuid4().hex
        exchanged = await self._exchange_read_token(actor, trace_id=trace_id)
        page = await self.client.list_agents(
            exchanged.access_token,
            page_size=page_size,
            search=search,
            cursor=cursor,
            trace_id=trace_id,
        )

        # 按 resource_id 聚合当前页版本列表，同时保留平铺 items 供前端多页合并或诊断
        grouped: dict[str, dict[str, Any]] = {}
        for item in page.items:
            entry = grouped.setdefault(
                item.resource_id,
                {
                    "agent_id": item.resource_id,
                    "name": item.name,
                    "description": item.description,
                    "versions": [],
                    "version_items": [],
                },
            )
            if item.version_id not in entry["versions"]:
                entry["versions"].append(item.version_id)
                entry["version_items"].append(
                    {
                        "version_id": item.version_id,
                        "version": item.version,
                        "call_id": item.call_id,
                        "name": item.name,
                        "description": item.description,
                        "status": item.status,
                        "allowed_actions": item.allowed_actions,
                    }
                )

        return {
            "data": list(grouped.values()),
            "items": [item.model_dump() for item in page.items],
            "page_size": page.page_size,
            "next_cursor": page.next_cursor,
            "has_more": page.has_more,
            "provider_mode": self.config.mode,
            "policy_revision": self.config.policy_revision,
        }

    async def get_version(self, actor: VerifiedAgentActor, ref: AgentReference) -> AgentVersion:
        trace_id = uuid4().hex
        exchanged = await self._exchange_read_token(actor, trace_id=trace_id)
        return await self.client.get_agent_version(
            exchanged.access_token,
            resource_id=ref.agent_id,
            version_id=ref.version_id,
            trace_id=trace_id,
        )

    async def check_use(self, actor: VerifiedAgentActor, ref: AgentReference) -> AgentVersion:
        version = await self.get_version(actor, ref)
        if not version.available:
            raise PlatformAgentPermissionError()
        if not version.can_use:
            raise PlatformAgentPermissionError()
        return version

    async def invoke(
        self,
        actor: VerifiedAgentActor,
        ref: AgentReference,
        inputs: dict,
        call_id: str = "",
        *,
        user_prompt: str | None = None,
        workflow_run_id: str | None = None,
        node_run_id: str | None = None,
        idempotency_key: str | None = None,
        resolved_version: AgentVersion | None = None,
    ) -> AgentInvokeResult:
        trace_id = uuid4().hex
        version = resolved_version or await self.check_use(actor, ref)
        if not version.available or not version.can_use:
            raise PlatformAgentPermissionError()

        model_call_id = (version.call_id or ref.call_id or version.ref.version_id).strip()
        if not model_call_id or model_call_id.lower() == "latest":
            raise PlatformAgentVersionError()

        messages = _build_agent_messages(inputs, user_prompt)
        exchanged = await self._exchange_token(
            actor,
            scope=SCOPE_AGENT_INVOKE,
            trace_id=trace_id,
            require_scope=True,
        )
        wf_run = (workflow_run_id or "").strip() or (call_id.split(":", 1)[0] if call_id else trace_id)
        nd_run = (node_run_id or "").strip() or call_id or trace_id
        idem = (idempotency_key or "").strip() or call_id or trace_id
        completion = await self.client.invoke_chat_completion(
            exchanged.access_token,
            call_id=model_call_id,
            messages=messages,
            workflow_run_id=wf_run,
            node_run_id=nd_run,
            idempotency_key=idem,
            trace_id=trace_id,
        )
        output = _format_agent_output(completion, output_schema=version.output_schema)
        return AgentInvokeResult(
            status="SUCCEEDED",
            ref=version.ref,
            output=output,
            agent_run_id=completion.raw_id or call_id or None,
        )
