from datetime import datetime, timedelta

import pytest

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiCredentialInvalidError,
    OpenApiCredentialMissingError,
)
from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_SERVICE_ACCOUNT
from bisheng.open_api.domain.models.service_account import ServiceAccount
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest
from bisheng.open_api.domain.services.credential_service import CredentialService, hash_token
from bisheng.open_api.domain.services.credential_validator import extract_bearer_token, validate_bearer


async def seed_service_account(open_api_db, *, disabled=False):
    async with open_api_db() as session:
        row = ServiceAccount(
            tenant_id=1,
            name="integration",
            resource_owner_user_id=21,
            disabled_at=datetime.now() if disabled else None,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


def test_bearer_extraction_rejects_jwt_and_malformed_values():
    for value in (None, "", "Bearer jwt.header.payload", "Basic abc", "Bearer bs-sak-short"):
        with pytest.raises(OpenApiCredentialMissingError):
            extract_bearer_token(value)


async def test_valid_service_account_key_builds_independent_principal(open_api_db, fake_redis):
    account = await seed_service_account(open_api_db)
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=account.id,
        request=KeyIssueRequest(name="key", scopes=["knowledge:read"]),
        created_by=3,
    )
    principal = await validate_bearer(f"Bearer {issued.plaintext}")
    assert (principal.actor_kind, principal.actor_id) == ("service_account", account.id)
    assert principal.authorization_subject_type == "service_account"
    assert principal.resource_owner_user_id == 21
    assert issued.plaintext not in repr(fake_redis.values)


async def test_revoked_expired_disabled_and_prefix_mismatch_fail_closed(open_api_db, fake_redis):
    account = await seed_service_account(open_api_db, disabled=True)
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=account.id,
        request=KeyIssueRequest(name="key", expires_at=datetime.now() + timedelta(days=1)),
        created_by=3,
    )
    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {issued.plaintext}")

    digest = hash_token(issued.plaintext)
    fake_redis.values[f"oapi:cred:{digest}"] = {
        "credential_id": issued.id,
        "actor_kind": "natural_person",
        "actor_id": account.id,
        "actor_name": "collision",
        "tenant_id": 1,
        "resource_owner_user_id": None,
        "scopes": [],
        "mode": "S",
        "authorization_subject_type": "user",
        "authorization_subject_id": account.id,
        "effective_user_id": account.id,
    }
    with pytest.raises(OpenApiCredentialInvalidError):
        await validate_bearer(f"Bearer {issued.plaintext}")


async def test_redis_failure_is_dependency_unavailable(open_api_db, fake_redis, monkeypatch):
    async def fail(_key):
        raise OSError("redis unavailable")

    fake_redis.aget = fail
    with pytest.raises(OpenApiAuthDependencyUnavailableError):
        await validate_bearer("Bearer bs-sak-" + "a" * 43)
