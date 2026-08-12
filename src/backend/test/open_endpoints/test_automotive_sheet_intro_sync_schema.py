import pytest
from pydantic import ValidationError

from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import (
    AutomotiveSheetIntroSyncConfig,
    DEFAULT_AUTOMOTIVE_SHEET_EXTERNAL_FILE_ID,
    DEFAULT_AUTOMOTIVE_SHEET_FILE_NAME,
    default_automotive_sheet_intro_sync_config,
    strip_legacy_automotive_sheet_intro_sync_config_keys,
)


def _enabled_payload() -> dict:
    return {
        "enabled": True,
        "api_url": "https://example.com/automotive.pdf",
        "developer_token_id": 10,
    }


def test_default_config_values():
    config = default_automotive_sheet_intro_sync_config()
    assert config.enabled is False
    assert config.file_name == DEFAULT_AUTOMOTIVE_SHEET_FILE_NAME
    assert config.external_file_id == DEFAULT_AUTOMOTIVE_SHEET_EXTERNAL_FILE_ID
    assert config.api_method == "GET"
    assert config.api_timeout_seconds == 120
    assert config.api_ssl_verify is True


def test_disabled_config_allows_minimal_payload():
    config = AutomotiveSheetIntroSyncConfig.model_validate({"enabled": False})
    assert config.enabled is False
    assert config.api_url is None


def test_enabled_config_requires_core_fields():
    with pytest.raises(ValidationError):
        AutomotiveSheetIntroSyncConfig.model_validate({"enabled": True})


def test_enabled_config_accepts_minimal_payload():
    config = AutomotiveSheetIntroSyncConfig.model_validate(_enabled_payload())
    assert config.enabled is True
    assert config.api_url == "https://example.com/automotive.pdf"
    assert config.developer_token_id == 10


def test_file_name_must_be_pdf_basename():
    payload = _enabled_payload()
    payload["file_name"] = "nested/汽车板介绍.pdf"
    with pytest.raises(ValidationError):
        AutomotiveSheetIntroSyncConfig.model_validate(payload)

    payload["file_name"] = "汽车板介绍.txt"
    with pytest.raises(ValidationError):
        AutomotiveSheetIntroSyncConfig.model_validate(payload)


def test_api_url_must_be_http_or_https():
    payload = _enabled_payload()
    payload["api_url"] = "ftp://example.com/file.pdf"
    with pytest.raises(ValidationError):
        AutomotiveSheetIntroSyncConfig.model_validate(payload)


def test_strip_legacy_config_keys():
    payload = {
        "enabled": True,
        "api_url": "https://example.com/automotive.pdf",
        "developer_token_id": 10,
        "category": {"code": "DOC", "subcategory_code": "INTRO"},
        "business_domain": {"mode": "fixed", "code": "AUTO"},
        "target_space": {"mode": "fixed", "knowledge_id": 100, "folder_mode": "none"},
    }
    cleaned = strip_legacy_automotive_sheet_intro_sync_config_keys(payload)
    config = AutomotiveSheetIntroSyncConfig.model_validate(cleaned)
    assert config.enabled is True
    assert "category" not in config.model_dump()
