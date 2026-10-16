"""Temporary sessions for debug windows and single-node tests (F078 design decision 8).

A debug run has no chat id, so nothing in the database says who may download
its files. The owner is registered in Redis instead, with a 24-hour TTL that
every run refreshes. Clean-up happens in three places:

1. the WebSocket closes (``aclose``);
2. the tmp bucket's 7-day lifecycle rule removes deliverables left behind;
3. a Beat sweep removes workspaces whose registration has expired.
"""

from __future__ import annotations

import asyncio
import uuid

from loguru import logger

from bisheng.agent_runtime.domain.services.agent_workspace import adelete_session_workspaces

TMP_SESSION_TTL_SECONDS = 24 * 60 * 60
_KEY_PREFIX = "agent_runtime:tmp_session:"


def tmp_session_key(tmp_id: str) -> str:
    """Workspace session key of a temporary session."""
    return f"tmp-{tmp_id}"


def tmp_deliverable_dir(tmp_id: str) -> str:
    """Tmp-bucket directory that holds a temporary session's deliverables."""
    return f"agent_runtime/{tmp_session_key(tmp_id)}"


def _registration_key(tmp_id: str) -> str:
    return f"{_KEY_PREFIX}{tmp_id}"


def _remove_tmp_bucket_dir(minio, prefix: str) -> int:
    objects = minio.minio_client_sync.list_objects(minio.tmp_bucket, prefix=prefix, recursive=True)
    names = [obj.object_name for obj in objects]
    for name in names:
        minio.remove_object_sync(bucket_name=minio.tmp_bucket, object_name=name)
    return len(names)


class TmpSessionService:
    def __init__(self, redis, minio) -> None:
        self.redis = redis
        self.minio = minio

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    async def aregister(self, tmp_id: str, *, user_id: int, tenant_id: int) -> None:
        """Register (or refresh) the owner of a temporary session."""
        await self.redis.aset(
            _registration_key(tmp_id),
            {"user_id": int(user_id), "tenant_id": int(tenant_id)},
            expiration=TMP_SESSION_TTL_SECONDS,
        )

    async def aowner_of(self, tmp_id: str) -> dict | None:
        return await self.redis.aget(_registration_key(tmp_id))

    async def aexists(self, tmp_id: str) -> bool:
        return bool(await self.redis.aexists(_registration_key(tmp_id)))

    async def aclose(self, tmp_id: str) -> None:
        """Delete the session's workspaces, deliverables and registration."""
        workspaces = await adelete_session_workspaces(self.minio, tmp_session_key(tmp_id))
        deliverables = await asyncio.to_thread(_remove_tmp_bucket_dir, self.minio, f"{tmp_deliverable_dir(tmp_id)}/")
        await self.redis.adelete(_registration_key(tmp_id))
        logger.info(
            "act=agent_tmp_session_close tmp_id={} workspaces={} deliverables={}", tmp_id, workspaces, deliverables
        )
