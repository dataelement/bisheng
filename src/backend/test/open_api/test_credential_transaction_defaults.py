"""Candidate credentials stay readable on databases without INSERT RETURNING."""

import pytest
from sqlalchemy import inspect

from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.schemas.credential import KeyItem


@pytest.mark.parametrize("insert_returning", [True, False])
async def test_candidate_defaults_loaded_without_committing(open_api_db, monkeypatch, insert_returning):
    async with open_api_db() as session:
        monkeypatch.setattr(session.bind.dialect, "insert_returning", insert_returning)
        row = ApiCredential(
            tenant_id=1,
            subject_kind="hosted_app",
            subject_id=1,
            name="transaction-defaults",
            key_prefix="bs-app-",
            last4="test",
            token_hash="a" * 64,
            scopes=[],
        )
        result = await CredentialRepository.create_in_transaction(session, row)
        item = KeyItem.from_row(result)
        assert item.create_time is not None
        assert not inspect(result).expired_attributes
        credential_id = item.id
        # Refresh must not commit the caller's candidate credential transaction.
        await session.rollback()
        assert await session.get(ApiCredential, credential_id) is None
