from __future__ import annotations

import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import PortalShareDownloadGrantInvalidError
from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalShareLinkVerifyReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.portal_share_download_grant_service import (
    PortalShareDownloadGrantService,
)


def _service(*, clock=None, ttl_seconds: int = 300) -> PortalShareDownloadGrantService:
    return PortalShareDownloadGrantService(
        secret="unit-test-secret",
        ttl_seconds=ttl_seconds,
        clock=clock or time.time,
    )


def _issue(service: PortalShareDownloadGrantService, **overrides):
    payload = {
        "user_id": 7,
        "tenant_id": 5,
        "share_token": "share-token",
        "space_id": 12,
        "file_id": 1580,
        "allow_download": True,
    }
    payload.update(overrides)
    return service.issue(**payload)


def _verify(service: PortalShareDownloadGrantService, token: str, **overrides):
    expected = {
        "user_id": 7,
        "tenant_id": 5,
        "share_token": "share-token",
        "space_id": 12,
        "file_id": 1580,
    }
    expected.update(overrides)
    return service.verify(token, **expected)


def test_share_download_grant_contains_bound_claims_and_short_ttl() -> None:
    now = int(time.time())
    service = _service(clock=lambda: now, ttl_seconds=300)

    issued = _issue(service)
    claims = _verify(service, issued.token)
    claims_from_download_header = service.verify(
        issued.token,
        user_id=7,
        tenant_id=5,
        space_id=12,
        file_id=1580,
    )

    assert issued.expires_at == now + 300
    assert claims.v == 1
    assert claims.purpose == "portal_share_pdf_download"
    assert claims.aud == "shougang_portal"
    assert claims.sub == "7"
    assert claims.tenant_id == 5
    assert claims.share_token == "share-token"
    assert claims.space_id == 12
    assert claims.file_id == 1580
    assert claims.allow_download is True
    assert claims.iat == now
    assert claims.exp == now + 300
    assert claims.jti
    assert claims_from_download_header.share_token == "share-token"


def test_share_download_grant_never_outlives_share_link() -> None:
    now = int(time.time())
    service = _service(clock=lambda: now, ttl_seconds=300)

    issued = _issue(service, not_after=now + 30)

    assert issued.expires_at == now + 30
    assert _verify(service, issued.token).exp == now + 30
    with pytest.raises(PortalShareDownloadGrantInvalidError):
        _issue(service, not_after=now)


def test_share_download_grant_rejects_tamper_raw_secret_and_wrong_purpose() -> None:
    service = _service()
    issued = _issue(service)
    tampered = issued.token[:-1] + ("a" if issued.token[-1] != "a" else "b")
    with pytest.raises(PortalShareDownloadGrantInvalidError):
        _verify(service, tampered)

    raw_secret_token = jwt.encode(
        {
            "v": 1,
            "purpose": "portal_share_pdf_download",
            "aud": "shougang_portal",
            "sub": "7",
            "tenant_id": 5,
            "share_token": "share-token",
            "space_id": 12,
            "file_id": 1580,
            "allow_download": True,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "jti": "raw-secret",
        },
        "unit-test-secret",
        algorithm="HS256",
    )
    with pytest.raises(PortalShareDownloadGrantInvalidError):
        _verify(service, raw_secret_token)

    payload = jwt.decode(
        issued.token,
        service.signing_key,
        algorithms=["HS256"],
        audience="shougang_portal",
    )
    payload["purpose"] = "portal_share_view"
    wrong_purpose = jwt.encode(payload, service.signing_key, algorithm="HS256")
    with pytest.raises(PortalShareDownloadGrantInvalidError):
        _verify(service, wrong_purpose)


@pytest.mark.parametrize(
    "expected",
    [
        {"user_id": 8},
        {"tenant_id": 6},
        {"share_token": "other-token"},
        {"space_id": 13},
        {"file_id": 1581},
    ],
)
def test_share_download_grant_rejects_cross_context_replay(expected: dict) -> None:
    service = _service()
    issued = _issue(service)

    with pytest.raises(PortalShareDownloadGrantInvalidError):
        _verify(service, issued.token, **expected)


def test_share_download_grant_rejects_expired_and_view_only_issuance() -> None:
    expired_service = _service(clock=lambda: 1, ttl_seconds=1)
    expired = _issue(expired_service)
    with pytest.raises(PortalShareDownloadGrantInvalidError):
        _verify(expired_service, expired.token)

    with pytest.raises(PortalShareDownloadGrantInvalidError):
        _issue(_service(), allow_download=False)


