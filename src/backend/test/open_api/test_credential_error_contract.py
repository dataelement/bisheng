"""Credential lifecycle failures retain their PRD error codes on the wire."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.credential_service import hash_token


@pytest.mark.parametrize("subject_kind", ["service_account", "natural_person"])
@pytest.mark.parametrize(
    "state",
    [
        "unknown",
        "wrong_hash",
        "expired",
        "manual",
        "batch",
        "regenerated",
        "subject_disabled",
        "subject_deleted",
        "holder_missing",
        "tenant_mismatch",
    ],
)
async def test_lifecycle_denials_use_distinct_codes(fake_redis, monkeypatch, subject_kind, state):
    plaintext = ("bs-sak-" if subject_kind == "service_account" else "bs-pat-") + "a" * 43
    row = ApiCredential(
        id=1,
        tenant_id=2,
        subject_kind=subject_kind,
        subject_id=7,
        name="fixture",
        key_prefix=plaintext[:7],
        last4="aaaa",
        token_hash=hash_token(plaintext),
    )
    expected_code = 26002
    if state == "expired":
        row.expires_at = datetime.now() - timedelta(seconds=1)
    elif state == "wrong_hash":
        row.token_hash = "0" * 64
    elif state in {"manual", "batch", "regenerated", "subject_disabled", "subject_deleted"}:
        row.revoked_at = datetime.now()
        row.revoke_reason = state
    if state in {"subject_disabled", "subject_deleted", "holder_missing"}:
        expected_code = 26027 if subject_kind == "service_account" else 26043
    if state == "tenant_mismatch" and subject_kind == "natural_person":
        expected_code = 26043
    holder = (
        None
        if state == "holder_missing"
        else SimpleNamespace(
            id=7,
            user_id=7,
            name="fixture",
            user_name="fixture",
            tenant_id=3 if state == "tenant_mismatch" else 2,
            is_enabled=True,
            resource_owner_user_id=9,
        )
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.credential_validator.CredentialRepository.get_by_hash",
        AsyncMock(return_value=None if state == "unknown" else row),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.credential_validator.ServiceAccountRepository.get",
        AsyncMock(return_value=holder),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.repositories.owner_repository.OwnerRepository.get_active_natural_person",
        AsyncMock(return_value=holder),
    )
    app = FastAPI()
    register_open_api_exception_handlers(app)
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])

    @router.get("/probe")
    @open_api_scope(None)
    async def probe():
        pytest.fail("An invalid credential must never reach business code")

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v2/probe", headers={"Authorization": f"Bearer {plaintext}"})
    assert (response.status_code, response.json()["status_code"]) == (401, expected_code)
