"""Issuance and governance for natural-person access tokens."""

from __future__ import annotations

from datetime import datetime, timedelta

from bisheng.common.errcode.open_api import PersonalTokenDisabledError, PersonalTokenHolderInvalidError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.open_api.domain.models.api_credential import (
    REVOKE_REASON_MANUAL,
    REVOKE_REASON_REGENERATED,
    SUBJECT_KIND_NATURAL_PERSON,
    ApiCredential,
)
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.repositories.owner_repository import NaturalPersonRecord, OwnerRepository
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest, KeyItem
from bisheng.open_api.domain.schemas.personal_token import (
    PersonalTokenIssued,
    PersonalTokenLedgerItem,
    PersonalTokenLedgerPage,
    PersonalTokenStatus,
)
from bisheng.open_api.domain.services.credential_service import CredentialService
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService

PERSONAL_TOKEN_SCOPE = "knowledge:read"
PERSONAL_TOKEN_NAME = "Personal access token"


class PersonalTokenService:
    @classmethod
    async def status(cls, *, tenant_id: int, user_id: int) -> PersonalTokenStatus:
        setting = await TenantSettingService.get_response(tenant_id)
        token = await cls._current_item(tenant_id=tenant_id, user_id=user_id)
        return PersonalTokenStatus(
            enabled=setting.effective_enabled,
            token=token,
            holder_is_admin=await cls._is_admin(user_id, tenant_id),
        )

    @classmethod
    async def issue(cls, *, tenant_id: int, user_id: int, operator) -> PersonalTokenIssued:
        setting = await TenantSettingService.get_response(tenant_id)
        if not setting.effective_enabled:
            raise PersonalTokenDisabledError()
        holder = await cls._active_holder(user_id, tenant_id)
        holder_is_admin = await cls._is_admin(user_id, tenant_id)
        ttl_days = setting.pat_ttl_days
        if holder_is_admin:
            ttl_days = min(ttl_days, settings.open_api.pat_admin_ttl_days)

        await cls._revoke_active(
            tenant_id=tenant_id,
            user_id=user_id,
            reason=REVOKE_REASON_REGENERATED,
            operator=operator,
            action="open_api.pat.regenerate",
        )
        issued = await CredentialService.issue(
            tenant_id=tenant_id,
            subject_kind=SUBJECT_KIND_NATURAL_PERSON,
            subject_id=user_id,
            request=KeyIssueRequest(
                name=PERSONAL_TOKEN_NAME,
                scopes=[PERSONAL_TOKEN_SCOPE],
                expires_at=datetime.now() + timedelta(days=ttl_days),
            ),
            created_by=operator.user_id,
        )
        await cls._audit(
            operator,
            "open_api.pat.create",
            credential_id=issued.id,
            holder=holder,
            key_mask=issued.key_mask,
        )
        return PersonalTokenIssued(**issued.model_dump(), holder_is_admin=holder_is_admin)

    @classmethod
    async def revoke_self(cls, *, tenant_id: int, user_id: int, operator) -> int:
        return await cls._revoke_active(
            tenant_id=tenant_id,
            user_id=user_id,
            reason=REVOKE_REASON_MANUAL,
            operator=operator,
            action="open_api.pat.delete",
        )

    @classmethod
    async def revoke_by_holder(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        operator,
    ) -> int:
        await cls._active_holder(user_id, tenant_id)
        return await cls._revoke_active(
            tenant_id=tenant_id,
            user_id=user_id,
            reason=REVOKE_REASON_MANUAL,
            operator=operator,
            action="open_api.pat.revoke_holder",
        )

    @classmethod
    async def revoke_by_id(
        cls,
        *,
        tenant_id: int,
        credential_id: int,
        operator,
    ) -> KeyItem:
        row = await CredentialRepository.get(credential_id)
        if (
            row is None
            or row.tenant_id != tenant_id
            or row.subject_kind != SUBJECT_KIND_NATURAL_PERSON
        ):
            from bisheng.common.errcode.open_api import ApiCredentialNotFoundError

            raise ApiCredentialNotFoundError()
        item = await CredentialService.revoke(
            SUBJECT_KIND_NATURAL_PERSON,
            row.subject_id,
            credential_id,
            reason=REVOKE_REASON_MANUAL,
        )
        await cls._audit(
            operator,
            "open_api.pat.revoke",
            credential_id=row.id,
            holder=await cls._holder_record(row.subject_id),
            key_mask=row.key_mask,
        )
        return item

    @classmethod
    async def list_page(cls, *, tenant_id: int, page: int, page_size: int) -> PersonalTokenLedgerPage:
        rows, total = await CredentialRepository.list_natural_person_page(
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
        )
        items = [await cls._ledger_item(row) for row in rows]
        return PersonalTokenLedgerPage(data=items, total=total)

    @classmethod
    async def cascade_revoke(cls, *, tenant_id: int, user_id: int, reason: str) -> int:
        rows = await CredentialRepository.revoke_natural_person(
            tenant_id=tenant_id,
            user_id=user_id,
            reason=reason,
        )
        await CredentialService.invalidate_cache(row.token_hash for row in rows)
        return len(rows)

    @classmethod
    async def _revoke_active(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        reason: str,
        operator,
        action: str,
    ) -> int:
        rows = await CredentialRepository.revoke_natural_person(
            tenant_id=tenant_id,
            user_id=user_id,
            reason=reason,
        )
        await CredentialService.invalidate_cache(row.token_hash for row in rows)
        for row in rows:
            await cls._audit(
                operator,
                action,
                credential_id=row.id,
                holder=await cls._holder_record(user_id),
                key_mask=row.key_mask,
            )
        return len(rows)

    @staticmethod
    async def _active_holder(user_id: int, tenant_id: int) -> NaturalPersonRecord:
        holder = await OwnerRepository.get_active_natural_person(user_id)
        if holder is None or holder.tenant_id != tenant_id:
            raise PersonalTokenHolderInvalidError()
        return holder

    @staticmethod
    async def _holder_record(user_id: int) -> NaturalPersonRecord:
        holder = await OwnerRepository.get_active_natural_person(user_id)
        if holder is not None:
            return holder
        return NaturalPersonRecord(user_id=user_id, user_name="", tenant_id=0)

    @staticmethod
    async def _is_admin(user_id: int, tenant_id: int) -> bool:
        from bisheng.permission.application.relation_api import is_tenant_admin
        from bisheng.utils.http_middleware import _check_is_global_super

        return await _check_is_global_super(user_id) or await is_tenant_admin(user_id, tenant_id)

    @classmethod
    async def _current_item(cls, *, tenant_id: int, user_id: int) -> KeyItem | None:
        rows = await CredentialRepository.list_by_subject(
            SUBJECT_KIND_NATURAL_PERSON,
            user_id,
            include_revoked=False,
        )
        row = next((item for item in rows if item.tenant_id == tenant_id), None)
        return KeyItem.from_row(row) if row is not None else None

    @classmethod
    async def _ledger_item(cls, row: ApiCredential) -> PersonalTokenLedgerItem:
        holder = await cls._holder_record(row.subject_id)
        return PersonalTokenLedgerItem(
            id=row.id,
            holder_user_id=row.subject_id,
            holder_name=holder.user_name,
            key_mask=row.key_mask,
            scopes=list(row.scopes or []),
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
            revoke_reason=row.revoke_reason,
            is_valid=row.is_valid_at(datetime.now()),
            holder_is_admin=await cls._is_admin(row.subject_id, row.tenant_id),
            create_time=row.create_time,
        )

    @staticmethod
    async def _audit(
        operator,
        action: str,
        *,
        credential_id: int,
        holder: NaturalPersonRecord,
        key_mask: str,
    ) -> None:
        tenant_id = get_current_tenant_id() or operator.tenant_id
        await AuditLogDao.ainsert_v2(
            tenant_id=tenant_id,
            operator_id=operator.user_id,
            operator_tenant_id=tenant_id,
            action=action,
            target_type="api_credential",
            target_id=str(credential_id),
            object_name=holder.user_name,
            metadata={
                "credential_id": credential_id,
                "subject_kind": SUBJECT_KIND_NATURAL_PERSON,
                "subject_id": holder.user_id,
                "key_mask": key_mask,
            },
        )

