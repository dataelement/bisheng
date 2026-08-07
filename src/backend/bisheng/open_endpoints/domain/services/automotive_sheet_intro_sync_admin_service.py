"""Admin operations for automotive sheet intro scheduled sync (F049)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncDisabledError
from bisheng.common.schemas.api import PageData
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService
from bisheng.open_endpoints.domain.models.filelib_scheduled_sync_run_log import AUTOMOTIVE_SHEET_INTRO_JOB_CODE
from bisheng.open_endpoints.domain.repositories.implementations.filelib_scheduled_sync_run_log_repository_impl import (
    FilelibScheduledSyncRunLogRepositoryImpl,
)
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import (
    AutomotiveSheetIntroSyncConfig,
    AutomotiveSheetIntroSyncRunRead,
    AutomotiveSheetIntroSyncTestResponse,
)
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service import (
    AutomotiveSheetIntroSyncConfigService,
)
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service import (
    AutomotiveSheetIntroSyncRunResult,
    AutomotiveSheetIntroSyncService,
)


def _build_config_service(session) -> AutomotiveSheetIntroSyncConfigService:
    from bisheng.open_endpoints.domain.repositories.implementations.automotive_sheet_intro_sync_config_repository_impl import (
        AutomotiveSheetIntroSyncConfigRepositoryImpl,
    )

    return AutomotiveSheetIntroSyncConfigService(AutomotiveSheetIntroSyncConfigRepositoryImpl(session))


def _build_test_response(
    *,
    tenant_id: int,
    result: AutomotiveSheetIntroSyncRunResult,
) -> AutomotiveSheetIntroSyncTestResponse:
    if result.status == "success":
        message = "Automotive sheet intro sync completed successfully"
    elif result.status == "skipped":
        message = f"Automotive sheet intro sync skipped: {result.skip_reason or 'unknown'}"
    else:
        message = f"Automotive sheet intro sync failed: {result.error_message or 'unknown'}"
    return AutomotiveSheetIntroSyncTestResponse(
        run_id=result.run_id,
        status=result.status,
        error_message=result.error_message,
        skip_reason=result.skip_reason,
        file_id=result.file_id,
        tenant_id=tenant_id,
        message=message,
    )


class AutomotiveSheetIntroSyncAdminService:
    @classmethod
    async def _resolve_tenant_id(cls, operator: UserPayload) -> int:
        tenant_id = int(get_current_tenant_id() or operator.tenant_id)
        await DeveloperTokenService._assert_admin_scope(operator, tenant_id)
        return tenant_id

    @classmethod
    async def get_config(cls, operator: UserPayload) -> AutomotiveSheetIntroSyncConfig:
        tenant_id = await cls._resolve_tenant_id(operator)
        with DeveloperTokenService._target_tenant_context(tenant_id):
            async with get_async_db_session() as session:
                return await _build_config_service(session).get_config(tenant_id)

    @classmethod
    async def save_config(
        cls,
        operator: UserPayload,
        payload: AutomotiveSheetIntroSyncConfig,
    ) -> AutomotiveSheetIntroSyncConfig:
        tenant_id = await cls._resolve_tenant_id(operator)
        with DeveloperTokenService._target_tenant_context(tenant_id):
            async with get_async_db_session() as session:
                config = await _build_config_service(session).save_config(tenant_id, payload)
                await session.commit()
                return config

    @classmethod
    async def trigger_test(
        cls,
        operator: UserPayload,
        *,
        run_manual_sync: Callable[[int], Awaitable[AutomotiveSheetIntroSyncRunResult]] | None = None,
    ) -> AutomotiveSheetIntroSyncTestResponse:
        tenant_id = await cls._resolve_tenant_id(operator)
        with DeveloperTokenService._target_tenant_context(tenant_id):
            async with get_async_db_session() as session:
                config = await _build_config_service(session).get_config(tenant_id)
                if not config.enabled:
                    raise AutomotiveSheetIntroSyncDisabledError()

                if run_manual_sync is not None:
                    result = await run_manual_sync(tenant_id)
                    return _build_test_response(tenant_id=tenant_id, result=result)

                service = AutomotiveSheetIntroSyncService(session=session)
                result = await service.run(tenant_id=tenant_id, trigger_type="manual")
                await session.commit()
                return _build_test_response(tenant_id=tenant_id, result=result)

    @classmethod
    async def list_runs(
        cls,
        operator: UserPayload,
        *,
        page: int,
        limit: int,
    ) -> PageData[AutomotiveSheetIntroSyncRunRead]:
        tenant_id = await cls._resolve_tenant_id(operator)
        with DeveloperTokenService._target_tenant_context(tenant_id):
            async with get_async_db_session() as session:
                runs, total = await FilelibScheduledSyncRunLogRepositoryImpl(session).list_by_tenant(
                    tenant_id,
                    job_code=AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
                    page=page,
                    limit=limit,
                )
        return PageData(
            data=[AutomotiveSheetIntroSyncRunRead.model_validate(row) for row in runs],
            total=total,
        )
