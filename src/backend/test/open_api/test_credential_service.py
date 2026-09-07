from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import func, select

from bisheng.common.errcode.open_api import OpenApiDelegateConfigurationInvalidError
from bisheng.open_api.domain.models.api_credential import (
    REVOKE_REASON_MANUAL,
    SUBJECT_KIND_SERVICE_ACCOUNT,
    ApiCredential,
)
from bisheng.open_api.domain.models.credential_delegate_scope import ApiCredentialDelegateScope
from bisheng.open_api.domain.schemas.credential import (
    DelegateScopeInput,
    KeyIssueRequest,
    KeyUpdateRequest,
)
from bisheng.open_api.domain.services.credential_service import CredentialService, hash_token


async def test_issue_stores_only_hash_and_returns_plaintext_once(open_api_db, fake_redis):
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=7,
        request=KeyIssueRequest(name="production", scopes=["knowledge:read"]),
        created_by=3,
    )
    assert issued.plaintext.startswith("bs-sak-")
    assert issued.key_mask.startswith("bs-sak-********")

    async with open_api_db() as session:
        row = (await session.exec(select(ApiCredential))).one()
    assert row.token_hash == hash_token(issued.plaintext)
    assert issued.plaintext not in row.model_dump_json()
    assert not hasattr(row, "plaintext")


async def test_update_and_revoke_invalidate_positive_cache(open_api_db, fake_redis):
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=7,
        request=KeyIssueRequest(name="old", scopes=["knowledge:read"]),
        created_by=3,
    )
    digest = hash_token(issued.plaintext)
    fake_redis.values[f"oapi:cred:{digest}"] = {"cached": True}
    updated = await CredentialService.update(
        SUBJECT_KIND_SERVICE_ACCOUNT,
        7,
        issued.id,
        KeyUpdateRequest(name="new"),
    )
    assert updated.name == "new"
    assert f"oapi:cred:{digest}" not in fake_redis.values

    fake_redis.values[f"oapi:cred:{digest}"] = {"cached": True}
    revoked = await CredentialService.revoke(
        SUBJECT_KIND_SERVICE_ACCOUNT,
        7,
        issued.id,
        reason=REVOKE_REASON_MANUAL,
    )
    assert revoked.revoked_at is not None
    assert revoked.revoke_reason == REVOKE_REASON_MANUAL
    assert f"oapi:cred:{digest}" not in fake_redis.values


async def test_last_used_write_is_throttled(open_api_db, fake_redis):
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=7,
        request=KeyIssueRequest(name="key", expires_at=datetime.now() + timedelta(days=1)),
        created_by=3,
    )
    assert await CredentialService.touch_last_used(issued.id) is True
    assert await CredentialService.touch_last_used(issued.id) is False


async def test_removing_delegate_scope_clears_entries_atomically(
    open_api_db,
    fake_redis,
    monkeypatch,
):
    async def active_user(user_id):
        return SimpleNamespace(user_id=user_id, tenant_id=1)

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.delegate_scope_service."
        "OwnerRepository.get_active_natural_person",
        active_user,
    )
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=7,
        request=KeyIssueRequest(
            name="delegated",
            scopes=["knowledge:read", "delegate"],
            delegate_scopes=[DelegateScopeInput(subject_type="user", subject_id=9)],
        ),
        created_by=3,
    )

    updated = await CredentialService.update(
        SUBJECT_KIND_SERVICE_ACCOUNT,
        7,
        issued.id,
        KeyUpdateRequest(scopes=["knowledge:read"]),
    )

    assert updated.delegate_scopes == []
    async with open_api_db() as session:
        count = (await session.exec(select(func.count()).select_from(ApiCredentialDelegateScope))).one()
    assert count == 0


async def test_delegate_requires_nonempty_scope_and_service_account(open_api_db, fake_redis):
    with pytest.raises(OpenApiDelegateConfigurationInvalidError):
        await CredentialService.issue(
            tenant_id=1,
            subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
            subject_id=7,
            request=KeyIssueRequest(name="empty", scopes=["delegate"]),
            created_by=3,
        )

    with pytest.raises(OpenApiDelegateConfigurationInvalidError):
        await CredentialService.issue(
            tenant_id=1,
            subject_kind="natural_person",
            subject_id=3,
            request=KeyIssueRequest(
                name="pat",
                scopes=["knowledge:read"],
                delegate_scopes=[DelegateScopeInput(subject_type="user", subject_id=9)],
            ),
            created_by=3,
        )
