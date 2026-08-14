from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.automotive_sheet_intro_sync import AutomotiveSheetIntroUpstreamError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncConfig
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams, FilelibSyncResponseData
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service import (
    AUTOMOTIVE_SHEET_INTRO_SYNC_ENDPOINT_TAG,
    AutomotiveSheetIntroSyncService,
)


def _file_sync_rule() -> dict:
    return {
        "category": {"code": "DOC", "subcategory_code": "INTRO"},
        "business_domain": {"mode": "fixed", "code": "AUTO"},
        "target_space": {
            "mode": "fixed",
            "knowledge_id": 100,
            "folder_mode": "fixed",
            "folder_id": 200,
        },
    }


def _enabled_config() -> AutomotiveSheetIntroSyncConfig:
    return AutomotiveSheetIntroSyncConfig.model_validate(
        {
            "enabled": True,
            "api_url": "https://example.com/automotive.pdf",
            "developer_token_id": 10,
        }
    )


def _token() -> DeveloperToken:
    return DeveloperToken(
        id=10,
        tenant_id=5,
        user_id=100,
        name="scheduled-token",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bs_abc",
        enabled=True,
        file_sync_rule=_file_sync_rule(),
    )


@pytest.fixture(autouse=True)
def _tenant_context():
    token = set_current_tenant_id(5)
    yield
    current_tenant_id.reset(token)


def _service(session) -> AutomotiveSheetIntroSyncService:
    config_service = MagicMock()
    config_service.get_config = AsyncMock(return_value=AutomotiveSheetIntroSyncConfig.model_validate({"enabled": False}))
    pdf_client = MagicMock()
    pdf_client.fetch_pdf = AsyncMock(return_value=b"%PDF-1.4")
    return AutomotiveSheetIntroSyncService(
        session=session,
        config_service=config_service,
        pdf_client=pdf_client,
    )


@pytest.mark.asyncio
async def test_run_skips_when_disabled(async_db_session):
    service = _service(async_db_session)
    service.config_service.get_config = AsyncMock(
        return_value=AutomotiveSheetIntroSyncConfig.model_validate({"enabled": False})
    )
    service.run_log_repository.insert = AsyncMock(return_value=1)

    with patch.object(service, "_acquire_lock", AsyncMock(return_value="lock-token")):
        with patch.object(service, "_release_lock", AsyncMock()):
            result = await service.run(tenant_id=5, trigger_type="scheduled")

    assert result.status == "skipped"
    assert result.skip_reason == "disabled"
    service.pdf_client.fetch_pdf.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_skips_when_lock_not_acquired(async_db_session):
    service = _service(async_db_session)
    service.run_log_repository.insert = AsyncMock(return_value=2)

    with patch.object(service, "_acquire_lock", AsyncMock(return_value=None)):
        result = await service.run(tenant_id=5, trigger_type="scheduled")

    assert result.status == "skipped"
    assert result.skip_reason == "lock_held"
    assert service.config_service.get_config.await_count == 0


@pytest.mark.asyncio
async def test_run_success_writes_run_log_and_syncs(async_db_session):
    service = _service(async_db_session)
    config = _enabled_config()
    service.config_service.get_config = AsyncMock(return_value=config)
    service.run_log_repository.insert = AsyncMock(return_value=11)
    service.run_log_repository.update = AsyncMock()
    service._build_filelib_sync_params = AsyncMock(
        return_value=FilelibSyncParams(external_file_id="automotive_sheet_intro", file_name="汽车板介绍.pdf")
    )

    filelib_service = MagicMock()
    filelib_service.sync_from_staged_file = AsyncMock(
        return_value=FilelibSyncResponseData(
            external_file_id="automotive_sheet_intro",
            file_id=900,
            file_encoding="ENC",
            knowledge_id=100,
            knowledge_name="space",
            status=5,
        )
    )

    with patch.object(service, "_acquire_lock", AsyncMock(return_value="lock-token")):
        with patch.object(service, "_release_lock", AsyncMock()):
            with patch.object(service, "_load_enabled_token", AsyncMock(return_value=_token())):
                with patch.object(service, "_write_temp_pdf", AsyncMock(return_value="/tmp/test.pdf")):
                    with patch.object(service, "_cleanup_temp_file", AsyncMock()):
                        with patch(
                            "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.build_filelib_sync_service_for_scheduled_sync",
                            return_value=filelib_service,
                        ):
                            with patch(
                                "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.DeveloperTokenService._get_bound_user_payload",
                                AsyncMock(return_value=UserPayload(user_id=100, user_name="u", tenant_id=5)),
                            ):
                                result = await service.run(tenant_id=5, trigger_type="manual")

    assert result.status == "success"
    assert result.file_id == 900
    service.pdf_client.fetch_pdf.assert_awaited_once_with(
        api_url="https://example.com/automotive.pdf",
        method="GET",
        timeout_seconds=120,
        api_ssl_verify=True,
    )
    filelib_service.sync_from_staged_file.assert_awaited_once_with(
        params=service._build_filelib_sync_params.return_value,
        local_file_path="/tmp/test.pdf",
        endpoint_tag=AUTOMOTIVE_SHEET_INTRO_SYNC_ENDPOINT_TAG,
        trigger_type="manual",
        allow_personal_fallback=False,
    )
    service.run_log_repository.update.assert_awaited()


