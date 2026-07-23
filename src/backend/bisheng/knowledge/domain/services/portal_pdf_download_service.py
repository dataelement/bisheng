from __future__ import annotations

import asyncio
import inspect
import secrets
import shutil
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.errcode.knowledge_space import (
    PortalPdfArtifactUnavailableError,
    PortalPdfDownloadBusyError,
    PortalPdfDownloadGenerationError,
    PortalPdfDownloadServiceUnavailableError,
    PortalPdfDownloadTimeoutError,
    SpaceFileNotFoundError,
)
from bisheng.common.schemas.telemetry.event_data_schema import PortalDocumentDownloadEventData
from bisheng.common.telemetry.portal_event_service import PortalTelemetryEventService
from bisheng.core.config.settings import KnowledgePdfWatermarkConf
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.schemas.portal_pdf_download_schema import (
    PortalPdfDownloadRequest,
    PreparedPortalPdfDownload,
)
from bisheng.knowledge.domain.services.knowledge_space_daily_download import (
    KnowledgeSpaceDailyDownloadCounter,
    enforce_knowledge_space_daily_download,
    record_knowledge_space_daily_download,
    resolve_knowledge_space_daily_download_limit,
    should_enforce_knowledge_space_daily_download,
)
from bisheng.knowledge.domain.services.pdf_artifact_on_demand_service import (
    PdfArtifactOnDemandGenerationError,
    PdfArtifactOnDemandServiceUnavailableError,
    PdfArtifactOnDemandTimeoutError,
)
from bisheng.knowledge.pdf.validator import PdfValidationError, validate_pdf
from bisheng.knowledge.pdf.watermark import PdfWatermarkSpec
from bisheng.knowledge.pdf.watermark_worker import (
    PdfWatermarkWorkerError,
    PdfWatermarkWorkerTimeout,
    run_watermark_worker,
)


class PortalPdfDownloadProcessCapacity:
    def __init__(self, limit: int) -> None:
        self.limit = max(int(limit), 1)
        self.active = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    def release(self) -> None:
        with self._lock:
            if self.active > 0:
                self.active -= 1


_CAPACITY_LOCK = threading.Lock()
_CAPACITY_LIMITERS: dict[int, PortalPdfDownloadProcessCapacity] = {}


def get_portal_pdf_download_capacity(limit: int) -> PortalPdfDownloadProcessCapacity:
    normalized = max(int(limit), 1)
    with _CAPACITY_LOCK:
        limiter = _CAPACITY_LIMITERS.get(normalized)
        if limiter is None:
            limiter = PortalPdfDownloadProcessCapacity(normalized)
            _CAPACITY_LIMITERS[normalized] = limiter
        return limiter


class PortalPdfDownloadUserLock:
    _RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = getattr(redis_client, "async_connection", redis_client)

    async def _connection(self) -> Any:
        if self._redis is None:
            from bisheng.core.cache.redis_manager import get_redis_client

            client = await get_redis_client()
            self._redis = client.async_connection
        return self._redis

    @staticmethod
    def _key(tenant_id: int, user_id: int) -> str:
        return f"bisheng:portal_pdf_download:user:{int(tenant_id)}:{int(user_id)}"

    async def acquire(self, *, tenant_id: int, user_id: int, ttl_seconds: int) -> str | None:
        token = secrets.token_urlsafe(18)
        try:
            redis = await self._connection()
            acquired = await redis.set(
                self._key(tenant_id, user_id),
                token,
                nx=True,
                ex=max(int(ttl_seconds), 1),
            )
        except Exception:
            raise PortalPdfDownloadServiceUnavailableError() from None
        return token if acquired else None

    async def release(self, *, tenant_id: int, user_id: int, token: str) -> None:
        try:
            redis = await self._connection()
            await redis.eval(
                self._RELEASE_SCRIPT,
                1,
                self._key(tenant_id, user_id),
                token,
            )
        except Exception:
            logger.error(
                "portal_pdf_download_lock_release_failed tenant_id={} user_id={}",
                tenant_id,
                user_id,
            )


