from __future__ import annotations

import asyncio
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.developer_token import DeveloperTokenDisabledError, DeveloperTokenMissingError
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.repositories.developer_token_repository import DeveloperTokenRepository
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.open_endpoints.domain.models.filelib_scheduled_sync_run_log import AUTOMOTIVE_SHEET_INTRO_JOB_CODE
from bisheng.open_endpoints.domain.repositories.implementations.filelib_scheduled_sync_run_log_repository_impl import (
    FilelibScheduledSyncRunLogRepositoryImpl,
)
from bisheng.open_endpoints.domain.repositories.interfaces.filelib_scheduled_sync_run_log_repository import (
    FilelibScheduledSyncRunLogCreate,
    FilelibScheduledSyncRunLogUpdate,
)
from bisheng.open_endpoints.domain.repositories.implementations.filelib_sync_repository_impl import (
    FilelibSyncRepositoryImpl,
)
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import (
    AutomotiveSheetIntroSyncConfig,
    AutomotiveSheetIntroSyncTriggerType,
)
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client import AutomotiveSheetIntroSyncClient
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service import (
    AutomotiveSheetIntroSyncConfigService,
    build_file_sync_rule_from_token,
)
from bisheng.open_endpoints.domain.services.filelib_sync_factory import build_filelib_sync_service_for_scheduled_sync

AUTOMOTIVE_SHEET_INTRO_SYNC_LOCK_PREFIX = "bisheng:lock:automotive_sheet_intro_sync:"
AUTOMOTIVE_SHEET_INTRO_SYNC_LOCK_TTL_SECONDS = 1800
AUTOMOTIVE_SHEET_INTRO_SYNC_ENDPOINT_TAG = "automotive_sheet_intro_sync"


@dataclass(frozen=True)
class AutomotiveSheetIntroSyncRunResult:
    status: Literal["success", "failed", "skipped"]
    run_id: int | None = None
    file_id: int | None = None
    error_message: str | None = None
    skip_reason: str | None = None