@pytest.mark.asyncio
async def test_run_upstream_failure_marks_run_log_failed_without_sync(async_db_session):
    service = _service(async_db_session)
    service.config_service.get_config = AsyncMock(return_value=_enabled_config())
    service.run_log_repository.insert = AsyncMock(return_value=12)
    service.run_log_repository.update = AsyncMock()
    service.pdf_client.fetch_pdf = AsyncMock(
        side_effect=AutomotiveSheetIntroUpstreamError(msg="upstream PDF request failed")
    )

    with patch.object(service, "_acquire_lock", AsyncMock(return_value="lock-token")):
        with patch.object(service, "_release_lock", AsyncMock()):
            with patch.object(service, "_load_enabled_token", AsyncMock(return_value=_token())):
                result = await service.run(tenant_id=5, trigger_type="scheduled")

    assert result.status == "failed"
    service.run_log_repository.update.assert_awaited()
    update_payload = service.run_log_repository.update.await_args.args[1]
    assert update_payload.status == "failed"


@pytest.mark.asyncio
async def test_run_passes_disabled_api_ssl_verify_to_pdf_client(async_db_session):
    service = _service(async_db_session)
    config = AutomotiveSheetIntroSyncConfig.model_validate(
        {
            "enabled": True,
            "api_url": "https://192.168.147.131/automotive.pdf",
            "developer_token_id": 10,
            "api_ssl_verify": False,
        }
    )
    service.config_service.get_config = AsyncMock(return_value=config)
    service.run_log_repository.insert = AsyncMock(return_value=13)
    service.run_log_repository.update = AsyncMock()
    service.pdf_client.fetch_pdf = AsyncMock(return_value=b"%PDF-1.4 test")
    service._build_filelib_sync_params = AsyncMock(
        return_value=FilelibSyncParams(external_file_id="automotive_sheet_intro", file_name="汽车板介绍.pdf")
    )
    filelib_service = MagicMock()
    filelib_service.sync_from_staged_file = AsyncMock(
        return_value=FilelibSyncResponseData(
            external_file_id="automotive_sheet_intro",
            file_id=901,
            file_encoding="ENC",
            knowledge_id=100,
            knowledge_name="space",
            status=5,
        )
    )

    with patch.object(service, "_acquire_lock", AsyncMock(return_value="lock-token")):
        with patch.object(service, "_release_lock", AsyncMock()):
            with patch.object(service, "_load_enabled_token", AsyncMock(return_value=_token())):
                with patch.object(service, "_write_temp_pdf", AsyncMock(return_value="/tmp/test.pdf")):
                    with patch.object(service, "_cleanup_temp_file", AsyncMock()):
                        with patch(
                            "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.build_filelib_sync_service_for_scheduled_sync",
                            return_value=filelib_service,
                        ):
                            with patch(
                                "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.DeveloperTokenService._get_bound_user_payload",
                                AsyncMock(return_value=UserPayload(user_id=100, user_name="u", tenant_id=5)),
                            ):
                                await service.run(tenant_id=5, trigger_type="manual")

    service.pdf_client.fetch_pdf.assert_awaited_once_with(
        api_url="https://192.168.147.131/automotive.pdf",
        method="GET",
        timeout_seconds=120,
        api_ssl_verify=False,
    )


@pytest.mark.asyncio
async def test_build_filelib_sync_params_omits_external_department_id(async_db_session):
    service = AutomotiveSheetIntroSyncService(session=async_db_session)
    token = _token()
    config = _enabled_config()
    department = SimpleNamespace(name="Dept A", dept_id="EXT-001", external_id="EXT-001")
    user = SimpleNamespace(external_id="USER-001")

    with patch(
        "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.FilelibSyncRepositoryImpl"
    ) as repo_cls:
        repo = repo_cls.return_value
        repo.find_primary_departments = AsyncMock(return_value=[SimpleNamespace(department_id=9)])
        repo.find_department_by_id = AsyncMock(return_value=department)
        repo.find_user_by_id = AsyncMock(return_value=user)

        params = await service._build_filelib_sync_params(token=token, config=config)

    assert params.department_id is None
    assert params.department == "Dept A"
    assert params.responsible_person_id == "USER-001"
    service = _service(async_db_session)
    service.config_service.get_config = AsyncMock(return_value=_enabled_config())
    service.run_log_repository.insert = AsyncMock(return_value=13)
    service.run_log_repository.update = AsyncMock()

    with patch.object(service, "_acquire_lock", AsyncMock(return_value="lock-token")):
        with patch.object(service, "_release_lock", AsyncMock()):
            with patch.object(service, "_load_enabled_token", AsyncMock(side_effect=Exception("token disabled"))):
                result = await service.run(tenant_id=5, trigger_type="scheduled")

    assert result.status == "failed"
