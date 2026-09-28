"""Platform adapters for E+ configuration and worker target notifications."""

from __future__ import annotations

import json
import logging

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.database.models.assistant import Assistant, AssistantStatus
from bisheng.eplus.domain.schemas.config import AssistantSnapshot, EPlusBindableSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.permission.application.business_authorization import require_business_action

logger = logging.getLogger(__name__)

EPLUS_CONFIG_CHANGED_CHANNEL = "eplus:config_changed"


class BusinessAssistantPermissionChecker:
    def __init__(self, login_user: UserPayload) -> None:
        self._login_user = login_user

    async def require_assistant_edit(
        self,
        *,
        tenant_id: int,
        assistant_id: str,
        operator_id: int,
        action: str,
    ) -> None:
        if int(operator_id) != int(self._login_user.user_id):
            raise ValueError("operator does not match the authenticated user")
        await require_business_action(
            self._login_user,
            resource_type="assistant",
            resource_id=assistant_id,
            action=action,
        )


class SqlAssistantReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_assistant(self, *, tenant_id: int, assistant_id: str) -> AssistantSnapshot | None:
        row = (
            await self._session.exec(
                select(Assistant).where(
                    Assistant.id == str(assistant_id),
                    Assistant.tenant_id == int(tenant_id),
                )
            )
        ).first()
        if row is None:
            return None
        return AssistantSnapshot(
            assistant_id=str(row.id),
            tenant_id=int(row.tenant_id),
            is_deleted=bool(row.is_delete),
            is_online=row.status == AssistantStatus.ONLINE.value,
        )


class SqlSpaceReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def require_valid_spaces(self, *, tenant_id: int, space_ids: tuple[int, ...]) -> None:
        if not space_ids:
            return
        rows = await self._session.exec(
            select(Knowledge.id).where(
                Knowledge.tenant_id == int(tenant_id),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                col(Knowledge.id).in_(space_ids),
            )
        )
        valid_ids = {int(space_id) for space_id in rows.all()}
        invalid_ids = sorted(set(space_ids) - valid_ids)
        if invalid_ids:
            raise ValueError(f"invalid knowledge spaces: {invalid_ids}")

    async def list_valid_spaces(self, *, tenant_id: int) -> tuple[EPlusBindableSpace, ...]:
        rows = await self._session.exec(
            select(Knowledge.id, Knowledge.name)
            .where(
                Knowledge.tenant_id == int(tenant_id),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
            .order_by(Knowledge.name.asc(), Knowledge.id.asc())
        )
        return tuple(EPlusBindableSpace(id=int(space_id), name=str(name)) for space_id, name in rows.all())


class RedisConfigNotifier:
    def __init__(self, redis_client: RedisClient) -> None:
        self._redis_client = redis_client

    async def config_changed(self, event: dict[str, int | str]) -> None:
        await self._redis_client.apublish(
            EPLUS_CONFIG_CHANGED_CHANNEL,
            json.dumps(event, separators=(",", ":"), ensure_ascii=True),
        )


async def notify_eplus_assistant_target_changed(*, tenant_id: int, assistant_id: str) -> None:
    """Best-effort wakeup; the worker's periodic reconciliation remains authoritative."""

    try:
        redis_client = await get_redis_client()
        await RedisConfigNotifier(redis_client).config_changed(
            {
                "tenant_id": int(tenant_id),
                "assistant_id": str(assistant_id),
            }
        )
    except Exception as exc:
        logger.warning(
            "E+ assistant target notification failed for assistant_id=%s: %s",
            assistant_id,
            type(exc).__name__,
        )