class AutomotiveSheetIntroSyncService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        config_service: AutomotiveSheetIntroSyncConfigService | None = None,
        pdf_client: AutomotiveSheetIntroSyncClient | None = None,
    ) -> None:
        self.session = session
        self.config_service = config_service or AutomotiveSheetIntroSyncConfigService(
            config_repository=_config_repository(session),
        )
        self.pdf_client = pdf_client or AutomotiveSheetIntroSyncClient()
        self.run_log_repository = FilelibScheduledSyncRunLogRepositoryImpl(session)

    async def run(
        self,
        *,
        tenant_id: int,
        trigger_type: AutomotiveSheetIntroSyncTriggerType,
    ) -> AutomotiveSheetIntroSyncRunResult:
        tenant_id = int(tenant_id)
        current = get_current_tenant_id()
        if current is not None and int(current) != tenant_id:
            raise PermissionError("automotive sheet intro sync tenant mismatch")

        lock_token = await self._acquire_lock(tenant_id)
        if lock_token is None:
            logger.info(
                "automotive sheet intro sync skipped tenant_id={} trigger_type={} reason=lock_held",
                tenant_id,
                trigger_type,
            )
            return await self._write_skipped_run(
                tenant_id=tenant_id,
                trigger_type=trigger_type,
                reason="lock_held",
            )

        run_id: int | None = None
        temp_file_path: str | None = None
        started = time.perf_counter()
        try:
            config = await self.config_service.get_config(tenant_id)
            if not config.enabled:
                logger.info(
                    "automotive sheet intro sync skipped tenant_id={} trigger_type={} reason=disabled",
                    tenant_id,
                    trigger_type,
                )
                return await self._write_skipped_run(
                    tenant_id=tenant_id,
                    trigger_type=trigger_type,
                    reason="disabled",
                    developer_token_id=config.developer_token_id,
                )

            token = await self._load_enabled_token(tenant_id, config)
            file_sync_rule = build_file_sync_rule_from_token(token)
            preview_knowledge_id = (
                int(file_sync_rule.target_space.knowledge_id)
                if file_sync_rule.target_space.mode == "fixed" and file_sync_rule.target_space.knowledge_id
                else None
            )
            run_id = await self.run_log_repository.insert(
                FilelibScheduledSyncRunLogCreate(
                    tenant_id=tenant_id,
                    job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
                    trigger_type=trigger_type,
                    status="running",
                    developer_token_id=int(token.id),
                    file_name=config.file_name,
                    knowledge_id=preview_knowledge_id,
                    start_time=_utc_now(),
                )
            )

            pdf_bytes = await self.pdf_client.fetch_pdf(
                api_url=str(config.api_url),
                method=config.api_method,
                timeout_seconds=config.api_timeout_seconds,
                api_ssl_verify=bool(config.api_ssl_verify),
            )
            temp_file_path = await self._write_temp_pdf(config.file_name, pdf_bytes)

            login_user = await DeveloperTokenService._get_bound_user_payload(int(tenant_id), int(token.user_id))
            params = await self._build_filelib_sync_params(token=token, config=config)
            filelib_service = build_filelib_sync_service_for_scheduled_sync(
                session=self.session,
                token=token,
                file_sync_rule=file_sync_rule,
                login_user=login_user,
            )
            sync_result = await filelib_service.sync_from_staged_file(
                params=params,
                local_file_path=temp_file_path,
                endpoint_tag=AUTOMOTIVE_SHEET_INTRO_SYNC_ENDPOINT_TAG,
                trigger_type=trigger_type,
                allow_personal_fallback=False,
            )

            duration_ms = int((time.perf_counter() - started) * 1000)
            end_time = _utc_now()
            await self.run_log_repository.update(
                run_id,
                FilelibScheduledSyncRunLogUpdate(
                    status="success",
                    file_id=int(sync_result.file_id),
                    knowledge_id=int(sync_result.knowledge_id),
                    file_name=config.file_name,
                    end_time=end_time,
                    duration_ms=duration_ms,
                ),
            )
            logger.info(
                "automotive sheet intro sync success tenant_id={} trigger_type={} file_id={} knowledge_id={} duration_ms={}",
                tenant_id,
                trigger_type,
                sync_result.file_id,
                sync_result.knowledge_id,
                duration_ms,
            )
            return AutomotiveSheetIntroSyncRunResult(
                status="success",
                run_id=run_id,
                file_id=int(sync_result.file_id),
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            error_message = _truncate_error_message(exc)
            if run_id is not None:
                await self.run_log_repository.update(
                    run_id,
                    FilelibScheduledSyncRunLogUpdate(
                        status="failed",
                        error_message=error_message,
                        end_time=_utc_now(),
                        duration_ms=duration_ms,
                    ),
                )
            logger.exception(
                "automotive sheet intro sync failed tenant_id={} trigger_type={} run_id={} error={}",
                tenant_id,
                trigger_type,
                run_id,
                error_message,
            )
            return AutomotiveSheetIntroSyncRunResult(
                status="failed",
                run_id=run_id,
                error_message=error_message,
            )
        finally:
            if temp_file_path:
                await self._cleanup_temp_file(temp_file_path)
            await self._release_lock(tenant_id, lock_token)

    async def _write_skipped_run(
        self,
        *,
        tenant_id: int,
        trigger_type: AutomotiveSheetIntroSyncTriggerType,
        reason: str,
        developer_token_id: int | None = None,
    ) -> AutomotiveSheetIntroSyncRunResult:
        now = _utc_now()
        run_id = await self.run_log_repository.insert(
            FilelibScheduledSyncRunLogCreate(
                tenant_id=tenant_id,
                job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
                trigger_type=trigger_type,
                status="skipped",
                developer_token_id=developer_token_id,
                error_message=reason,
                start_time=now,
                end_time=now,
                duration_ms=0,
            )
        )
        return AutomotiveSheetIntroSyncRunResult(
            status="skipped",
            run_id=run_id,
            skip_reason=reason,
        )

    @staticmethod
    async def _load_enabled_token(tenant_id: int, config: AutomotiveSheetIntroSyncConfig) -> DeveloperToken:
        token_id = int(config.developer_token_id or 0)
        token = await DeveloperTokenRepository.get_token_by_id(token_id)
        if token is None or int(token.tenant_id) != int(tenant_id):
            raise DeveloperTokenMissingError()
        if not bool(token.enabled):
            raise DeveloperTokenDisabledError()
        return token

    async def _build_filelib_sync_params(
        self,
        *,
        token: DeveloperToken,
        config: AutomotiveSheetIntroSyncConfig,
    ) -> FilelibSyncParams:
        repo = FilelibSyncRepositoryImpl(self.session)
        primary_links = await repo.find_primary_departments(int(token.user_id))
        department = None
        if primary_links:
            department = await repo.find_department_by_id(int(primary_links[0].department_id))
        user = await repo.find_user_by_id(int(token.user_id))

        user_external = str(getattr(user, "external_id", None) or "").strip() if user is not None else ""

        # Scheduled sync resolves the token user's primary department internally.
        # Passing external department_id here would trigger open-API mapping lookup and fail
        # when SG external department mappings are not configured.
        return FilelibSyncParams(
            external_file_id=config.external_file_id,
            file_name=config.file_name,
            department_id=None,
            department=getattr(department, "name", None) if department is not None else None,
            responsible_person_id=user_external or None,
            responsible_person=user_external or None,
        )

    @staticmethod
    async def _write_temp_pdf(file_name: str, content: bytes) -> str:
        suffix = os.path.splitext(file_name)[1] or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            return tmp.name

    @staticmethod
    async def _cleanup_temp_file(file_path: str) -> None:
        try:
            await asyncio.to_thread(KnowledgeService.remove_unused_file, file_path)
        except Exception:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                logger.warning("automotive sheet intro sync temp cleanup failed path={}", file_path)

    @staticmethod
    async def _acquire_lock(tenant_id: int) -> str | None:
        try:
            redis = await get_redis_client()
            lock_key = f"{AUTOMOTIVE_SHEET_INTRO_SYNC_LOCK_PREFIX}{tenant_id}"
            token = secrets.token_hex(16)
            acquired = await redis.async_connection.set(
                lock_key,
                token,
                nx=True,
                ex=AUTOMOTIVE_SHEET_INTRO_SYNC_LOCK_TTL_SECONDS,
            )
            return token if acquired else None
        except Exception as exc:
            logger.warning("automotive sheet intro sync lock acquisition failed tenant_id={} err={}", tenant_id, exc)
            return None

    @staticmethod
    async def _release_lock(tenant_id: int, token: str | None) -> None:
        if not token:
            return
        try:
            redis = await get_redis_client()
            lock_key = f"{AUTOMOTIVE_SHEET_INTRO_SYNC_LOCK_PREFIX}{tenant_id}"
            current = await redis.async_connection.get(lock_key)
            if current and current.decode() == token:
                await redis.async_connection.delete(lock_key)
        except Exception as exc:
            logger.warning("automotive sheet intro sync lock release failed tenant_id={} err={}", tenant_id, exc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _truncate_error_message(exc: Exception, *, limit: int = 500) -> str:
    if isinstance(exc, BaseErrorCode):
        return str(exc.message)[:limit]
    return str(exc)[:limit]


def _config_repository(session: AsyncSession):
    from bisheng.open_endpoints.domain.repositories.implementations.automotive_sheet_intro_sync_config_repository_impl import (
        AutomotiveSheetIntroSyncConfigRepositoryImpl,
    )

    return AutomotiveSheetIntroSyncConfigRepositoryImpl(session)
