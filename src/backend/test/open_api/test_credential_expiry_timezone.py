"""Offset-bearing API inputs retain their instant in the existing local DB clock."""

import os
import time
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError, PersonalTokenTtlExceededError
from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP, SUBJECT_KIND_SERVICE_ACCOUNT
from bisheng.open_api.domain.models.service_account import ServiceAccount
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest, KeyUpdateRequest
from bisheng.open_api.domain.services.credential_service import CredentialService, hash_token
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService
from bisheng.user.domain.models.user import User


@pytest.fixture(params=["Asia/Shanghai", "UTC", "America/New_York"])
def server_timezone(request):
    previous = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.parametrize("offset", [UTC, timezone(timedelta(hours=-5))])
async def test_issue_update_and_authenticate_after_database_round_trip(
    server_timezone, offset, open_api_db, fake_redis
):
    async with open_api_db() as session:
        session.add(User(user_id=21, user_name="expiry-owner", password=""))
        session.add(UserTenant(user_id=21, tenant_id=1, is_active=1, status="active"))
        account = ServiceAccount(tenant_id=1, name="expiry", resource_owner_user_id=21)
        session.add(account)
        await session.commit()
        await session.refresh(account)
    expiry = (datetime.now(UTC) + timedelta(hours=3)).astimezone(offset)
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=account.id,
        request=KeyIssueRequest(name="expires", expires_at=expiry.isoformat()),
        created_by=21,
    )
    row = await CredentialRepository.get_by_hash(hash_token(issued.plaintext))
    assert row.expires_at == expiry.astimezone().replace(tzinfo=None)
    assert row.is_valid_at(datetime.now())
    assert (await validate_bearer(f"Bearer {issued.plaintext}")).actor_id == account.id

    retained = await CredentialService.update(
        SUBJECT_KIND_SERVICE_ACCOUNT, account.id, issued.id, KeyUpdateRequest(name="renamed")
    )
    assert retained.expires_at == row.expires_at
    expired = datetime.now(UTC) - timedelta(minutes=1)
    await CredentialService.update(
        SUBJECT_KIND_SERVICE_ACCOUNT, account.id, issued.id, KeyUpdateRequest(expires_at=expired)
    )
    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {issued.plaintext}")
    cleared = await CredentialService.update(
        SUBJECT_KIND_SERVICE_ACCOUNT, account.id, issued.id, KeyUpdateRequest(expires_at=None)
    )
    assert cleared.expires_at is None
    assert (await validate_bearer(f"Bearer {issued.plaintext}")).actor_id == account.id


async def test_transactional_issuance_and_personal_token_ttl(server_timezone, open_api_db, fake_redis, monkeypatch):
    expiry = datetime.now(UTC) + timedelta(hours=3)
    request = KeyIssueRequest(name="candidate", expires_at=expiry)
    async with open_api_db() as session:
        issued = await CredentialService.issue_in_transaction(
            session=session,
            tenant_id=1,
            subject_kind=SUBJECT_KIND_HOSTED_APP,
            subject_id=7,
            request=request,
            created_by=21,
        )
        assert issued.is_valid
        assert issued.expires_at == expiry.astimezone().replace(tzinfo=None)
        await session.rollback()
    monkeypatch.setattr(TenantSettingService, "get_policy", AsyncMock(return_value=SimpleNamespace(ttl_days=1)))
    await CredentialService._validate_personal_token(
        tenant_id=1, scopes=["knowledge:read"], expires_at=request.expires_at
    )
    too_late = KeyIssueRequest(name="too-late", expires_at=datetime.now(UTC) + timedelta(days=2))
    with pytest.raises(PersonalTokenTtlExceededError):
        await CredentialService._validate_personal_token(
            tenant_id=1, scopes=["knowledge:read"], expires_at=too_late.expires_at
        )


@pytest.mark.parametrize("request_type", [KeyIssueRequest, KeyUpdateRequest])
def test_naive_and_null_inputs_keep_existing_semantics(server_timezone, request_type):
    old_local_value = datetime(2026, 8, 1, 12, 30)
    assert request_type(name="legacy", expires_at=old_local_value).expires_at == old_local_value
    assert request_type(name="never", expires_at=None).expires_at is None
    assert "expires_at" not in request_type(name="omitted").model_fields_set
