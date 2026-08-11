from __future__ import annotations

import mimetypes
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Protocol
from urllib.parse import quote
from uuid import UUID, uuid4

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import (
    SpaceFileChangeInvalidStateError,
    SpaceFileSizeLimitError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import (
    KnowledgeSpaceUploadStage,
    KnowledgeSpaceUploadStageState,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_repository import (
    KnowledgeSpaceFileChangeRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
    KnowledgeSpaceUploadStageRepository,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class UploadStageStorage(Protocol):
    bucket: str
    tmp_bucket: str

    async def copy_object(
        self,
        source_bucket: str,
        source_object: str,
        dest_bucket: str,
        dest_object: str,
    ) -> None: ...

    async def remove_object(self, bucket_name: str, object_name: str) -> None: ...

    async def object_exists(self, bucket_name: str, object_name: str) -> bool: ...

    async def get_share_link(
        self,
        object_name: str,
        bucket: str,
        expire_days: int,
        response_headers: dict[str, str] | None = None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class KnowledgeSpaceUploadCapacity:
    """Authoritative formal usage and byte caps loaded while the tenant lock is held."""

    user_used_bytes: int = 0
    user_limit_bytes: int | None = None
    tenant_used_bytes: int = 0
    tenant_limit_bytes: int | None = None


CapacityLoader = Callable[[int, int], Awaitable[KnowledgeSpaceUploadCapacity]]


class KnowledgeSpaceUploadStageService:
    """Own opaque staged objects without exposing their storage references."""

    _OBJECT_PREFIX = "knowledge-space-upload-stage/"

    _PREVIEWABLE_STATES = {
        KnowledgeSpaceUploadStageState.UPLOADED,
        KnowledgeSpaceUploadStageState.ATTACHING,
        KnowledgeSpaceUploadStageState.ATTACHED,
    }

    def __init__(
        self,
        *,
        storage: UploadStageStorage,
        capacity_loader: CapacityLoader,
        session_factory: SessionFactory = get_async_db_session,
        upload_id_factory: Callable[[], str] = lambda: str(uuid4()),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        stage_ttl: timedelta = timedelta(days=3),
        preview_expire_days: int = 1,
    ) -> None:
        self.storage = storage
        self.session_factory = session_factory
        self.capacity_loader = capacity_loader
        self.upload_id_factory = upload_id_factory
        self.now = now
        self.stage_ttl = stage_ttl
        self.preview_expire_days = preview_expire_days

    @staticmethod
    def _tenant_id() -> int:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise RuntimeError("tenant context is required for upload stage")
        return int(tenant_id)

    @staticmethod
    def _normalize_upload_id(upload_id: str) -> str:
        normalized = str(UUID(str(upload_id)))
        if len(normalized) > 64:  # pragma: no cover - UUID normalization is fixed width
            raise ValueError("upload_id exceeds storage limit")
        return normalized

    def _new_upload_id(self) -> str:
        return self._normalize_upload_id(self.upload_id_factory())

    @staticmethod
    def _file_suffix(file_name: str) -> str:
        normalized_name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
        suffix = PurePath(normalized_name).suffix
        if not suffix or len(suffix) > 32 or not suffix[1:].isalnum():
            return ""
        return suffix

    @classmethod
    def _permanent_object_name(cls, *, tenant_id: int, upload_id: str, file_name: str) -> str:
        return f"{cls._OBJECT_PREFIX}{tenant_id}/{upload_id}{cls._file_suffix(file_name)}"

    @staticmethod
    def _preview_response_headers(file_name: str) -> dict[str, str]:
        safe_name = str(file_name or "file").replace("\\", "/").rsplit("/", 1)[-1]
        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        return {
            "response-content-disposition": f"inline; filename*=UTF-8''{quote(safe_name, safe='')}",
            "response-content-type": content_type,
        }

    @staticmethod
    def _is_same_upload(
        stage: KnowledgeSpaceUploadStage,
        *,
        space_id: int,
        uploader_user_id: int,
        file_name: str,
        file_size: int,
        content_hash: str,
    ) -> bool:
        return (
            int(stage.space_id) == int(space_id)
            and int(stage.uploader_user_id) == int(uploader_user_id)
            and stage.file_name == file_name
            and int(stage.file_size) == int(file_size)
            and stage.content_hash == content_hash
        )

    async def create_stage(
        self,
        *,
        space_id: int,
        uploader_user_id: int,
        file_name: str,
        file_size: int,
        content_hash: str,
        temporary_object_name: str,
        upload_id: str | None = None,
    ) -> KnowledgeSpaceUploadStage:
        tenant_id = self._tenant_id()
        if not file_name or not file_name.strip():
            raise ValueError("file_name is required")
        if file_size < 0:
            raise ValueError("file_size cannot be negative")
        if not content_hash:
            raise ValueError("content_hash is required")
        if (
            not temporary_object_name
            or "/" in temporary_object_name
            or "\\" in temporary_object_name
            or temporary_object_name in {".", ".."}
        ):
            raise ValueError("temporary_object_name is invalid")

        file_name = file_name.strip()
        candidate_upload_id = self._normalize_upload_id(upload_id) if upload_id else self._new_upload_id()
        async with self.session_factory() as session:
            async with session.begin():
                policy_repository = KnowledgeSpaceFileChangeRepository(session)
                await policy_repository.ensure_policy_row(tenant_id=tenant_id, for_update=True)
                repository = KnowledgeSpaceUploadStageRepository(session)
                existing = await repository.get_by_upload_id(
                    tenant_id=tenant_id,
                    upload_id=candidate_upload_id,
                    for_update=True,
                )
                if existing is not None:
                    if self._is_same_upload(
                        existing,
                        space_id=space_id,
                        uploader_user_id=uploader_user_id,
                        file_name=file_name,
                        file_size=file_size,
                        content_hash=content_hash,
                    ):
                        return existing
                    if (
                        int(existing.space_id) != int(space_id)
                        or int(existing.uploader_user_id) != int(uploader_user_id)
                        or existing.file_name != file_name
                    ):
                        raise ValueError("upload_id belongs to a different staged upload")
                    candidate_upload_id = await self._next_unused_upload_id(
                        repository=repository,
                        tenant_id=tenant_id,
                    )

                capacity = await self.capacity_loader(tenant_id, int(uploader_user_id))
                await self._require_capacity(
                    repository=repository,
                    tenant_id=tenant_id,
                    uploader_user_id=int(uploader_user_id),
                    file_size=file_size,
                    capacity=capacity,
                )
                stage = KnowledgeSpaceUploadStage(
                    upload_id=candidate_upload_id,
                    tenant_id=tenant_id,
                    space_id=int(space_id),
                    uploader_user_id=int(uploader_user_id),
                    object_name=temporary_object_name,
                    file_name=file_name,
                    file_size=file_size,
                    content_hash=content_hash,
                    state=KnowledgeSpaceUploadStageState.UPLOADED,
                    expire_at=self.now() + self.stage_ttl,
                )
                return await repository.add(stage)

    async def _next_unused_upload_id(
        self,
        *,
        repository: KnowledgeSpaceUploadStageRepository,
        tenant_id: int,
    ) -> str:
        for _attempt in range(5):
            candidate = self._new_upload_id()
            if await repository.get_by_upload_id(tenant_id=tenant_id, upload_id=candidate) is None:
                return candidate
        raise RuntimeError("unable to allocate a unique upload_id")

    @staticmethod
    async def _require_capacity(
        *,
        repository: KnowledgeSpaceUploadStageRepository,
        tenant_id: int,
        uploader_user_id: int,
        file_size: int,
        capacity: KnowledgeSpaceUploadCapacity,
    ) -> None:
        reserved_user = await repository.get_reserved_bytes(
            tenant_id=tenant_id,
            uploader_user_id=uploader_user_id,
        )
        if (
            capacity.user_limit_bytes is not None
            and capacity.user_used_bytes + reserved_user + file_size > capacity.user_limit_bytes
        ):
            raise SpaceFileSizeLimitError()

        reserved_tenant = await repository.get_reserved_bytes(tenant_id=tenant_id)
        if (
            capacity.tenant_limit_bytes is not None
            and capacity.tenant_used_bytes + reserved_tenant + file_size > capacity.tenant_limit_bytes
        ):
            raise SpaceFileSizeLimitError()

    async def attach(self, upload_id: str) -> KnowledgeSpaceUploadStage:
        stage = await self._transition(
            upload_id=upload_id,
            allowed_from={KnowledgeSpaceUploadStageState.UPLOADED},
            target=KnowledgeSpaceUploadStageState.ATTACHING,
        )
        return await self.retain_bound_stage(stage.upload_id)

    async def retain_bound_stage(self, upload_id: str) -> KnowledgeSpaceUploadStage:
        """Copy a request-bound object from the temporary to permanent bucket.

        ``ATTACHING`` is durable, so a failed post-commit call can be retried by
        reconciliation. The deterministic destination makes every retry safe.
        """

        tenant_id = self._tenant_id()
        normalized_upload_id = self._normalize_upload_id(upload_id)
        async with self.session_factory() as session:
            repository = KnowledgeSpaceUploadStageRepository(session)
            stage = await self._require_stage(
                repository=repository,
                tenant_id=tenant_id,
                upload_id=normalized_upload_id,
            )
            if stage.state == KnowledgeSpaceUploadStageState.ATTACHED:
                return stage
            if stage.state != KnowledgeSpaceUploadStageState.ATTACHING:
                raise SpaceFileChangeInvalidStateError()
            temporary_object_name = stage.object_name
            permanent_object_name = self._permanent_object_name(
                tenant_id=tenant_id,
                upload_id=normalized_upload_id,
                file_name=stage.file_name,
            )

        await self.storage.copy_object(
            source_bucket=self.storage.tmp_bucket,
            source_object=temporary_object_name,
            dest_bucket=self.storage.bucket,
            dest_object=permanent_object_name,
        )

        async with self.session_factory() as session:
            async with session.begin():
                repository = KnowledgeSpaceUploadStageRepository(session)
                stage = await self._require_stage(
                    repository=repository,
                    tenant_id=tenant_id,
                    upload_id=normalized_upload_id,
                    for_update=True,
                )
                if stage.state == KnowledgeSpaceUploadStageState.ATTACHED:
                    return stage
                if stage.state != KnowledgeSpaceUploadStageState.ATTACHING:
                    raise SpaceFileChangeInvalidStateError()
                stage.object_name = permanent_object_name
                stage.state = KnowledgeSpaceUploadStageState.ATTACHED
                attached = await repository.save(stage)
        try:
            await self.storage.remove_object(self.storage.tmp_bucket, temporary_object_name)
        except Exception:
            logger.exception("failed to remove copied temporary upload object {}", temporary_object_name)
        return attached

    async def consume(self, upload_id: str) -> KnowledgeSpaceUploadStage:
        return await self._transition(
            upload_id=upload_id,
            allowed_from={KnowledgeSpaceUploadStageState.ATTACHED},
            target=KnowledgeSpaceUploadStageState.CONSUMED,
        )

    async def _transition(
        self,
        *,
        upload_id: str,
        allowed_from: set[str],
        target: str,
    ) -> KnowledgeSpaceUploadStage:
        tenant_id = self._tenant_id()
        normalized_upload_id = self._normalize_upload_id(upload_id)
        async with self.session_factory() as session:
            async with session.begin():
                await KnowledgeSpaceFileChangeRepository(session).ensure_policy_row(
                    tenant_id=tenant_id,
                    for_update=True,
                )
                repository = KnowledgeSpaceUploadStageRepository(session)
                stage = await self._require_stage(
                    repository=repository,
                    tenant_id=tenant_id,
                    upload_id=normalized_upload_id,
                    for_update=True,
                )
                if stage.state == target:
                    return stage
                if stage.state not in allowed_from:
                    raise SpaceFileChangeInvalidStateError()
                stage.state = target
                return await repository.save(stage)

    async def cleanup(self, upload_id: str) -> KnowledgeSpaceUploadStage:
        tenant_id = self._tenant_id()
        normalized_upload_id = self._normalize_upload_id(upload_id)
        async with self.session_factory() as session:
            async with session.begin():
                await KnowledgeSpaceFileChangeRepository(session).ensure_policy_row(
                    tenant_id=tenant_id,
                    for_update=True,
                )
                repository = KnowledgeSpaceUploadStageRepository(session)
                stage = await self._require_stage(
                    repository=repository,
                    tenant_id=tenant_id,
                    upload_id=normalized_upload_id,
                    for_update=True,
                )
                if stage.state == KnowledgeSpaceUploadStageState.CLEANED:
                    return stage
                if stage.state not in {
                    KnowledgeSpaceUploadStageState.UPLOADED,
                    KnowledgeSpaceUploadStageState.ATTACHING,
                    KnowledgeSpaceUploadStageState.ATTACHED,
                    KnowledgeSpaceUploadStageState.CONSUMED,
                    KnowledgeSpaceUploadStageState.CLEANUP_PENDING,
                }:
                    raise SpaceFileChangeInvalidStateError()
                stage.state = KnowledgeSpaceUploadStageState.CLEANUP_PENDING
                object_name = stage.object_name
                object_bucket = self._bucket_for_object(object_name)
                await repository.save(stage)

        await self.storage.remove_object(object_bucket, object_name)
        permanent_object_name = self._permanent_object_name(
            tenant_id=tenant_id,
            upload_id=normalized_upload_id,
            file_name=stage.file_name,
        )
        if object_bucket == self.storage.tmp_bucket:
            await self.storage.remove_object(self.storage.bucket, permanent_object_name)
            legacy_permanent_object_name = f"{self._OBJECT_PREFIX}{tenant_id}/{normalized_upload_id}"
            if legacy_permanent_object_name != permanent_object_name:
                await self.storage.remove_object(self.storage.bucket, legacy_permanent_object_name)

        async with self.session_factory() as session:
            async with session.begin():
                await KnowledgeSpaceFileChangeRepository(session).ensure_policy_row(
                    tenant_id=tenant_id,
                    for_update=True,
                )
                repository = KnowledgeSpaceUploadStageRepository(session)
                stage = await self._require_stage(
                    repository=repository,
                    tenant_id=tenant_id,
                    upload_id=normalized_upload_id,
                    for_update=True,
                )
                if stage.state == KnowledgeSpaceUploadStageState.CLEANED:
                    return stage
                if stage.state != KnowledgeSpaceUploadStageState.CLEANUP_PENDING:
                    raise SpaceFileChangeInvalidStateError()
                stage.state = KnowledgeSpaceUploadStageState.CLEANED
                return await repository.save(stage)

    async def reconcile_expired_orphan(self, upload_id: str) -> bool:
        """Release metadata only after MinIO lifecycle removed an orphan.

        The application deliberately does not delete the object here. Physical
        expiration belongs to MinIO; this method only reconciles the database
        row and reserved capacity after an authoritative absence check.
        """

        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )

        tenant_id = self._tenant_id()
        normalized_upload_id = self._normalize_upload_id(upload_id)
        async with self.session_factory() as session:
            async with session.begin():
                await KnowledgeSpaceFileChangeRepository(session).ensure_policy_row(
                    tenant_id=tenant_id,
                    for_update=True,
                )
                repository = KnowledgeSpaceUploadStageRepository(session)
                stage = await self._require_stage(
                    repository=repository,
                    tenant_id=tenant_id,
                    upload_id=normalized_upload_id,
                    for_update=True,
                )
                if stage.state == KnowledgeSpaceUploadStageState.CLEANED:
                    return True
                if stage.state not in {
                    KnowledgeSpaceUploadStageState.UPLOADED,
                    KnowledgeSpaceUploadStageState.CLEANUP_PENDING,
                }:
                    return False
                if not self._has_expired(stage.expire_at):
                    return False
                bound = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_upload_stage_id(
                    tenant_id=tenant_id,
                    upload_stage_id=int(stage.id),
                    for_update=True,
                )
                if bound is not None:
                    return False
                object_name = stage.object_name
        if await self.storage.object_exists(self.storage.tmp_bucket, object_name):
            return False

        async with self.session_factory() as session:
            async with session.begin():
                await KnowledgeSpaceFileChangeRepository(session).ensure_policy_row(
                    tenant_id=tenant_id,
                    for_update=True,
                )
                repository = KnowledgeSpaceUploadStageRepository(session)
                stage = await self._require_stage(
                    repository=repository,
                    tenant_id=tenant_id,
                    upload_id=normalized_upload_id,
                    for_update=True,
                )
                if stage.state == KnowledgeSpaceUploadStageState.CLEANED:
                    return True
                if stage.state not in {
                    KnowledgeSpaceUploadStageState.UPLOADED,
                    KnowledgeSpaceUploadStageState.CLEANUP_PENDING,
                }:
                    return False
                bound = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_upload_stage_id(
                    tenant_id=tenant_id,
                    upload_stage_id=int(stage.id),
                    for_update=True,
                )
                if bound is not None:
                    return False
                stage.state = KnowledgeSpaceUploadStageState.CLEANED
                await repository.save(stage)
                return True

    async def reconcile_lifecycle(self, upload_id: str) -> bool:
        """Repair one bounded lifecycle candidate without deleting objects."""

        tenant_id = self._tenant_id()
        normalized_upload_id = self._normalize_upload_id(upload_id)
        async with self.session_factory() as session:
            stage = await self._require_stage(
                repository=KnowledgeSpaceUploadStageRepository(session),
                tenant_id=tenant_id,
                upload_id=normalized_upload_id,
            )
            state = stage.state
        if state == KnowledgeSpaceUploadStageState.ATTACHING:
            await self.retain_bound_stage(normalized_upload_id)
            return True
        return await self.reconcile_expired_orphan(normalized_upload_id)

    def _has_expired(self, expire_at: datetime) -> bool:
        now = self.now()
        if expire_at.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif expire_at.tzinfo is not None and now.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=None)
        return expire_at <= now

    async def create_preview_url(
        self,
        upload_id: str,
        *,
        requester_user_id: int,
        can_manage_space: bool = False,
    ) -> str:
        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            repository = KnowledgeSpaceUploadStageRepository(session)
            stage = await self._require_stage(
                repository=repository,
                tenant_id=tenant_id,
                upload_id=self._normalize_upload_id(upload_id),
            )
            if stage.state not in self._PREVIEWABLE_STATES:
                raise SpaceFileChangeInvalidStateError()
            if int(stage.uploader_user_id) != int(requester_user_id) and not can_manage_space:
                raise PermissionError("requester is not authorized to preview this upload stage")
            return await self.storage.get_share_link(
                stage.object_name,
                bucket=self._bucket_for_object(stage.object_name),
                expire_days=self.preview_expire_days,
                response_headers=self._preview_response_headers(stage.file_name),
            )

    def _bucket_for_object(self, object_name: str) -> str:
        if object_name.startswith(self._OBJECT_PREFIX):
            return self.storage.bucket
        return self.storage.tmp_bucket

    @staticmethod
    async def _require_stage(
        *,
        repository: KnowledgeSpaceUploadStageRepository,
        tenant_id: int,
        upload_id: str,
        for_update: bool = False,
    ) -> KnowledgeSpaceUploadStage:
        stage = await repository.get_by_upload_id(
            tenant_id=tenant_id,
            upload_id=upload_id,
            for_update=for_update,
        )
        if stage is None:
            raise LookupError(f"upload stage not found: {upload_id}")
        return stage
