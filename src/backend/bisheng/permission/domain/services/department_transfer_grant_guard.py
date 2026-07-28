from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import select

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import UserDepartment
from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
    DepartmentTransferCleanupItemType,
)
from bisheng.permission.domain.repositories.implementations.department_transfer_permission_cleanup_repository_impl import (
    DepartmentTransferPermissionCleanupRepositoryImpl,
)
from bisheng.permission.domain.services.department_transfer_permission_snapshot_service import (
    DepartmentTransferPermissionSnapshotService,
)


class DepartmentTransferGrantRetryableError(RuntimeError):
    """授权与主部门切换并发, 调用方应稍后重试。"""


@dataclass(frozen=True)
class KnowledgeGrantSignature:
    resource_type: str
    resource_id: str
    relation: str
    model_id: str | None = None


class _DepartmentTransferUserLock:
    def __init__(self, user_id: int, *, ttl_seconds: int = 15):
        self.key = f"permission:department_transfer:user:{user_id}:lock"
        self.ttl_seconds = ttl_seconds
        self.token = secrets.token_hex(16)
        self.redis_client = None

    async def __aenter__(self):
        try:
            self.redis_client = await get_redis_client()
            acquired = await self.redis_client.async_connection.set(
                self.key,
                self.token,
                nx=True,
                ex=self.ttl_seconds,
            )
        except Exception as exc:
            raise DepartmentTransferGrantRetryableError(
                "department transfer permission lock is unavailable"
            ) from exc
        if not acquired:
            raise DepartmentTransferGrantRetryableError("department transfer permission lock is busy")
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if self.redis_client is None:
            return
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """
        await self.redis_client.async_connection.eval(script, 1, self.key, self.token)


class DepartmentTransferGrantGuard:
    def __init__(
        self,
        *,
        repository,
        current_department_loader: Callable[[int], Awaitable[int | None]],
        lock_factory: Callable[[int], AbstractAsyncContextManager] | None = None,
    ):
        self.repository = repository
        self.current_department_loader = current_department_loader
        self.lock_factory = lock_factory or _DepartmentTransferUserLock

    async def protect_knowledge_grants(
        self,
        *,
        user_id: int,
        grants: list[KnowledgeGrantSignature],
        source: str,
        operation_id: str,
        lock_held: bool = False,
    ) -> None:
        if not grants:
            return
        if lock_held:
            await self._protect_knowledge_grants_locked(
                user_id=user_id,
                grants=grants,
                source=source,
                operation_id=operation_id,
            )
            return
        async with self.lock_factory(user_id):
            await self._protect_knowledge_grants_locked(
                user_id=user_id,
                grants=grants,
                source=source,
                operation_id=operation_id,
            )

    async def _protect_knowledge_grants_locked(
        self,
        *,
        user_id: int,
        grants: list[KnowledgeGrantSignature],
        source: str,
        operation_id: str,
    ) -> None:
        events = await self._active_events_after_transfer(user_id)
        now = datetime.now()
        for event in events:
            for grant in grants:
                await self.repository.protect_item(
                    event_id=int(event.id),
                    item_key=DepartmentTransferPermissionSnapshotService.knowledge_item_key(
                        grant.resource_type,
                        grant.resource_id,
                        grant.relation,
                    ),
                    source=source[:32],
                    protected_at=now,
                    tenant_id=int(event.tenant_id or 1),
                    user_id=user_id,
                    item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
                    resource_type=grant.resource_type,
                    resource_id=str(grant.resource_id),
                    relation=grant.relation,
                    snapshot={
                        "model_id": grant.model_id,
                        "operation_id": operation_id[:128],
                        "post_transfer_grant": True,
                    },
                )
                if grant.resource_type == "knowledge_space":
                    await self.repository.protect_item(
                        event_id=int(event.id),
                        item_key=DepartmentTransferPermissionSnapshotService.space_membership_item_key(
                            grant.resource_id,
                        ),
                        source=source[:32],
                        protected_at=now,
                        tenant_id=int(event.tenant_id or 1),
                        user_id=user_id,
                        item_type=DepartmentTransferCleanupItemType.SPACE_MEMBERSHIP,
                        resource_type="knowledge_space",
                        resource_id=str(grant.resource_id),
                        relation=grant.relation,
                        snapshot={
                            "operation_id": operation_id[:128],
                            "post_transfer_grant": True,
                        },
                    )

    async def protect_department_file_grant(
        self,
        *,
        user_id: int,
        space_id: int,
        file_id: int,
        approval_instance_id: int,
    ) -> None:
        async with self.lock_factory(user_id):
            events = await self._active_events_after_transfer(user_id)
            now = datetime.now()
            for event in events:
                await self.repository.protect_item(
                    event_id=int(event.id),
                    item_key=DepartmentTransferPermissionSnapshotService.department_file_item_key(
                        space_id,
                        file_id,
                    ),
                    source="approval",
                    protected_at=now,
                    tenant_id=int(event.tenant_id or 1),
                    user_id=user_id,
                    item_type=DepartmentTransferCleanupItemType.DEPARTMENT_FILE_GRANT,
                    resource_type="knowledge_file",
                    resource_id=str(file_id),
                    relation="viewer",
                    snapshot={
                        "space_id": int(space_id),
                        "approval_instance_id": int(approval_instance_id),
                        "post_transfer_grant": True,
                    },
                )

    async def _active_events_after_transfer(self, user_id: int) -> list:
        events = await self.repository.list_active_events_for_user(user_id=user_id)
        current_department_id: int | None = None
        ready = []
        for event in events:
            if event.status != DepartmentTransferCleanupEventStatus.PREPARING:
                ready.append(event)
                continue
            if current_department_id is None:
                current_department_id = await self.current_department_loader(user_id)
            if current_department_id == int(event.old_department_id):
                raise DepartmentTransferGrantRetryableError("primary department change is preparing")
            if current_department_id is None:
                raise DepartmentTransferGrantRetryableError("primary department state is unavailable")
            changed_at = datetime.now()
            await self.repository.activate_event(
                int(event.id),
                changed_at=changed_at,
                deadline_at=changed_at + timedelta(minutes=5),
            )
            ready.append(event)
        return ready


async def protect_knowledge_direct_grants(
    *,
    user_id: int,
    grants: list[KnowledgeGrantSignature],
    source: str,
    operation_id: str,
    lock_held: bool = False,
) -> None:
    if not grants:
        return
    async with get_async_db_session() as session:
        repository = DepartmentTransferPermissionCleanupRepositoryImpl(session)

        async def _load_primary(target_user_id: int) -> int | None:
            result = await session.execute(
                select(UserDepartment.department_id).where(
                    UserDepartment.user_id == target_user_id,
                    UserDepartment.is_primary == 1,
                )
            )
            value = result.scalar_one_or_none()
            return int(value) if value is not None else None

        guard = DepartmentTransferGrantGuard(
            repository=repository,
            current_department_loader=_load_primary,
        )
        await guard.protect_knowledge_grants(
            user_id=user_id,
            grants=grants,
            source=source,
            operation_id=operation_id,
            lock_held=lock_held,
        )
        await session.commit()


async def protect_department_file_grant(
    *,
    user_id: int,
    space_id: int,
    file_id: int,
    approval_instance_id: int,
) -> None:
    async with get_async_db_session() as session:
        repository = DepartmentTransferPermissionCleanupRepositoryImpl(session)

        async def _load_primary(target_user_id: int) -> int | None:
            result = await session.execute(
                select(UserDepartment.department_id).where(
                    UserDepartment.user_id == target_user_id,
                    UserDepartment.is_primary == 1,
                )
            )
            value = result.scalar_one_or_none()
            return int(value) if value is not None else None

        guard = DepartmentTransferGrantGuard(
            repository=repository,
            current_department_loader=_load_primary,
        )
        await guard.protect_department_file_grant(
            user_id=user_id,
            space_id=space_id,
            file_id=file_id,
            approval_instance_id=approval_instance_id,
        )
        await session.commit()