class PortalPdfDownloadService:
    def __init__(
        self,
        *,
        config: KnowledgePdfWatermarkConf,
        file_repository: Any,
        user_repository: Any,
        authorization_service: Any,
        artifact_ensurer: Callable[..., Awaitable[Any]],
        artifact_readiness_timeout_seconds: int,
        storage: Any,
        share_grant_service: Any,
        user_lock: Any,
        capacity_limiter: PortalPdfDownloadProcessCapacity | None = None,
        watermark_runner: Callable[..., Any] = run_watermark_worker,
        telemetry_recorder: Callable[[dict[str, Any]], Any] | None = None,
        temp_root: str | Path | None = None,
        now_provider: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        daily_download_counter: Any | None = None,
        daily_limit_resolver: Callable[[Any], Awaitable[int]] | None = None,
    ) -> None:
        self.config = config
        self.file_repository = file_repository
        self.user_repository = user_repository
        self.authorization_service = authorization_service
        self.artifact_ensurer = artifact_ensurer
        self.artifact_readiness_timeout_seconds = max(int(artifact_readiness_timeout_seconds), 1)
        self.user_lock_ttl_seconds = max(
            int(config.user_lock_ttl_seconds),
            self.artifact_readiness_timeout_seconds + int(config.timeout_seconds) + 30,
        )
        self.storage = storage
        self.share_grant_service = share_grant_service
        self.user_lock = user_lock
        self.capacity_limiter = capacity_limiter or get_portal_pdf_download_capacity(config.max_concurrency)
        self.watermark_runner = watermark_runner
        self.telemetry_recorder = telemetry_recorder or self._record_download_telemetry
        self.temp_root = Path(temp_root).resolve() if temp_root is not None else None
        self.now_provider = now_provider or (lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
        self.monotonic = monotonic
        self.daily_download_counter = daily_download_counter or KnowledgeSpaceDailyDownloadCounter(
            now_provider=self.now_provider,
        )
        self.daily_limit_resolver = daily_limit_resolver

    async def _resolve_daily_limit(self, login_user: Any) -> int:
        if self.daily_limit_resolver is not None:
            return int(await self.daily_limit_resolver(login_user))
        return await resolve_knowledge_space_daily_download_limit(login_user)

    async def _should_enforce_daily_limit(self, request: PortalPdfDownloadRequest, login_user: Any) -> bool:
        if request.share_access_grant:
            return False
        return await should_enforce_knowledge_space_daily_download(login_user)

    async def _enforce_daily_download_limit(self, request: PortalPdfDownloadRequest, login_user: Any) -> None:
        if request.share_access_grant:
            return
        await enforce_knowledge_space_daily_download(
            login_user,
            counter=self.daily_download_counter,
            limit_resolver=self._resolve_daily_limit,
        )

    async def _record_daily_download(self, request: PortalPdfDownloadRequest, login_user: Any) -> None:
        if request.share_access_grant:
            return
        await record_knowledge_space_daily_download(
            login_user,
            counter=self.daily_download_counter,
            limit_resolver=self._resolve_daily_limit,
        )

    async def prepare_download(
        self,
        request: PortalPdfDownloadRequest,
        login_user: Any,
    ) -> PreparedPortalPdfDownload:
        tenant_id = int(getattr(login_user, "tenant_id", 0) or 0)
        user_id = int(getattr(login_user, "user_id", 0) or 0)
        file_record = await self.file_repository.find_by_id(request.file_id)
        if (
            file_record is None
            or file_record.file_type != FileType.FILE.value
            or int(file_record.knowledge_id) != int(request.space_id)
            or int(file_record.tenant_id or 0) != tenant_id
        ):
            raise SpaceFileNotFoundError()

        if request.share_access_grant:
            claims = self.share_grant_service.verify(
                request.share_access_grant,
                user_id=user_id,
                tenant_id=tenant_id,
                space_id=request.space_id,
                file_id=request.file_id,
            )
            await self.authorization_service.require_shougang_portal_share_download(
                share_token=claims.share_token,
                space_id=request.space_id,
                file_id=request.file_id,
            )
        else:
            await self.authorization_service.require_shougang_portal_file_download_permission(
                space_id=request.space_id,
                file_id=request.file_id,
            )

        await self._enforce_daily_download_limit(request, login_user)

        user_record = await self.user_repository.find_by_id(user_id)
        if user_record is None:
            raise PortalPdfDownloadGenerationError()
        display_name = str(getattr(user_record, "user_name", "") or "").strip()
        if not display_name:
            display_name = str(getattr(login_user, "user_name", "") or user_id).strip()
        department_name = str(await self.user_repository.get_primary_department_name(user_id) or "").strip()
        account = str(getattr(user_record, "external_id", "") or "").strip()
        if not account:
            account = str(getattr(login_user, "user_name", "") or user_id).strip()
        identity_prefix = f"{department_name}-{display_name}" if department_name else display_name

        lock_token = await self.user_lock.acquire(
            tenant_id=tenant_id,
            user_id=user_id,
            ttl_seconds=self.user_lock_ttl_seconds,
        )
        if not lock_token:
            raise PortalPdfDownloadBusyError()
        if not self.capacity_limiter.try_acquire():
            await self.user_lock.release(tenant_id=tenant_id, user_id=user_id, token=lock_token)
            raise PortalPdfDownloadBusyError()

        temp_dir: Path | None = None
        capacity_acquired = True
        try:
            if self.temp_root is not None:
                self.temp_root.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(
                tempfile.mkdtemp(
                    prefix="portal-pdf-download-",
                    dir=str(self.temp_root) if self.temp_root is not None else None,
                )
            ).resolve()
            input_path = temp_dir / "artifact.pdf"
            output_path = temp_dir / "watermarked.pdf"
            readiness_deadline = self.monotonic() + float(self.artifact_readiness_timeout_seconds)
            artifact = await self.artifact_ensurer(
                file_record,
                timeout_seconds=self._remaining(readiness_deadline),
            )
            self._validate_artifact_reference(artifact, tenant_id, request.file_id)
            try:
                await self._copy_and_validate_artifact(artifact, input_path, readiness_deadline)
            except asyncio.CancelledError:
                raise
            except PortalPdfDownloadTimeoutError:
                raise
            except Exception:
                if self.monotonic() >= readiness_deadline:
                    raise PortalPdfDownloadTimeoutError() from None
                invalid_generation = int(getattr(artifact, "generation", 0) or 0)
                artifact = await self.artifact_ensurer(
                    file_record,
                    invalid_generation=invalid_generation,
                    timeout_seconds=self._remaining(readiness_deadline),
                )
                self._validate_artifact_reference(
                    artifact,
                    tenant_id,
                    request.file_id,
                    invalid_generation=invalid_generation,
                )
                await self._copy_and_validate_artifact(artifact, input_path, readiness_deadline)

            deadline = self.monotonic() + float(self.config.timeout_seconds)
            watermark_date = self.now_provider().strftime("%Y/%m/%d")
            spec = PdfWatermarkSpec(
                lines=(
                    f"{identity_prefix}--{account}-{watermark_date}",
                    "首钢股份内部资料，严禁外传，违者必究",  # noqa: RUF001
                )
            )
            remaining = self._remaining(deadline)
            await asyncio.to_thread(
                self.watermark_runner,
                input_path=input_path,
                output_path=output_path,
                spec=spec,
                timeout_seconds=remaining,
                terminate_grace_seconds=self.config.process_terminate_grace_seconds,
            )
            if self.monotonic() >= deadline:
                raise PortalPdfDownloadTimeoutError()
            validation = validate_pdf(output_path)
            filename = self._safe_pdf_filename(file_record.file_name)
        except asyncio.CancelledError:
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            raise
        except (PortalPdfDownloadTimeoutError, PdfWatermarkWorkerTimeout):
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            raise PortalPdfDownloadTimeoutError() from None
        except PdfArtifactOnDemandTimeoutError:
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            raise PortalPdfDownloadTimeoutError() from None
        except PdfArtifactOnDemandServiceUnavailableError:
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            raise PortalPdfDownloadServiceUnavailableError() from None
        except PdfArtifactOnDemandGenerationError:
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            raise PortalPdfDownloadGenerationError() from None
        except PortalPdfDownloadBusyError:
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            raise
        except PortalPdfArtifactUnavailableError:
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            raise
        except (PdfWatermarkWorkerError, PdfValidationError):
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            raise PortalPdfDownloadGenerationError() from None
        except Exception as exc:
            await self._cleanup_failed_request(temp_dir, tenant_id, user_id, lock_token)
            logger.error(
                "portal_pdf_download_generation_failed tenant_id={} user_id={} file_id={} error_type={}",
                tenant_id,
                user_id,
                request.file_id,
                type(exc).__name__,
            )
            raise PortalPdfDownloadGenerationError() from None
        finally:
            if capacity_acquired:
                self.capacity_limiter.release()

        async def cleanup() -> None:
            if temp_dir is not None:
                await asyncio.to_thread(shutil.rmtree, temp_dir, True)
            await self.user_lock.release(tenant_id=tenant_id, user_id=user_id, token=lock_token)

        async def record_success() -> None:
            payload = {
                "user_id": user_id,
                "space_id": request.space_id,
                "file_id": request.file_id,
                "entry_point": request.entry_point.value,
            }
            result = self.telemetry_recorder(payload)
            if inspect.isawaitable(result):
                await result

        await self._record_daily_download(request, login_user)

        return PreparedPortalPdfDownload(
            path=output_path,
            filename=filename,
            size=validation.artifact_size,
            cleanup_callback=cleanup,
            success_callback=record_success,
        )

    async def _run_with_deadline(
        self,
        callback: Callable[..., Any],
        deadline: float,
        *args: Any,
    ) -> Any:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(callback, *args),
                timeout=self._remaining(deadline),
            )
        except (TimeoutError, asyncio.TimeoutError):
            raise PortalPdfDownloadTimeoutError() from None

    def _copy_artifact(self, object_name: str, target_path: Path, deadline: float) -> None:
        response = None
        try:
            response = self.storage.download_object_sync(object_name=object_name)
            with target_path.open("wb") as output:
                while True:
                    if self.monotonic() >= deadline:
                        raise PortalPdfDownloadTimeoutError()
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    async def _copy_and_validate_artifact(self, artifact: Any, input_path: Path, deadline: float) -> None:
        input_path.unlink(missing_ok=True)
        await self._run_with_deadline(
            self._copy_artifact,
            deadline,
            str(artifact.object_name),
            input_path,
            deadline,
        )
        validation = await self._run_with_deadline(validate_pdf, deadline, input_path)
        if (
            validation.artifact_sha256 != str(getattr(artifact, "artifact_sha256", "") or "")
            or validation.artifact_size != int(getattr(artifact, "artifact_size", 0) or 0)
            or validation.page_count != int(getattr(artifact, "page_count", 0) or 0)
        ):
            raise PdfValidationError("PDF artifact metadata does not match the stored object")

    @staticmethod
    def _validate_artifact_reference(
        artifact: Any,
        tenant_id: int,
        knowledge_file_id: int,
        *,
        invalid_generation: int | None = None,
    ) -> None:
        generation = int(getattr(artifact, "generation", 0) or 0)
        if (
            artifact is None
            or int(getattr(artifact, "tenant_id", 0) or 0) != tenant_id
            or int(getattr(artifact, "knowledge_file_id", 0) or 0) != knowledge_file_id
            or not str(getattr(artifact, "object_name", "") or "")
            or not str(getattr(artifact, "artifact_sha256", "") or "")
            or int(getattr(artifact, "page_count", 0) or 0) <= 0
            or int(getattr(artifact, "artifact_size", 0) or 0) <= 0
            or generation <= 0
            or (invalid_generation is not None and generation == invalid_generation)
        ):
            raise PortalPdfArtifactUnavailableError()

    async def _cleanup_failed_request(
        self,
        temp_dir: Path | None,
        tenant_id: int,
        user_id: int,
        lock_token: str,
    ) -> None:
        if temp_dir is not None:
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)
        await self.user_lock.release(tenant_id=tenant_id, user_id=user_id, token=lock_token)

    def _remaining(self, deadline: float) -> float:
        return max(deadline - self.monotonic(), 0.001)

    @staticmethod
    def _safe_pdf_filename(file_name: str) -> str:
        stem = Path(str(file_name or "document").replace("\\", "/")).name
        stem = Path(stem).stem.strip().replace("\r", "").replace("\n", "")
        stem = stem.replace('"', "").replace("/", "").replace("\\", "")
        return f"{stem or 'document'}.pdf"

    @staticmethod
    def _record_download_telemetry(payload: dict[str, Any]) -> None:
        PortalTelemetryEventService.log_event_sync(
            user_id=int(payload["user_id"]),
            event_type=BaseTelemetryTypeEnum.PORTAL_DOCUMENT_DOWNLOAD,
            event_data=PortalDocumentDownloadEventData(
                source_app="shougang_portal",
                scene="document_download",
                entry_point=str(payload["entry_point"]),
                resource_type="document",
                space_id=int(payload["space_id"]),
                file_id=int(payload["file_id"]),
                status="success",
            ),
        )
