from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncInvalidConfigError
from bisheng.common.errcode.developer_token import DeveloperTokenDisabledError, DeveloperTokenMissingError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.open_endpoints.domain.repositories.interfaces.automotive_sheet_intro_sync_config_repository import (
    AutomotiveSheetIntroSyncConfigRecord,
)
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service import (
    AutomotiveSheetIntroSyncConfigService,
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


def _enabled_payload() -> dict:
    return {
        "enabled": True,
        "api_url": "https://example.com/automotive.pdf",
        "developer_token_id": 10,
    }


@pytest.fixture(autouse=True)
def _tenant_context():
    token = set_current_tenant_id(5)
    yield
    current_tenant_id.reset(token)


@pytest.mark.asyncio
async def test_get_config_returns_defaults_when_missing():
    repository = MagicMock()
    repository.get = AsyncMock(return_value=None)
    service = AutomotiveSheetIntroSyncConfigService(repository)

    config = await service.get_config(5)

    assert config.enabled is False
    assert config.file_name == "汽车板介绍.pdf"


@pytest.mark.asyncio
async def test_get_config_merges_stored_values_and_strips_legacy_keys():
    repository = MagicMock()
    repository.get = AsyncMock(
        return_value=AutomotiveSheetIntroSyncConfigRecord(
            key="automotive_sheet_intro_sync:t:5",
            value=json.dumps(
                {
                    "enabled": True,
                    "api_url": "https://example.com/x.pdf",
                    "developer_token_id": 10,
                    "category": {"code": "DOC", "subcategory_code": "INTRO"},
                    "business_domain": {"mode": "fixed", "code": "AUTO"},
                    "target_space": {
                        "mode": "fixed",
                        "knowledge_id": 100,
                        "folder_mode": "none",
                    },
                }
            ),
        )
    )
    service = AutomotiveSheetIntroSyncConfigService(repository)

    config = await service.get_config(5)

    assert config.enabled is True
    assert config.api_url == "https://example.com/x.pdf"
    assert config.file_name == "汽车板介绍.pdf"


@pytest.mark.asyncio
async def test_save_disabled_config_skips_token_validation(monkeypatch):
    repository = MagicMock()
    repository.get = AsyncMock(return_value=None)
    repository.write_value = AsyncMock()
    service = AutomotiveSheetIntroSyncConfigService(repository)
    validate = AsyncMock()
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service.DeveloperTokenService._validate_file_sync_rule",
        validate,
    )

    saved = await service.save_config(5, {"enabled": False})

    assert saved.enabled is False
    validate.assert_not_awaited()
    repository.write_value.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_enabled_config_validates_token_file_sync_rule(monkeypatch):
    repository = MagicMock()
    repository.write_value = AsyncMock()
    service = AutomotiveSheetIntroSyncConfigService(repository)
    token = DeveloperToken(
        id=10,
        tenant_id=5,
        user_id=100,
        name="token",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bs_abc",
        enabled=True,
        file_sync_rule=_file_sync_rule(),
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service.DeveloperTokenRepository.get_token_by_id",
        AsyncMock(return_value=token),
    )
    validate_rule = AsyncMock(return_value=_file_sync_rule())
    validate_target = AsyncMock(return_value=MagicMock(id=100))
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service.DeveloperTokenService._validate_file_sync_rule",
        validate_rule,
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service.DeveloperTokenService._validate_file_sync_target",
        validate_target,
    )

    saved = await service.save_config(5, _enabled_payload())

    assert saved.enabled is True
    validate_rule.assert_awaited_once()
    validate_target.assert_awaited_once()
    repository.write_value.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_enabled_config_rejects_missing_token(monkeypatch):
    repository = MagicMock()
    service = AutomotiveSheetIntroSyncConfigService(repository)
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service.DeveloperTokenRepository.get_token_by_id",
        AsyncMock(return_value=None),
    )

    with pytest.raises(DeveloperTokenMissingError):
        await service.save_config(5, _enabled_payload())


@pytest.mark.asyncio
async def test_save_enabled_config_rejects_disabled_token(monkeypatch):
    repository = MagicMock()
    service = AutomotiveSheetIntroSyncConfigService(repository)
    token = DeveloperToken(
        id=10,
        tenant_id=5,
        user_id=100,
        name="token",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bs_abc",
        enabled=False,
        file_sync_rule=_file_sync_rule(),
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service.DeveloperTokenRepository.get_token_by_id",
        AsyncMock(return_value=token),
    )

    with pytest.raises(DeveloperTokenDisabledError):
        await service.save_config(5, _enabled_payload())


@pytest.mark.asyncio
async def test_save_enabled_config_rejects_token_without_file_sync_rule(monkeypatch):
    repository = MagicMock()
    service = AutomotiveSheetIntroSyncConfigService(repository)
    token = DeveloperToken(
        id=10,
        tenant_id=5,
        user_id=100,
        name="token",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bs_abc",
        enabled=True,
        file_sync_rule=None,
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_config_service.DeveloperTokenRepository.get_token_by_id",
        AsyncMock(return_value=token),
    )

    with pytest.raises(AutomotiveSheetIntroSyncInvalidConfigError):
        await service.save_config(5, _enabled_payload())


@pytest.mark.asyncio
async def test_save_config_rejects_invalid_payload():
    repository = MagicMock()
    service = AutomotiveSheetIntroSyncConfigService(repository)

    with pytest.raises(AutomotiveSheetIntroSyncInvalidConfigError):
        await service.save_config(5, {"enabled": True})
