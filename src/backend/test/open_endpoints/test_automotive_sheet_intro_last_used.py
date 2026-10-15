"""定时同步成功请求上游后, 把上游 IP 和成功时间写入 developer_token."""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncConfig
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams, FilelibSyncResponseData
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_client import (
    AutomotiveSheetIntroFetchedPdf,
)
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service import (
    AutomotiveSheetIntroSyncService,
)

_UPSTREAM_IP = "203.0.113.10"
_SUCCEEDED_AT = datetime(2026, 10, 15, 11, 31, 0)


def _mysql_async_url() -> str:
    """读取 config.yaml 里的 171 库地址, 不打印口令."""
    from bisheng.core.config.settings import decrypt_token

    cfg_name = os.environ.get("config", "config.yaml")
    cfg_path = Path(__file__).resolve().parents[2] / "bisheng" / Path(cfg_name).name
    loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    url = loaded["database_url"]
    match = re.search(r"(?<=:)[^:]+(?=@)", url)
    if match:
        url = re.sub(r"(?<=:)[^:]+(?=@)", decrypt_token(match.group(0)), url)
    return url.replace("pymysql", "aiomysql")


def _service(session) -> AutomotiveSheetIntroSyncService:
    config_service = MagicMock()
    config_service.get_config = AsyncMock(
        return_value=AutomotiveSheetIntroSyncConfig.model_validate(
            {
                "enabled": True,
                "api_url": "https://imp.sggf.com.cn/excel/vama/exportProductPdf",
                "developer_token_id": 1,
            }
        )
    )
    pdf_client = MagicMock()
    return AutomotiveSheetIntroSyncService(
        session=session,
        config_service=config_service,
        pdf_client=pdf_client,
    )


async def _run(service: AutomotiveSheetIntroSyncService, token_id: int, trigger_type: str, fetched):
    token = DeveloperToken(
        id=token_id,
        tenant_id=1,
        user_id=1,
        name="last-used-flow",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bst_test",
        enabled=True,
        file_sync_rule={
            "category": {"code": "CAS", "subcategory_code": "CAS-PVA7"},
            "business_domain": {"mode": "fixed", "code": "IT"},
            "target_space": {"mode": "fixed", "knowledge_id": 100, "folder_mode": "fixed", "folder_path": "test"},
        },
    )
    filelib_service = MagicMock()
    filelib_service.sync_from_staged_file = AsyncMock(
        return_value=FilelibSyncResponseData(
            external_file_id="automotive_sheet_intro",
            file_id=1,
            file_encoding="ENC",
            knowledge_id=100,
            knowledge_name="信息",
            status=5,
        )
    )
    service.pdf_client.fetch_pdf = AsyncMock(return_value=fetched)
    service.run_log_repository.insert = AsyncMock(return_value=1)
    service.run_log_repository.update = AsyncMock()
    service._build_filelib_sync_params = AsyncMock(
        return_value=FilelibSyncParams(external_file_id="automotive_sheet_intro", file_name="汽车板介绍.pdf")
    )
    with patch.object(service, "_acquire_lock", AsyncMock(return_value="lock")):
        with patch.object(service, "_release_lock", AsyncMock()):
            with patch.object(service, "_load_enabled_token", AsyncMock(return_value=token)):
                with patch.object(service, "_write_temp_pdf", AsyncMock(return_value="/tmp/a.pdf")):
                    with patch.object(service, "_cleanup_temp_file", AsyncMock()):
                        with patch(
                            "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.build_filelib_sync_service_for_scheduled_sync",
                            return_value=filelib_service,
                        ):
                            with patch(
                                "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service.DeveloperTokenService._get_bound_user_payload",
                                AsyncMock(return_value=UserPayload(user_id=1, user_name="admin", tenant_id=1)),
                            ):
                                return await service.run(tenant_id=1, trigger_type=trigger_type)


@pytest.mark.asyncio
async def test_scheduled_sync_writes_upstream_last_used_on_mysql():
    """定时同步在上游成功后写入 developer_token, 手动测试不再改这两列."""
    engine = create_async_engine(_mysql_async_url())
    token_hash = uuid.uuid4().hex
    token_id: int | None = None
    tenant_token = set_current_tenant_id(1)

    @asynccontextmanager
    async def sessions():
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    try:
        async with sessions() as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO developer_token (
                        tenant_id, user_id, name, token_hash, token_ciphertext, token_prefix,
                        enabled, logic_delete
                    ) VALUES (
                        1, 1, :name, :token_hash, 'cipher', 'bst_test', 1, 0
                    )
                    """
                ),
                params={"name": f"last-used-flow-{token_hash[:8]}", "token_hash": token_hash},
            )
            await session.commit()
            token_id = int(result.lastrowid)

        with patch(
            "bisheng.developer_token.domain.repositories.developer_token_repository.get_async_db_session",
            sessions,
        ):
            service = _service(MagicMock())
            scheduled = await _run(
                service,
                token_id,
                "scheduled",
                AutomotiveSheetIntroFetchedPdf(
                    content=b"%PDF-1.4",
                    upstream_ip=_UPSTREAM_IP,
                    succeeded_at=_SUCCEEDED_AT,
                ),
            )
            assert scheduled.status == "success"

            async with sessions() as session:
                row = (
                    await session.execute(
                        text("SELECT last_used_ip, last_used_time FROM developer_token WHERE id = :token_id"),
                        params={"token_id": token_id},
                    )
                ).one()
            assert row[0] == _UPSTREAM_IP
            assert row[1] == _SUCCEEDED_AT

            manual = await _run(
                service,
                token_id,
                "manual",
                AutomotiveSheetIntroFetchedPdf(
                    content=b"%PDF-1.4",
                    upstream_ip="198.51.100.8",
                    succeeded_at=datetime(2026, 10, 15, 12, 0, 0),
                ),
            )
            assert manual.status == "success"
            async with sessions() as session:
                again = (
                    await session.execute(
                        text("SELECT last_used_ip, last_used_time FROM developer_token WHERE id = :token_id"),
                        params={"token_id": token_id},
                    )
                ).one()
            assert again[0] == _UPSTREAM_IP
            assert again[1] == _SUCCEEDED_AT
    finally:
        current_tenant_id.reset(tenant_token)
        if token_id is not None:
            async with sessions() as session:
                await session.execute(
                    text("DELETE FROM developer_token WHERE id = :token_id"),
                    params={"token_id": token_id},
                )
                await session.commit()
        await engine.dispose()
