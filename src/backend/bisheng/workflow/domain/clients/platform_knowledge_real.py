"""昆联平台知识库目录与知识检索真实 HTTP 客户端与 Provider。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
from loguru import logger
from pydantic import SecretStr

from bisheng.common.errcode.flow import (
    PlatformKnowledgeConfigurationError,
    PlatformKnowledgeError,
    PlatformKnowledgeNotReadyError,
    PlatformKnowledgeOutputError,
    PlatformKnowledgePermissionError,
    PlatformKnowledgeResourceError,
    PlatformKnowledgeTimeoutError,
    PlatformKnowledgeUpstreamError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError, KunlianError
from bisheng.core.config.settings import PlatformKnowledgeConf
from bisheng.sso_sync.application.kunlian import resolve_kunlian_token_exchange_material
from bisheng.workflow.domain.clients.kunlian_resources import (
    SCOPE_KNOWLEDGE_RETRIEVE,
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
    fetch_resources_page,
    sanitize_log_field,
    send_bounded,
    validate_resource_origin,
)
from bisheng.workflow.domain.clients.kunlian_resources import (
    exchange_resource_token as shared_exchange_resource_token,
)
from bisheng.workflow.domain.schemas.platform_knowledge import MAX_QUERY_LENGTH, MAX_TOP_K, KnowledgeActor

KNOWLEDGE_RETRIEVE_PATH = "/api/platform/v1/knowledge/retrieve"
_MAX_DIRECTORY_SCAN_PAGES = 10


@dataclass(frozen=True)
class KnowledgeRetrieveResult:
    """昆联知识检索单次响应摘要。"""

    items: list[dict[str, Any]]
    query_id: str = ""
    permission_filtered: bool | None = None
    trace_id: str = ""


def _map_http_error(
    status_code: int,
    reason_code: str | None = None,
    *,
    body_status: int | None = None,
) -> PlatformKnowledgeError:
    """按昆联知识检索文档及双方契约将 HTTP 状态码 / reason_code 映射为稳定业务异常。"""
    normalized = reason_code.strip().upper() if isinstance(reason_code, str) and reason_code.strip() else None
    if status_code in (401, 403) or normalized in ("INVALID_TOKEN", "PERMISSION_DENIED", "FORBIDDEN"):
        return PlatformKnowledgePermissionError()
    if (
        status_code == 404
        or body_status == 10970
        or normalized in ("NOT_FOUND", "RESOURCE_NOT_FOUND", "KNOWLEDGE_NOT_FOUND")
    ):
        return PlatformKnowledgeResourceError()
    if status_code == 409 or normalized in ("VERSION_CONFLICT", "VERSION_MISMATCH", "RESOURCE_VERSION_MISMATCH"):
        return PlatformKnowledgeResourceError()
    if status_code == 400 or normalized in ("INVALID_REQUEST", "INVALID_QUERY", "BAD_REQUEST"):
        return PlatformKnowledgeConfigurationError()
    if status_code == 503 or normalized == "SERVICE_UNAVAILABLE":
        return PlatformKnowledgeNotReadyError()
    if status_code == 504 or normalized in ("EXECUTION_TIMEOUT", "GATEWAY_TIMEOUT", "TIMEOUT"):
        return PlatformKnowledgeTimeoutError()
    return PlatformKnowledgeUpstreamError()


def _map_shared_error(exc: Exception) -> PlatformKnowledgeError:
    if isinstance(exc, KunlianNotConfiguredError):
        return PlatformKnowledgeNotReadyError()
    if isinstance(exc, KunlianBadRequestError):
        return PlatformKnowledgeConfigurationError()
    if isinstance(exc, KunlianInvalidTokenError):
        return PlatformKnowledgePermissionError()
    if isinstance(exc, KunlianTimeoutError):
        return PlatformKnowledgeTimeoutError()
    if isinstance(exc, KunlianHttpStatusError):
        return _map_http_error(exc.status_code, exc.reason_code)
    return PlatformKnowledgeUpstreamError()


def _map_identity_error(exc: Exception) -> PlatformKnowledgeError:
    if isinstance(exc, PlatformKnowledgeError):
        return exc
    if isinstance(exc, KunlianDependencyUnavailableError):
        return PlatformKnowledgeNotReadyError()
    if isinstance(exc, KunlianError):
        return PlatformKnowledgePermissionError()
    if isinstance(exc, UnAuthorizedError):
        return PlatformKnowledgePermissionError()
    return PlatformKnowledgeUpstreamError()


def _parse_knowledge_item(row: dict[str, Any]) -> dict[str, Any]:
    """解析单条知识库目录记录，兼容统一资源格式与 quickstart 文档字段。"""
    resource_type = row.get("resource_type")
    if resource_type is not None and resource_type != "knowledge":
        raise PlatformKnowledgeOutputError()
    resource_id = row.get("resource_id")
    version_id = row.get("version_id") or row.get("current_version_id")
    name = row.get("name")
    if (
        not isinstance(resource_id, str)
        or not resource_id.strip()
        or not isinstance(version_id, str)
        or not version_id.strip()
        or not isinstance(name, str)
        or not name.strip()
    ):
        raise PlatformKnowledgeOutputError()

    if "use_allowed" in row:
        use_allowed = bool(row.get("use_allowed"))
    elif isinstance(row.get("allowed_actions"), list):
        use_allowed = "use" in [str(item) for item in row["allowed_actions"]]
    else:
        use_allowed = True

    raw_status = row.get("status")
    status = raw_status.strip().lower() if isinstance(raw_status, str) and raw_status.strip() else "active"
    if not use_allowed:
        status = "forbidden"

    return {
        "resource_id": resource_id.strip(),
        "version_id": version_id.strip(),
        "name": name.strip(),
        "status": status,
        "provider_mode": "real",
        "use_allowed": use_allowed,
    }


def _parse_retrieve_hit(resource_id: str, item: Any) -> dict[str, Any]:
    """将昆联 /knowledge/retrieve 单条片段映射为 KnowledgeHit 输入字典。"""
    if not isinstance(item, dict):
        raise PlatformKnowledgeOutputError()
    chunk_id = item.get("chunk_id")
    document_id = item.get("document_id")
    content = item.get("content") if "content" in item else item.get("text")
    if (
        not isinstance(chunk_id, str)
        or not chunk_id.strip()
        or not isinstance(document_id, str)
        or not document_id.strip()
        or not isinstance(content, str)
        or not content.strip()
    ):
        raise PlatformKnowledgeOutputError()

    citation = item.get("citation")
    if citation is not None and not isinstance(citation, dict):
        raise PlatformKnowledgeOutputError()
    citation_dict = citation or {}

    raw_title = citation_dict.get("title") or item.get("document_name")
    document_name = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else None

    raw_page = citation_dict.get("page")
    location = item.get("location")
    if not isinstance(location, str) or not location.strip():
        if isinstance(raw_page, int) and not isinstance(raw_page, bool):
            location = f"第 {raw_page} 页"
        elif isinstance(raw_page, str) and raw_page.strip():
            location = raw_page.strip()
        else:
            location = None
    else:
        location = location.strip()

    raw_source_ref = citation_dict.get("source_ref")
    source_ref = raw_source_ref.strip() if isinstance(raw_source_ref, str) and raw_source_ref.strip() else None

    score = item.get("score")
    if isinstance(score, bool) or (score is not None and not isinstance(score, (int, float))):
        raise PlatformKnowledgeOutputError()

    return {
        "resource_id": resource_id,
        "document_id": document_id.strip(),
        "chunk_id": chunk_id.strip(),
        "text": content,
        "document_name": document_name,
        "location": location,
        "score": float(score) if score is not None else None,
        "source_ref": source_ref,
    }


class KunlianPlatformKnowledgeClient:
    """昆联平台知识库目录与检索 HTTP 客户端。"""

    def __init__(self, config: PlatformKnowledgeConf, *, transport: httpx.AsyncBaseTransport | None = None):
        if config.mode != "real" or not config.resource_base_url.strip():
            raise PlatformKnowledgeNotReadyError()
        self.config = config
        try:
            self._resource_base = validate_resource_origin(config.resource_base_url)
        except KunlianNotConfiguredError:
            raise PlatformKnowledgeNotReadyError() from None
        self._transport = transport

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
        """使用用户 SSO Access Token 兑换短时昆联资源令牌（<= 120s）。"""
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
            if isinstance(exc, KunlianHttpStatusError) and exc.status_code in (400, 401, 403):
                raise PlatformKnowledgePermissionError() from None
            raise _map_shared_error(exc) from None

    async def list_knowledge(
        self,
        resource_token: SecretStr,
        *,
        cursor: str | None = None,
        name: str | None = None,
        page_size: int = 20,
        type_param_name: str = "types",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """查询当前用户有权使用的知识库列表。"""
        try:
            page = await fetch_resources_page(
                resource_base=self._resource_base,
                resource_token=resource_token,
                resource_type="knowledge",
                action="use" if type_param_name == "types" else None,
                type_param_name=type_param_name,
                page_size=page_size,
                search=name,
                cursor=cursor,
                timeout_seconds=self.config.list_timeout_seconds,
                max_payload_bytes=self.config.max_list_payload_bytes,
                trace_id=trace_id,
                transport=self._transport,
            )
        except Exception as exc:
            raise _map_shared_error(exc) from None

        items = [_parse_knowledge_item(row) for row in page.raw_items]
        usable_items = [item for item in items if item["use_allowed"]]
        return {
            "items": usable_items,
            "next_cursor": page.next_cursor if page.has_more else None,
        }

    async def retrieve_chunks(
        self,
        resource_token: SecretStr,
        *,
        resource_id: str,
        version_id: str,
        query: str,
        top_k: int,
        workflow_run_id: str,
        node_run_id: str,
        trace_id: str | None = None,
    ) -> KnowledgeRetrieveResult:
        """调用 POST /api/platform/v1/knowledge/retrieve 执行知识检索。"""
        clean_id = resource_id.strip()
        clean_ver = version_id.strip()
        clean_query = query.strip()
        if (
            not clean_id
            or not clean_ver
            or clean_ver.lower() == "latest"
            or not clean_query
            or len(clean_query) > MAX_QUERY_LENGTH
            or isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or not 1 <= top_k <= MAX_TOP_K
        ):
            raise PlatformKnowledgeConfigurationError()

        req_trace = trace_id or uuid4().hex
        headers = {
            "Authorization": f"Bearer {resource_token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Caller-Type": "workflow",
            "X-Trace-ID": req_trace,
        }
        payload = {
            "knowledge_ref": {
                "resource_id": clean_id,
                "version_id": clean_ver,
            },
            "query": clean_query,
            "top_k": top_k,
            "filters": {},
            "run_context": {
                "workflow_run_id": workflow_run_id,
                "node_run_id": node_run_id,
            },
        }
        try:
            async with build_async_client(timeout=self.config.retrieve_timeout_seconds, transport=self._transport) as client:
                async with asyncio.timeout(self.config.retrieve_timeout_seconds):
                    request = client.build_request(
                        "POST",
                        f"{self._resource_base}{KNOWLEDGE_RETRIEVE_PATH}",
                        headers=headers,
                        json=payload,
                    )
                    request.headers.pop("cookie", None)
                    response, content = await send_bounded(client, request, max_bytes=self.config.max_payload_bytes)
        except TimeoutError:
            logger.warning("kunlian knowledge retrieve timeout trace_id={}", sanitize_log_field(req_trace))
            raise PlatformKnowledgeTimeoutError() from None
        except (httpx.TransportError, ResponseTooLargeError):
            logger.warning("kunlian knowledge retrieve transport failed trace_id={}", sanitize_log_field(req_trace))
            raise PlatformKnowledgeUpstreamError() from None

        try:
            body = json.loads(content)
        except ValueError:
            raise PlatformKnowledgeOutputError() from None

        if not isinstance(body, dict):
            raise PlatformKnowledgeOutputError()

        body_status = body.get("status_code") if isinstance(body.get("status_code"), int) else None
        if response.status_code != 200 or (body_status is not None and body_status != 200):
            ctx = extract_error_context(response, body, request_trace_id=req_trace)
            logger.warning(
                "kunlian knowledge retrieve failed resource_id={} version_id={} http_status={} "
                "body_status={} reason_code={} trace_id={} workflow_run_id={} node_run_id={}",
                sanitize_log_field(clean_id),
                sanitize_log_field(clean_ver),
                response.status_code,
                sanitize_log_field(body_status),
                sanitize_log_field(ctx.reason_code),
                sanitize_log_field(ctx.trace_id),
                sanitize_log_field(workflow_run_id),
                sanitize_log_field(node_run_id),
            )
            raise _map_http_error(response.status_code, ctx.reason_code, body_status=body_status)

        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise PlatformKnowledgeOutputError()

        hits = [_parse_retrieve_hit(clean_id, row) for row in data["items"]]
        query_id = data.get("query_id").strip() if isinstance(data.get("query_id"), str) else ""
        permission_filtered = data.get("permission_filtered") if isinstance(data.get("permission_filtered"), bool) else None
        logger.info(
            "kunlian knowledge retrieve ok resource_id={} version_id={} query_id={} hit_count={} "
            "permission_filtered={} workflow_run_id={} node_run_id={} trace_id={}",
            sanitize_log_field(clean_id),
            sanitize_log_field(clean_ver),
            sanitize_log_field(query_id),
            len(hits),
            permission_filtered,
            sanitize_log_field(workflow_run_id),
            sanitize_log_field(node_run_id),
            sanitize_log_field(req_trace),
        )
        return KnowledgeRetrieveResult(
            items=hits,
            query_id=query_id,
            permission_filtered=permission_filtered,
            trace_id=req_trace,
        )


class RealPlatformKnowledgeProvider:
    """昆联真实模式 PlatformKnowledgeProvider。"""

    def __init__(
        self,
        config: PlatformKnowledgeConf,
        *,
        client: KunlianPlatformKnowledgeClient | None = None,
        token_material_resolver=None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.config = config
        self.client = client or KunlianPlatformKnowledgeClient(config, transport=transport)
        self.token_material_resolver = token_material_resolver or resolve_kunlian_token_exchange_material

    async def _exchange_token(
        self,
        actor: KnowledgeActor,
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
                "platform knowledge token exchange error user_id={} trace_id={} scope={} err_type={}",
                actor.user_id,
                sanitize_log_field(trace_id),
                sanitize_log_field(scope),
                type(exc).__name__,
            )
            raise _map_identity_error(exc) from None

        if require_scope and scope not in (exchanged.scope or "").split():
            logger.warning(
                "kunlian knowledge token missing required scope user_id={} trace_id={} expected_scope={}",
                actor.user_id,
                sanitize_log_field(trace_id),
                sanitize_log_field(scope),
            )
            raise PlatformKnowledgePermissionError()
        return exchanged

    async def list_knowledge(self, actor: KnowledgeActor, cursor: str | None, name: str | None) -> dict:
        trace_id = uuid4().hex
        exchanged = await self._exchange_token(actor, scope=SCOPE_RESOURCES_READ, trace_id=trace_id)
        try:
            return await self.client.list_knowledge(
                exchanged.access_token,
                cursor=cursor,
                name=name,
                trace_id=trace_id,
            )
        except PlatformKnowledgeConfigurationError:
            # 兼容网关按文档只认 resource_type 参数（无 action）的情况。
            return await self.client.list_knowledge(
                exchanged.access_token,
                cursor=cursor,
                name=name,
                type_param_name="resource_type",
                trace_id=trace_id,
            )

    async def _find_in_directory(self, actor: KnowledgeActor, resource_id: str, *, trace_id: str) -> dict[str, Any]:
        target = resource_id.strip()
        if not target:
            raise PlatformKnowledgeConfigurationError()
        cursor: str | None = None
        seen_cursors: set[str] = set()
        exchanged = await self._exchange_token(actor, scope=SCOPE_RESOURCES_READ, trace_id=trace_id)
        type_param = "types"
        for _ in range(_MAX_DIRECTORY_SCAN_PAGES):
            try:
                page = await self.client.list_knowledge(
                    exchanged.access_token,
                    cursor=cursor,
                    page_size=100,
                    type_param_name=type_param,
                    trace_id=trace_id,
                )
            except PlatformKnowledgeConfigurationError:
                if type_param == "resource_type":
                    raise
                type_param = "resource_type"
                page = await self.client.list_knowledge(
                    exchanged.access_token,
                    cursor=cursor,
                    page_size=100,
                    type_param_name=type_param,
                    trace_id=trace_id,
                )
            for item in page["items"]:
                if item["resource_id"] == target:
                    return item
            next_cursor = page.get("next_cursor")
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise PlatformKnowledgeResourceError()

    async def get_knowledge(self, actor: KnowledgeActor, resource_id: str) -> dict:
        trace_id = uuid4().hex
        item = await self._find_in_directory(actor, resource_id, trace_id=trace_id)
        if not item.get("use_allowed", True) or item.get("status") != "active":
            raise PlatformKnowledgePermissionError()
        return item

    async def check_use(self, actor: KnowledgeActor, resource_id: str) -> None:
        await self.get_knowledge(actor, resource_id)

    async def retrieve(
        self,
        actor: KnowledgeActor,
        resource_id: str,
        query: str,
        top_k: int,
        call_id: str,
        *,
        version_id: str | None = None,
        workflow_run_id: str | None = None,
        node_run_id: str | None = None,
    ) -> list[dict]:
        trace_id = uuid4().hex
        resolved_version = version_id.strip() if isinstance(version_id, str) and version_id.strip() else ""
        if not resolved_version:
            item = await self.get_knowledge(actor, resource_id)
            resolved_version = item["version_id"]

        exchanged = await self._exchange_token(
            actor,
            scope=SCOPE_KNOWLEDGE_RETRIEVE,
            trace_id=trace_id,
            require_scope=True,
        )
        wf_run = (workflow_run_id or "").strip() or trace_id
        nd_run = (node_run_id or "").strip() or call_id or trace_id
        result = await self.client.retrieve_chunks(
            exchanged.access_token,
            resource_id=resource_id,
            version_id=resolved_version,
            query=query,
            top_k=top_k,
            workflow_run_id=wf_run,
            node_run_id=nd_run,
            trace_id=trace_id,
        )
        return result.items
