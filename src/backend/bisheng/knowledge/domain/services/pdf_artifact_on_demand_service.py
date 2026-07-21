"""下载请求内确保统一 PDF Artifact 可用。"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from bisheng.core.config.settings import KnowledgePdfArtifactConf
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import KnowledgeFilePdfArtifactStatus


class PdfArtifactOnDemandTimeoutError(RuntimeError):
    """等待或生成统一 PDF 超过请求级截止时间。"""


class PdfArtifactOnDemandGenerationError(RuntimeError):
    """统一 PDF 在本次请求内生成失败。"""


class PdfArtifactOnDemandServiceUnavailableError(RuntimeError):
    """统一 PDF 协调依赖暂不可用。"""


class PdfArtifactGenerationLock:
    """租户+文件维度的 Redis 所有权锁; 同时支持请求与 Celery。"""

    _RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

    def __init__(self, redis_client: Any | None = None, sync_redis_client: Any | None = None) -> None:
        self._redis = getattr(redis_client, "async_connection", redis_client)
        self._sync_redis = getattr(sync_redis_client, "connection", sync_redis_client)

    @staticmethod
    def _key(tenant_id: int, knowledge_file_id: int) -> str:
        return f"bisheng:knowledge_pdf_artifact:generation:{int(tenant_id)}:{int(knowledge_file_id)}"

    async def _async_connection(self) -> Any:
        if self._redis is None:
            from bisheng.core.cache.redis_manager import get_redis_client

            client = await get_redis_client()
            self._redis = client.async_connection
        return self._redis

    def _sync_connection(self) -> Any:
        if self._sync_redis is None:
            from bisheng.core.cache.redis_manager import get_redis_client_sync

            client = get_redis_client_sync()
            self._sync_redis = client.connection
        return self._sync_redis

    async def acquire(self, *, tenant_id: int, knowledge_file_id: int, ttl_seconds: int) -> str | None:
        token = secrets.token_urlsafe(18)
        try:
            redis = await self._async_connection()
            acquired = await redis.set(
                self._key(tenant_id, knowledge_file_id),
                token,
                nx=True,
                ex=max(int(ttl_seconds), 1),
            )
        except Exception:
            raise PdfArtifactOnDemandServiceUnavailableError() from None
        return token if acquired else None

    async def release(self, *, tenant_id: int, knowledge_file_id: int, token: str) -> None:
        try:
            redis = await self._async_connection()
            await redis.eval(self._RELEASE_SCRIPT, 1, self._key(tenant_id, knowledge_file_id), token)
        except Exception:
            logger.error(
                "knowledge_pdf_artifact_generation_lock_release_failed tenant_id={} file_id={}",
                tenant_id,
                knowledge_file_id,
            )

    def acquire_sync(self, *, tenant_id: int, knowledge_file_id: int, ttl_seconds: int) -> str | None:
        token = secrets.token_urlsafe(18)
        try:
            acquired = self._sync_connection().set(
                self._key(tenant_id, knowledge_file_id),
                token,
                nx=True,
                ex=max(int(ttl_seconds), 1),
            )
        except Exception:
            raise PdfArtifactOnDemandServiceUnavailableError() from None
        return token if acquired else None

    def release_sync(self, *, tenant_id: int, knowledge_file_id: int, token: str) -> None:
        try:
            self._sync_connection().eval(
                self._RELEASE_SCRIPT,
                1,
                self._key(tenant_id, knowledge_file_id),
                token,
            )
        except Exception:
            logger.error(
                "knowledge_pdf_artifact_generation_lock_release_failed tenant_id={} file_id={}",
                tenant_id,
                knowledge_file_id,
            )


class PdfArtifactOnDemandService:
    """在当前下载请求内生成并持久化缺失或损坏的统一 PDF。"""

    def __init__(
        self,
        *,
        artifact_service: Any,
        artifact_accessor: Callable[[KnowledgeFile], Awaitable[Any]],
        generation_runner: Callable[..., Any],
        generation_lock: Any,
        config: KnowledgePdfArtifactConf,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.artifact_service = artifact_service
        self.artifact_accessor = artifact_accessor
        self.generation_runner = generation_runner
        self.generation_lock = generation_lock
        self.config = config
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or asyncio.sleep
        self._background_tasks: set[asyncio.Task] = set()

    @staticmethod
    def _is_acceptable(reference: Any, file: KnowledgeFile, invalid_generation: int | None) -> bool:
        if reference is None or file.id is None or file.tenant_id is None:
            return False
        generation = int(getattr(reference, "generation", 0) or 0)
        return bool(
            int(getattr(reference, "tenant_id", 0) or 0) == int(file.tenant_id)
            and int(getattr(reference, "knowledge_file_id", 0) or 0) == int(file.id)
            and str(getattr(reference, "object_name", "") or "")
            and generation > 0
            and (invalid_generation is None or generation != int(invalid_generation))
        )

    async def _wait_for_result(
        self,
        file: KnowledgeFile,
        *,
        invalid_generation: int | None,
        deadline: float,
    ) -> Any:
        while True:
            reference = await self.artifact_accessor(file)
            if self._is_acceptable(reference, file, invalid_generation):
                return reference
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise PdfArtifactOnDemandTimeoutError()
            await self.sleep(min(0.2, remaining))

    async def _persist_failure(
        self,
        *,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int | None,
        summary: str,
    ) -> None:
        if generation is None:
            return
        try:
            await self.artifact_service.fail_generation(
                tenant_id=tenant_id,
                knowledge_file_id=knowledge_file_id,
                generation=generation,
                error=summary,
            )
        except Exception as persistence_exc:
            logger.error(
                "knowledge_pdf_artifact_on_demand_failure_persist_failed "
                "tenant_id={} file_id={} generation={} error_type={}",
                tenant_id,
                knowledge_file_id,
                generation,
                type(persistence_exc).__name__,
            )

    async def _release_after_runner(
        self,
        runner_task: asyncio.Task,
        *,
        tenant_id: int,
        knowledge_file_id: int,
        token: str,
    ) -> None:
        try:
            await runner_task
        except BaseException as exc:
            logger.warning(
                "knowledge_pdf_artifact_late_runner_finished "
                "tenant_id={} file_id={} error_type={}",
                tenant_id,
                knowledge_file_id,
                type(exc).__name__,
            )
        finally:
            await self.generation_lock.release(
                tenant_id=tenant_id,
                knowledge_file_id=knowledge_file_id,
                token=token,
            )

    async def ensure_available(
        self,
        file: KnowledgeFile,
        *,
        invalid_generation: int | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        reference = await self.artifact_accessor(file)
        if self._is_acceptable(reference, file, invalid_generation):
            return reference
        if file.id is None or file.tenant_id is None:
            raise PdfArtifactOnDemandGenerationError()

        tenant_id = int(file.tenant_id)
        knowledge_file_id = int(file.id)
        configured_timeout = float(self.config.on_demand_timeout_seconds)
        effective_timeout = configured_timeout if timeout_seconds is None else min(configured_timeout, timeout_seconds)
        if effective_timeout <= 0:
            raise PdfArtifactOnDemandTimeoutError()
        deadline = self.monotonic() + effective_timeout
        token = await self.generation_lock.acquire(
            tenant_id=tenant_id,
            knowledge_file_id=knowledge_file_id,
            ttl_seconds=self.config.generation_lock_ttl_seconds,
        )
        if not token:
            return await self._wait_for_result(
                file,
                invalid_generation=invalid_generation,
                deadline=deadline,
            )

        generation: int | None = None
        runner_task: asyncio.Task | None = None
        try:
            reference = await self.artifact_accessor(file)
            if self._is_acceptable(reference, file, invalid_generation):
                return reference
            request = await self.artifact_service.request_on_demand_generation(
                file,
                invalid_generation=invalid_generation,
            )
            if request is None:
                raise PdfArtifactOnDemandGenerationError()
            generation = int(request.artifact.generation)
            if request.artifact.status == KnowledgeFilePdfArtifactStatus.FAILED.value:
                raise PdfArtifactOnDemandGenerationError()

            try:
                runner_task = asyncio.create_task(
                    asyncio.to_thread(
                        self.generation_runner,
                        tenant_id=tenant_id,
                        knowledge_file_id=knowledge_file_id,
                        generation=generation,
                        config=self.config,
                    )
                )
                await asyncio.wait_for(
                    asyncio.shield(runner_task),
                    timeout=max(deadline - self.monotonic(), 0.001),
                )
            except (TimeoutError, asyncio.TimeoutError):
                raise PdfArtifactOnDemandTimeoutError() from None

            reference = await self.artifact_accessor(file)
            if not self._is_acceptable(reference, file, invalid_generation):
                raise PdfArtifactOnDemandGenerationError()
            return reference
        except PdfArtifactOnDemandTimeoutError:
            await self._persist_failure(
                tenant_id=tenant_id,
                knowledge_file_id=knowledge_file_id,
                generation=generation,
                summary="process:TimeoutError",
            )
            raise
        except PdfArtifactOnDemandGenerationError:
            await self._persist_failure(
                tenant_id=tenant_id,
                knowledge_file_id=knowledge_file_id,
                generation=generation,
                summary="process:PdfArtifactOnDemandGenerationError",
            )
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._persist_failure(
                tenant_id=tenant_id,
                knowledge_file_id=knowledge_file_id,
                generation=generation,
                summary=f"process:{type(exc).__name__}",
            )
            logger.error(
                "knowledge_pdf_artifact_on_demand_failed tenant_id={} file_id={} generation={} error_type={}",
                tenant_id,
                knowledge_file_id,
                generation,
                type(exc).__name__,
            )
            raise PdfArtifactOnDemandGenerationError() from None
        finally:
            if runner_task is not None and not runner_task.done():
                cleanup_task = asyncio.create_task(
                    self._release_after_runner(
                        runner_task,
                        tenant_id=tenant_id,
                        knowledge_file_id=knowledge_file_id,
                        token=token,
                    )
                )
                self._background_tasks.add(cleanup_task)
                cleanup_task.add_done_callback(self._background_tasks.discard)
            else:
                await self.generation_lock.release(
                    tenant_id=tenant_id,
                    knowledge_file_id=knowledge_file_id,
                    token=token,
                )
