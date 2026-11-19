"""昆联工作流资料同步事件构造、持久入队与异步投递服务。"""

from __future__ import annotations

from asyncio import to_thread
from datetime import datetime, timezone
import json
import re
from uuid import uuid4

from loguru import logger
from sqlmodel import select

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.workflow.domain.clients.kunlian_snapshot import (
    KunlianSnapshotCallbackClient,
    SnapshotCallbackConfig,
)
from bisheng.workflow.domain.repositories.kunlian_snapshot_outbox import (
    KunlianSnapshotOutboxRepository,
)

# 文档建议的退避重试间隔（秒）：1、5、30、120、600
RETRY_BACKOFF_SECONDS = (1, 5, 30, 120, 600)

_WORKFLOW_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_DESCRIPTION_BYTES = 65536


def _format_occurred_at(dt: datetime | None = None) -> str:
    target = dt or datetime.now(timezone.utc)
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    else:
        target = target.astimezone(timezone.utc)
    return target.strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _sanitize_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _CONTROL_CHAR_RE.sub("", str(value))
    if not cleaned.strip():
        return None
    return cleaned[:128]


def _sanitize_description(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = str(value).replace("\x00", "")
    return _truncate_utf8(cleaned, _MAX_DESCRIPTION_BYTES)


def build_snapshot_event(
    *,
    workflow_id: str,
    actor_sub: str,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
    include_name: bool = False,
    name: str | None = None,
    include_description: bool = False,
    description: str | None = None,
    include_version: bool = False,
    current_version_id: int | str | None = None,
    current_version_name: str | None = None,
    include_status: bool = False,
    status: int | None = None,
) -> dict | None:
    """按昆联接口契约构造快照同步事件正文，不输出 null 或额外字段。"""
    normalized_workflow_id = str(workflow_id or "").strip().lower()
    normalized_actor_sub = str(actor_sub or "").strip()
    if not _WORKFLOW_ID_RE.match(normalized_workflow_id) or not normalized_actor_sub:
        return None

    payload: dict[str, object] = {
        "event_id": event_id or f"workflow-sync-{uuid4().hex}",
        "workflow_id": normalized_workflow_id,
        "actor_sub": normalized_actor_sub,
        "occurred_at": _format_occurred_at(occurred_at),
    }

    has_optional = False

    if include_name:
        sanitized_name = _sanitize_name(name)
        if sanitized_name is not None:
            payload["name"] = sanitized_name
            has_optional = True

    if include_description:
        payload["description"] = _sanitize_description(description)
        has_optional = True

    if include_version:
        version_id_str = "" if current_version_id is None else str(current_version_id).strip()
        version_name_clean = _sanitize_name(current_version_name)
        if version_id_str.isdigit() and int(version_id_str) > 0 and len(version_id_str) <= 19 and version_name_clean:
            payload["current_version_id"] = version_id_str
            payload["current_version_name"] = version_name_clean
            has_optional = True
        else:
            # 无当前版本时，版本 ID 与名称同时传空串，并同时传 status=1
            payload["current_version_id"] = ""
            payload["current_version_name"] = ""
            payload["status"] = 1
            has_optional = True

    if include_status and status in (1, 2):
        # 若上面已因无当前版本强制 status=1，则保持 status=1
        if "status" not in payload:
            payload["status"] = int(status)
            has_optional = True

    if not has_optional:
        return None
    return payload


def serialize_snapshot_event(event: dict) -> str:
    """按规范序列化一次，保证签名与重试发送字节完全一致。"""
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def compute_retry_delay(attempts_completed: int) -> int:
    """根据已完成尝试次数计算退避间隔（1, 5, 30, 120, 600 秒）。"""
    index = max(0, min(int(attempts_completed), len(RETRY_BACKOFF_SECONDS) - 1))
    return RETRY_BACKOFF_SECONDS[index]


async def resolve_actor_kunlian_sub(user_id: int) -> str | None:
    """从 KunlianIdentityBinding 查询当前操作用户的真实昆联 OIDC sub。"""
    if not isinstance(user_id, int) or user_id <= 0:
        return None
    from bisheng.common.services.config_service import settings
    from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding

    connection_id = (getattr(settings.sso_sync.kunlian, "connection_id", "") or "").strip()
    with tenant_execution_scope(1):
        async with get_async_db_session() as session:
            stmt = select(KunlianIdentityBinding).where(KunlianIdentityBinding.local_user_id == user_id)
            if connection_id:
                stmt = stmt.where(KunlianIdentityBinding.connection_id == connection_id)
            row = (await session.exec(stmt.limit(1))).first()
            if row is None or not row.subject:
                return None
            return str(row.subject).strip() or None


def _dispatch_delivery_task(tenant_id: int, event_id: str) -> None:
    from bisheng.worker.workflow.kunlian_snapshot import deliver_workflow_snapshot

    deliver_workflow_snapshot.apply_async(
        args=[event_id],
        queue="celery",
        headers={"tenant_id": tenant_id},
    )


class KunlianWorkflowSnapshotSyncService:
    """编排昆联工作流快照同步的入队、派发、投递与扫表重试。"""

    def __init__(
        self,
        *,
        repository: KunlianSnapshotOutboxRepository | None = None,
        config_loader=None,
        client_factory=None,
        actor_sub_resolver=None,
        dispatcher=None,
    ):
        self.repository = repository or KunlianSnapshotOutboxRepository()
        self._config_loader = config_loader or SnapshotCallbackConfig.from_env
        self._client_factory = client_factory or (lambda cfg: KunlianSnapshotCallbackClient(cfg))
        self._actor_sub_resolver = actor_sub_resolver or resolve_actor_kunlian_sub
        self._dispatcher = dispatcher or _dispatch_delivery_task

    async def enqueue_snapshot(
        self,
        *,
        tenant_id: int | None,
        user_id: int | None,
        workflow_id: str,
        include_name: bool = False,
        name: str | None = None,
        include_description: bool = False,
        description: str | None = None,
        include_version: bool = False,
        current_version_id: int | str | None = None,
        current_version_name: str | None = None,
        include_status: bool = False,
        status: int | None = None,
        occurred_at: datetime | None = None,
    ) -> str | None:
        """构造事件并写入持久 Outbox，随后触发异步派发。

        未配置回调环境变量或操作者无昆联 OIDC 绑定时静默跳过，不阻断业务保存。
        """
        config = self._config_loader()
        if config is None:
            return None
        if not tenant_id or not user_id:
            return None

        actor_sub = await self._actor_sub_resolver(int(user_id))
        if not actor_sub:
            return None

        event = build_snapshot_event(
            workflow_id=workflow_id,
            actor_sub=actor_sub,
            occurred_at=occurred_at,
            include_name=include_name,
            name=name,
            include_description=include_description,
            description=description,
            include_version=include_version,
            current_version_id=current_version_id,
            current_version_name=current_version_name,
            include_status=include_status,
            status=status,
        )
        if event is None:
            return None

        payload_json = serialize_snapshot_event(event)
        event_id = str(event["event_id"])
        await self.repository.enqueue(
            tenant_id=int(tenant_id),
            workflow_id=str(event["workflow_id"]),
            actor_sub=actor_sub,
            event_id=event_id,
            payload_json=payload_json,
        )
        logger.info(
            "kunlian_snapshot_enqueued event_id={} workflow_id={} tenant_id={}",
            event_id,
            event["workflow_id"],
            tenant_id,
        )
        try:
            self._dispatcher(int(tenant_id), event_id)
        except Exception as exc:
            # 持久表已落盘，Broker 异常时交由 Beat 兜底扫表重试
            logger.warning(
                "kunlian_snapshot_dispatch_deferred event_id={} workflow_id={} error={}",
                event_id,
                event["workflow_id"],
                type(exc).__name__,
            )
        return event_id

    async def deliver_event(
        self,
        tenant_id: int,
        event_id: str,
        *,
        ignore_schedule: bool = False,
    ) -> str | None:
        """认领并投递单条持久化事件，按 HTTP 响应分类更新状态。"""
        config = self._config_loader()
        if config is None:
            return None

        claimed = await self.repository.claim_by_event_id(
            tenant_id,
            event_id,
            ignore_schedule=ignore_schedule,
        )
        if claimed is None:
            return None

        client = self._client_factory(config)
        result = await to_thread(
            client.send,
            event_id=claimed.event_id,
            payload_json=claimed.payload_json,
        )

        if result.outcome == "delivered":
            await self.repository.mark_delivered(
                tenant_id,
                claimed.event_id,
                status_code=result.status_code or 202,
                request_id=result.request_id,
            )
            logger.info(
                "kunlian_snapshot_delivered event_id={} workflow_id={} http_status={} request_id={}",
                claimed.event_id,
                claimed.workflow_id,
                result.status_code,
                result.request_id,
            )
            return "delivered"

        if result.outcome == "retry":
            delay = compute_retry_delay(claimed.attempts)
            await self.repository.mark_retry(
                tenant_id,
                claimed.event_id,
                delay_seconds=delay,
                status_code=result.status_code,
                request_id=result.request_id,
                error=result.error,
            )
            logger.warning(
                "kunlian_snapshot_retry_scheduled event_id={} workflow_id={} attempt={} delay_s={} http_status={} request_id={} error={}",
                claimed.event_id,
                claimed.workflow_id,
                claimed.attempts + 1,
                delay,
                result.status_code,
                result.request_id,
                result.error,
            )
            return "retry"

        await self.repository.mark_failed(
            tenant_id,
            claimed.event_id,
            status_code=result.status_code,
            request_id=result.request_id,
            error=result.error,
        )
        logger.error(
            "kunlian_snapshot_failed event_id={} workflow_id={} http_status={} request_id={} error={}",
            claimed.event_id,
            claimed.workflow_id,
            result.status_code,
            result.request_id,
            result.error,
        )
        return "failed"

    async def reconcile_due_events(self, *, limit: int = 100) -> int:
        """扫描已到期的 PENDING/RETRYING 事件并逐条派发投递。"""
        if self._config_loader() is None:
            return 0
        references = await self.repository.list_due_references(limit=limit)
        dispatched = 0
        for tenant_id, event_id in references:
            try:
                self._dispatcher(tenant_id, event_id)
                dispatched += 1
            except Exception as exc:
                logger.warning(
                    "kunlian_snapshot_reconcile_dispatch_failed event_id={} error={}",
                    event_id,
                    type(exc).__name__,
                )
        return dispatched


_default_service = KunlianWorkflowSnapshotSyncService()


def get_kunlian_snapshot_sync_service() -> KunlianWorkflowSnapshotSyncService:
    return _default_service


async def notify_kunlian_workflow_snapshot_safe(**kwargs) -> str | None:
    """安全触发入口：异常隔离，确保任何回调入队异常不阻断工作流主保存流程。"""
    try:
        return await get_kunlian_snapshot_sync_service().enqueue_snapshot(**kwargs)
    except Exception as exc:
        logger.warning(
            "kunlian_snapshot_enqueue_failed workflow_id={} error={}",
            kwargs.get("workflow_id"),
            type(exc).__name__,
        )
        return None
