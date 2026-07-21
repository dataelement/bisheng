from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from bisheng.common.errcode import knowledge_space as knowledge_space_errcode
from bisheng.core.config.settings import KnowledgeConf, KnowledgePdfWatermarkConf
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalShareLinkAccessResp,
    ShougangPortalShareLinkVerifyReq,
)
from bisheng.knowledge.domain.schemas.portal_pdf_download_schema import (
    PortalPdfDownloadEntryPoint,
    PortalPdfDownloadRequest,
    PortalShareDownloadGrantClaims,
)


def test_pdf_watermark_config_defaults_and_knowledge_binding() -> None:
    config = KnowledgePdfWatermarkConf()

    assert config.timeout_seconds == 60
    assert config.max_concurrency == 2
    assert config.user_lock_ttl_seconds == 90
    assert config.process_terminate_grace_seconds == 2
    assert KnowledgeConf().pdf_watermark == config


@pytest.mark.parametrize(
    "payload",
    [
        {"timeout_seconds": 0},
        {"max_concurrency": 0},
        {"process_terminate_grace_seconds": 0},
        {"timeout_seconds": 60, "user_lock_ttl_seconds": 60},
    ],
)
def test_pdf_watermark_config_rejects_unsafe_limits(payload: dict) -> None:
    with pytest.raises(ValidationError):
        KnowledgePdfWatermarkConf.model_validate(payload)


def test_portal_download_entry_points_preserve_all_supported_values() -> None:
    values = {
        "search",
        "knowledge_list",
        "detail",
        "home_recommendation",
        "favorite",
        "share",
        "expert_qa",
        "qa_citation",
        "other",
    }

    assert {item.value for item in PortalPdfDownloadEntryPoint} == values
    for value in values:
        request = PortalPdfDownloadRequest(space_id=12, file_id=1580, entry_point=value)
        assert request.entry_point.value == value


@pytest.mark.parametrize("value", [None, "", "unknown", " SEARCH "])
def test_portal_download_entry_point_normalizes_invalid_values(value: str | None) -> None:
    request = PortalPdfDownloadRequest(space_id=12, file_id=1580, entry_point=value)
    assert request.entry_point is PortalPdfDownloadEntryPoint.OTHER


def test_internal_share_download_grant_contract_is_user_and_resource_bound() -> None:
    claims = PortalShareDownloadGrantClaims(
        sub="7",
        tenant_id=5,
        share_token="share-token",
        space_id=12,
        file_id=1580,
        allow_download=True,
        iat=1_721_558_400,
        exp=1_721_558_700,
        jti="grant-id",
    )

    assert claims.v == 1
    assert claims.purpose == "portal_share_pdf_download"
    assert claims.aud == "shougang_portal"
    assert claims.sub == "7"
    assert claims.tenant_id == 5
    assert claims.share_token == "share-token"
    assert claims.space_id == 12
    assert claims.file_id == 1580
    assert claims.allow_download is True

    verify_request = ShougangPortalShareLinkVerifyReq(issue_download_grant=True)
    access = ShougangPortalShareLinkAccessResp(
        share_token="share-token",
        space_id=12,
        file_id=1580,
        allow_download=True,
        download_grant="opaque",
        download_grant_expires_at=1_721_558_700,
    )
    assert verify_request.issue_download_grant is True
    assert access.download_grant == "opaque"
    assert access.download_grant_expires_at == 1_721_558_700


def test_portal_pdf_download_error_codes_are_unique_180xx_values() -> None:
    expected = {
        "PortalPdfArtifactUnavailableError": 18085,
        "PortalPdfDownloadBusyError": 18086,
        "PortalPdfDownloadTimeoutError": 18087,
        "PortalShareDownloadGrantInvalidError": 18088,
        "PortalPdfDownloadGenerationError": 18089,
        "PortalPdfDownloadServiceUnavailableError": 18090,
    }
    all_codes = [
        value.Code
        for _, value in inspect.getmembers(knowledge_space_errcode, inspect.isclass)
        if value.__module__ == knowledge_space_errcode.__name__ and hasattr(value, "Code")
    ]

    assert len(all_codes) == len(set(all_codes))
    for class_name, code in expected.items():
        error_type = getattr(knowledge_space_errcode, class_name)
        assert error_type.Code == code
        assert 18000 <= error_type.Code <= 18099