def _share_link(*, status="active", expires_in=300, allow_download=True, visibility="public"):
    return SimpleNamespace(
        share_token="share-token",
        resource_type="knowledge_space_file",
        status=status,
        create_time=datetime.now() - timedelta(seconds=10),
        expire_time=expires_in,
        create_user_id="99",
        meta_data={
            "space_id": 12,
            "file_id": 1580,
            "visibility": visibility,
            "permissions": {"view": True, "download": allow_download, "upload": False},
            "department_id": 33,
        },
    )


@pytest.mark.asyncio
async def test_share_verify_issues_user_bound_grant_only_when_requested() -> None:
    service = KnowledgeSpaceService(MagicMock(), UserPayload(user_id=7, user_name="张三", tenant_id=5))
    issued = SimpleNamespace(token="opaque-download-grant", expires_at=1234567890)
    share_link = _share_link()
    with (
        patch.object(
            service,
            "_get_shougang_portal_share_link",
            new_callable=AsyncMock,
            return_value=share_link,
        ),
        patch(
            "bisheng.knowledge.domain.services.portal_share_download_grant_service."
            "PortalShareDownloadGrantService.issue",
            return_value=issued,
        ) as issue,
    ):
        access = await service.verify_shougang_portal_share_link(
            "share-token",
            ShougangPortalShareLinkVerifyReq(issue_download_grant=True),
        )

    assert access.download_grant == "opaque-download-grant"
    assert access.download_grant_expires_at == 1234567890
    issue.assert_called_once_with(
        user_id=7,
        tenant_id=5,
        share_token="share-token",
        space_id=12,
        file_id=1580,
        allow_download=True,
        not_after=int((share_link.create_time + timedelta(seconds=share_link.expire_time)).timestamp()),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "issue_download_grant", "allow_download"),
    [
        (0, True, True),
        (7, False, True),
        (7, True, False),
    ],
)
async def test_share_verify_never_issues_grant_without_all_download_conditions(
    user_id: int,
    issue_download_grant: bool,
    allow_download: bool,
) -> None:
    service = KnowledgeSpaceService(
        MagicMock(),
        UserPayload(user_id=user_id, user_name="访客", tenant_id=5),
    )
    with (
        patch.object(
            service,
            "_get_shougang_portal_share_link",
            new_callable=AsyncMock,
            return_value=_share_link(allow_download=allow_download),
        ),
        patch(
            "bisheng.knowledge.domain.services.portal_share_download_grant_service."
            "PortalShareDownloadGrantService.issue",
        ) as issue,
    ):
        access = await service.verify_shougang_portal_share_link(
            "share-token",
            ShougangPortalShareLinkVerifyReq(issue_download_grant=issue_download_grant),
        )

    assert access.download_grant == ""
    assert access.download_grant_expires_at is None
    issue.assert_not_called()


@pytest.mark.asyncio
async def test_share_download_live_recheck_accepts_current_public_link() -> None:
    service = KnowledgeSpaceService(MagicMock(), UserPayload(user_id=7, user_name="张三", tenant_id=5))
    with patch.object(
        service,
        "_get_shougang_portal_share_link",
        new_callable=AsyncMock,
        return_value=_share_link(),
    ):
        await service.require_shougang_portal_share_download(
            share_token="share-token",
            space_id=12,
            file_id=1580,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "share_link",
    [
        _share_link(status="disabled"),
        _share_link(expires_in=1),
        _share_link(allow_download=False),
    ],
)
async def test_share_download_live_recheck_blocks_revoked_expired_or_view_only_link(share_link) -> None:
    if share_link.expire_time == 1:
        share_link.create_time = datetime.now() - timedelta(seconds=5)
    service = KnowledgeSpaceService(MagicMock(), UserPayload(user_id=7, user_name="张三", tenant_id=5))
    with patch.object(
        service,
        "_get_shougang_portal_share_link",
        new_callable=AsyncMock,
        return_value=share_link,
    ):
        with pytest.raises(PortalShareDownloadGrantInvalidError):
            await service.require_shougang_portal_share_download(
                share_token="share-token",
                space_id=12,
                file_id=1580,
            )


@pytest.mark.asyncio
async def test_share_download_live_recheck_rechecks_department_scope() -> None:
    service = KnowledgeSpaceService(MagicMock(), UserPayload(user_id=7, user_name="张三", tenant_id=5))
    with (
        patch.object(
            service,
            "_get_shougang_portal_share_link",
            new_callable=AsyncMock,
            return_value=_share_link(visibility="department"),
        ),
        patch.object(
            service,
            "_require_shougang_portal_share_department_access",
            new_callable=AsyncMock,
            side_effect=RuntimeError("department changed"),
        ),
    ):
        with pytest.raises(PortalShareDownloadGrantInvalidError):
            await service.require_shougang_portal_share_download(
                share_token="share-token",
                space_id=12,
                file_id=1580,
            )
