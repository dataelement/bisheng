from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncConfig
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams, FilelibSyncResponseData
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service import (
    AUTOMOTIVE_SHEET_INTRO_SYNC_ENDPOINT_TAG,
    AutomotiveSheetIntroSyncService,
)


@pytest.fixture(autouse=True)
def _tenant_context():
    token = set_current_tenant_id(5)
    yield
    current_tenant_id.reset(token)


@pytest.mark.asyncio
async def test_two_runs_use_same_fixed_filename_and_endpoint(async_db_session):
    config = AutomotiveSheetIntroSyncConfig.model_validate(
        {
            "enabled": True,
            "api_url": "https://example.com/automotive.pdf",
            "developer_token_id": 10,
            "file_name": "汽车板介绍.pdf",
        }
    )
    service = AutomotiveSheetIntroSyncService(session=async_db_session)
    service.config_service = MagicMock()
    service.config_service.get_config = AsyncMock(return_value=config)
    service.pdf_client = MagicMock()
    service.pdf_client.fetch_pdf = AsyncMock(return_value=b"%PDF-1.4")
    service.run_log_repository.insert = AsyncMock(side_effect=[1, 2])
    service.run_log_repository.update = AsyncMock()

    params = FilelibSyncParams(external_file_id="automotive_sheet_intro", file_name="汽车板介绍.pdf")
    filelib_service = MagicMock()
    filelib_service.sync_from_staged_file = AsyncMock(
        side_effect=[
            FilelibSyncResponseData(
                external_file_id="automotive_sheet_intro",
                file_id=901,
                file_encoding="ENC-1",
                knowledge_id=100,
                knowledge_name="space",
                status=5,
                replaced_file_id=None,
            ),
            FilelibSyncResponseData(
                external_file_id="automotive_sheet_intro",
                file_id=902,
                file_encoding="ENC-2",
                knowledge_id=100,
                knowledge_name="space",
                status=5,
                replaced_file_id=901,
            ),
        ]
    )

    token = DeveloperToken(
        id=10,
        tenant_id=5,
        user_id=100,
        name="scheduled-token",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bs_abc",
        enabled=True,
        file_sync_rule={
            "category": {"code": "DOC", "subcategory_code": "INTRO"},
            "business_domain": {"mode": "fixed", "code": "AUTO"},
            "target_space": {
                "mode": "fixed",
                "knowledge_id": 100,
                "folder_mode": "none",
            },
        },
    )

    with patch.object(service, "_acquire_lock", AsyncMock(return_value="lock")):
        with patch.object(service, "_release_lock", AsyncMock()):
            with patch.object(service, "_load_enabled_token", AsyncMock(return_value=token)):
                with patch.object(service, "_build_filelib_sync_params", AsyncMock(return_value=params)):
                    with patch.object(service, "_write_temp_pdf", AsyncMock(return_value="/tmp/a.pdf")):
                        with patch.object(service, "_cleanup_temp_file", AsyncMock()):
                            with patch(
                                "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.build_filelib_sync_service_for_scheduled_sync",
                                return_value=filelib_service,
                            ):
                                with patch(
                                    "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.DeveloperTokenService._get_bound_user_payload",
                                    AsyncMock(),
                                ):
                                    first = await service.run(tenant_id=5, trigger_type="scheduled")
                                    second = await service.run(tenant_id=5, trigger_type="scheduled")

    assert first.status == "success"
    assert second.status == "success"
    assert filelib_service.sync_from_staged_file.await_count == 2
    for call in filelib_service.sync_from_staged_file.await_args_list:
        assert call.kwargs["params"].file_name == "汽车板介绍.pdf"
        assert call.kwargs["endpoint_tag"] == AUTOMOTIVE_SHEET_INTRO_SYNC_ENDPOINT_TAG
    assert filelib_service.sync_from_staged_file.await_args_list[1].kwargs["params"].file_name == "汽车板介绍.pdf"
