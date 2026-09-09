"""Lifecycle management for independent service-account subjects."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from bisheng.common.errcode.open_api import ServiceAccountNotFoundError, ServiceAccountOwnerInvalidError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    current_tenant_id,
    get_current_tenant_id,
    visible_tenant_ids,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.open_api.domain.models.api_credential import (
    REVOKE_REASON_SUBJECT_DELETED,
    SUBJECT_KIND_SERVICE_ACCOUNT,
)
from bisheng.open_api.domain.models.service_account import ServiceAccount
from bisheng.open_api.domain.repositories.owner_repository import NaturalPersonRecord, OwnerRepository
from bisheng.open_api.domain.repositories.service_account_repository import ServiceAccountRepository
from bisheng.open_api.domain.schemas.service_account import (
    ServiceAccountCreate,
    ServiceAccountDetail,
    ServiceAccountItem,
    ServiceAccountOwner,
    ServiceAccountPage,
    ServiceAccountUpdate,
)
from bisheng.open_api.domain.services.credential_service import CredentialService

AUDIT_TARGET_TYPE = "service_account"


class ManagementActor(Protocol):
    user_id: int
    tenant_id: int
    is_global_super: bool


class ServiceAccountService:
    @classmethod
    async def get_row(cls, service_account_id: int, *, include_deleted: bool = False) -> ServiceAccount:
        row = await ServiceAccountRepository.get(service_account_id, include_deleted=include_deleted)
        if row is None:
            raise ServiceAccountNotFoundError()
        return row

    @classmethod
    async def create(cls, operator: ManagementActor, data: ServiceAccountCreate) -> ServiceAccount:
        owner = await cls._resolve_owner(data.resource_owner_user_id)
        tenant_id = cls._creation_tenant(operator, owner)
        if owner.tenant_id != tenant_id:
            raise ServiceAccountOwnerInvalidError()
        tenant_token = current_tenant_id.set(tenant_id)
        visible_token = visible_tenant_ids.set(frozenset({tenant_id}))
        try:
            row = await ServiceAccountRepository.create(
                ServiceAccount(
                    tenant_id=tenant_id,
                    name=data.name,
                    description=data.description,
                    resource_owner_user_id=owner.user_id,
                    created_by=operator.user_id,
                )
            )
        finally:
            visible_tenant_ids.reset(visible_token)
            current_tenant_id.reset(tenant_token)
        await cls._audit(operator, "open_api.service_account.create", row)
        return row

    @classmethod
    async def update(
        cls,
        operator: ManagementActor,
        service_account_id: int,
        data: ServiceAccountUpdate,
    ) -> ServiceAccount:
        row = await cls.get_row(service_account_id)
        if data.resource_owner_user_id is not None:
            owner = await cls._resolve_owner(data.resource_owner_user_id)
            if owner.tenant_id != row.tenant_id:
                raise ServiceAccountOwnerInvalidError()
            row.resource_owner_user_id = owner.user_id
        if data.name is not None:
            row.name = data.name
        if "description" in data.model_fields_set:
            row.description = data.description
        row = await ServiceAccountRepository.save(row)
        await cls._audit(operator, "open_api.service_account.update", row)
        return row

    @classmethod
    async def disable(cls, operator: ManagementActor, service_account_id: int) -> ServiceAccount:
        row = await cls.get_row(service_account_id)
        if row.disabled_at is None:
            row.disabled_at = datetime.now()
            row = await ServiceAccountRepository.save(row)
        await CredentialService.invalidate_subject_cache(SUBJECT_KIND_SERVICE_ACCOUNT, service_account_id)
        await cls._audit(operator, "open_api.service_account.disable", row)
        return row

    @classmethod
    async def enable(cls, operator: ManagementActor, service_account_id: int) -> ServiceAccount:
        row = await cls.get_row(service_account_id)
        row.disabled_at = None
        row = await ServiceAccountRepository.save(row)
        await CredentialService.invalidate_subject_cache(SUBJECT_KIND_SERVICE_ACCOUNT, service_account_id)
        await cls._audit(operator, "open_api.service_account.enable", row)
        return row

    @classmethod
    async def delete(cls, operator: ManagementActor, service_account_id: int) -> ServiceAccount:
        row = await cls.get_row(service_account_id)
        await CredentialService.revoke_by_subject(
            SUBJECT_KIND_SERVICE_ACCOUNT,
            service_account_id,
            reason=REVOKE_REASON_SUBJECT_DELETED,
        )
        row.deleted_at = datetime.now()
        row = await ServiceAccountRepository.save(row)
        await cls._audit(operator, "open_api.service_account.delete", row)
        return row

    @classmethod
    async def get_detail(cls, service_account_id: int) -> ServiceAccountDetail:
        row = await cls.get_row(service_account_id)
        item = await cls._to_item(row)
        return ServiceAccountDetail(**item.model_dump(), disabled_at=row.disabled_at)

    @classmethod
    async def list_page(
        cls,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> ServiceAccountPage:
        rows, total = await ServiceAccountRepository.list_page(
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return ServiceAccountPage(
            data=[await cls._to_item(row) for row in rows],
            total=total,
            idle_days=settings.open_api.service_account_idle_days,
        )

    @classmethod
    async def _to_item(cls, row: ServiceAccount) -> ServiceAccountItem:
        owner = await OwnerRepository.get_active_natural_person(row.resource_owner_user_id)
        keys = await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, row.id)
        last_used_values = [key.last_used_at for key in keys if key.last_used_at is not None]
        last_used_at = max(last_used_values) if last_used_values else None
        idle_before = datetime.now() - timedelta(days=settings.open_api.service_account_idle_days)
        return ServiceAccountItem(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            status=cls.status(row),
            resource_owner=ServiceAccountOwner(
                user_id=row.resource_owner_user_id,
                user_name=owner.user_name if owner else None,
                disabled=owner is None,
            ),
            active_key_count=sum(key.is_valid for key in keys),
            last_used_at=last_used_at,
            idle=last_used_at is None or last_used_at < idle_before,
            created_by=row.created_by,
            create_time=row.create_time,
            update_time=row.update_time,
        )

    @staticmethod
    def status(row: ServiceAccount) -> str:
        if row.deleted_at is not None:
            return "deleted"
        if row.disabled_at is not None:
            return "disabled"
        return "enabled"

    @staticmethod
    async def _resolve_owner(user_id: int) -> NaturalPersonRecord:
        owner = await OwnerRepository.get_active_natural_person(user_id)
        if owner is None:
            raise ServiceAccountOwnerInvalidError()
        return owner

    @staticmethod
    def _creation_tenant(operator: ManagementActor, owner: NaturalPersonRecord) -> int:
        scoped_tenant = get_current_tenant_id()
        if bool(getattr(operator, "is_global_super", False)) and scoped_tenant is None:
            return owner.tenant_id
        return int(scoped_tenant or operator.tenant_id or DEFAULT_TENANT_ID)

    @classmethod
    async def _audit(cls, operator: ManagementActor, action: str, row: ServiceAccount) -> None:
        await AuditLogDao.ainsert_v2(
            tenant_id=row.tenant_id,
            operator_id=operator.user_id,
            operator_tenant_id=get_current_tenant_id() or operator.tenant_id,
            action=action,
            target_type=AUDIT_TARGET_TYPE,
            target_id=str(row.id),
            metadata={
                "service_account_id": row.id,
                "resource_owner_user_id": row.resource_owner_user_id,
                "status": cls.status(row),
            },
            object_name=row.name,
        )
