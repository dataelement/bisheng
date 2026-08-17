"""Service-account lifecycle: create / edit / enable / disable / delete / list (F049 design D1).

What makes this different from "create a user":

* **One transaction, three rows** — ``user`` (the principal), ``service_account``
  (its companion attributes) and an *active* ``user_tenant`` row. Nothing here
  reuses ``UserDao.create_user`` / ``user_register`` / ``add_user_and_default_role``
  (pit 6: those funnel the new row into the guest department, which would put
  the account back into people-facing member searches and violate AC-22), and
  ``aadd_user_to_tenant`` is not used either (pit 8: it leaves ``is_active``
  unset, which makes F048 subject validation and credential validation fail).
* ``external_id`` stays **NULL** and ``source='service_account'`` (pit 5): three
  login-candidate lookups match on ``external_id`` only, so the account is
  structurally invisible to them — the 26012 guard is the second line, not the
  first.
* **State lives in two timestamps** (``disabled_at`` / ``deleted_at``).
  ``user.delete`` is a same-transaction write-through projection so that the
  ordinary ``delete == 0`` people filters hide the account; readers here never
  consult it (design D1 "读侧口径统一").
* **The tenant comes from the acting admin's scope**, never from the request
  body (AC-23) — with F019 admin-scope active, ``get_current_tenant_id()`` is
  the management view a super admin switched into (pit 23).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from bisheng.common.errcode.open_api import (
    ServiceAccountNotFoundError,
    ServiceAccountOwnerInvalidError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import UserTenantDao
from bisheng.open_api.domain.models.api_credential import (
    REVOKE_REASON_SUBJECT_DELETED,
    REVOKE_REASON_SUBJECT_DISABLED,
    SUBJECT_KIND_SERVICE_ACCOUNT,
)
from bisheng.open_api.domain.models.service_account import (
    SERVICE_ACCOUNT_PASSWORD_SENTINEL,
    SERVICE_ACCOUNT_USER_SOURCE,
    ServiceAccount,
    ServiceAccountDao,
)
from bisheng.open_api.domain.schemas.service_account import (
    ServiceAccountCreate,
    ServiceAccountDetail,
    ServiceAccountItem,
    ServiceAccountOwner,
    ServiceAccountPage,
    ServiceAccountUpdate,
)
from bisheng.open_api.domain.services.credential_service import CredentialService
from bisheng.user.domain.models.user import USER_TYPE_HUMAN, USER_TYPE_SERVICE, User, UserDao

if TYPE_CHECKING:  # pragma: no cover - typing only
    from bisheng.common.dependencies.user_deps import UserPayload

AUDIT_TARGET_TYPE = "service_account"
AUDIT_ACTION_CREATE = "open_api.service_account.create"
AUDIT_ACTION_UPDATE = "open_api.service_account.update"
AUDIT_ACTION_ENABLE = "open_api.service_account.enable"
AUDIT_ACTION_DISABLE = "open_api.service_account.disable"
AUDIT_ACTION_DELETE = "open_api.service_account.delete"


class ServiceAccountService:
    """Management-face operations on service accounts. Never called by ``/api/v2``."""

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @classmethod
    async def get_row(cls, user_id: int, *, include_deleted: bool = False) -> ServiceAccount:
        """One companion row, or 26020. Tenant scoping comes from the auto filter (AC-07)."""
        async with get_async_db_session() as session:
            row = await ServiceAccountDao.aget(session, user_id, include_deleted=include_deleted)
        if row is None:
            raise ServiceAccountNotFoundError()
        return row

    @classmethod
    async def get_detail(cls, user_id: int) -> ServiceAccountDetail:
        row = await cls.get_row(user_id)
        items = await cls._hydrate([row])
        item = items[0]
        return ServiceAccountDetail(**item.model_dump(), tenant_id=row.tenant_id)

    @classmethod
    async def list_page(
        cls,
        operator: UserPayload,
        *,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ServiceAccountPage:
        """One page of accounts with every AC-42 column already resolved."""
        user_ids: list[int] | None = None
        if keyword:
            user_ids = await cls._search_principal_ids(keyword)
        async with get_async_db_session() as session:
            rows, total = await ServiceAccountDao.alist_page(session, page=page, page_size=page_size, user_ids=user_ids)
        return ServiceAccountPage(
            data=await cls._hydrate(rows),
            total=total,
            idle_days=settings.open_api.service_account_idle_days,
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, operator: UserPayload, data: ServiceAccountCreate) -> ServiceAccount:
        """D1 create unit — principal + companion + active tenant row in one commit (AC-19)."""
        tenant_id = cls._acting_tenant_id(operator)
        await cls._assert_owner(data.resource_owner_user_id, tenant_id)

        principal = User(
            user_name=data.name,
            # NOT NULL column; the value is a sentinel that no password check can
            # ever produce, and no login path reaches a service account anyway.
            password=SERVICE_ACCOUNT_PASSWORD_SENTINEL,
            user_type=USER_TYPE_SERVICE,
            source=SERVICE_ACCOUNT_USER_SOURCE,
            external_id=None,
            delete=0,
        )
        async with get_async_db_session() as session:
            account = await ServiceAccountDao.acreate_with_user(
                session,
                user=principal,
                tenant_id=tenant_id,
                resource_owner_user_id=data.resource_owner_user_id,
                description=data.description,
                created_by=operator.user_id,
            )
            await session.commit()
            await session.refresh(account)

        await cls._audit(
            operator,
            AUDIT_ACTION_CREATE,
            account,
            name=data.name,
            extra={"description": data.description},
        )
        return account

    @classmethod
    async def update(cls, operator: UserPayload, user_id: int, data: ServiceAccountUpdate) -> ServiceAccount:
        """Edit name / description / resource owner. Owner changes are **not** retroactive (AC-27)."""
        row = await cls.get_row(user_id)
        if data.resource_owner_user_id is not None:
            await cls._assert_owner(data.resource_owner_user_id, row.tenant_id)

        before = {
            "name": await cls._principal_name(user_id),
            "description": row.description,
            "resource_owner_user_id": row.resource_owner_user_id,
        }
        async with get_async_db_session() as session:
            managed = await ServiceAccountDao.aget(session, user_id)
            if managed is None:
                raise ServiceAccountNotFoundError()
            if data.description is not None:
                managed.description = data.description
            if data.resource_owner_user_id is not None:
                # Only this column moves: resources already created keep their
                # creator relation, which is exactly what "not retroactive" means.
                managed.resource_owner_user_id = data.resource_owner_user_id
            await ServiceAccountDao.aupdate_row(session, managed)
            if data.name is not None:
                await cls._set_principal(session, user_id, user_name=data.name)
            await session.commit()
            await session.refresh(managed)
            row = managed

        after = {
            "name": await cls._principal_name(user_id),
            "description": row.description,
            "resource_owner_user_id": row.resource_owner_user_id,
        }
        await cls._audit(operator, AUDIT_ACTION_UPDATE, row, extra={"before": before, "after": after})
        return row

    @classmethod
    async def disable(cls, operator: UserPayload, user_id: int) -> ServiceAccount:
        """Stop the account without losing anything: keys, grants and config stay (AC-21 / AC-47)."""
        await cls.get_row(user_id)
        row = await cls._set_lifecycle(user_id, disabled_at=datetime.now(), user_delete=1)
        await CredentialService.invalidate_subject_cache(
            operator,
            SUBJECT_KIND_SERVICE_ACCOUNT,
            str(user_id),
            reason=REVOKE_REASON_SUBJECT_DISABLED,
        )
        await cls._audit(operator, AUDIT_ACTION_DISABLE, row)
        return row

    @classmethod
    async def enable(cls, operator: UserPayload, user_id: int) -> ServiceAccount:
        """Restore a disabled account exactly as it was (AC-47)."""
        await cls.get_row(user_id)
        row = await cls._set_lifecycle(user_id, disabled_at=None, user_delete=0)
        await cls._audit(operator, AUDIT_ACTION_ENABLE, row)
        return row

    @classmethod
    async def delete(cls, operator: UserPayload, user_id: int) -> ServiceAccount:
        """Wave 1 delete shape: revoke every key, book ``deleted_at``, hide the principal (AC-48).

        T065 inserts the grant reverse-lookup + REMOVE step ahead of this body;
        the row itself is never physically deleted (audit + FK RESTRICT).
        """
        await cls.get_row(user_id)
        await CredentialService.revoke_by_subject(
            operator,
            SUBJECT_KIND_SERVICE_ACCOUNT,
            str(user_id),
            reason=REVOKE_REASON_SUBJECT_DELETED,
        )
        row = await cls._set_lifecycle(user_id, deleted_at=datetime.now(), user_delete=1)
        await cls._audit(operator, AUDIT_ACTION_DELETE, row)
        return row

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def _acting_tenant_id(cls, operator: UserPayload) -> int:
        return get_current_tenant_id() or operator.tenant_id or DEFAULT_TENANT_ID

    @classmethod
    async def _assert_owner(cls, owner_user_id: int, tenant_id: int) -> User:
        """The resource owner must be an enabled natural person of this tenant (26021, AC-23)."""
        owner = await UserDao.aget_user(owner_user_id)
        if owner is None or owner.delete != 0 or owner.user_type != USER_TYPE_HUMAN:
            raise ServiceAccountOwnerInvalidError()
        active = await UserTenantDao.aget_active_user_tenant(owner_user_id)
        if active is None or int(active.tenant_id) != int(tenant_id) or active.status != "active":
            raise ServiceAccountOwnerInvalidError()
        return owner

    @classmethod
    async def _set_lifecycle(
        cls,
        user_id: int,
        *,
        disabled_at: datetime | None | object = ...,
        deleted_at: datetime | None | object = ...,
        user_delete: int,
    ) -> ServiceAccount:
        """Write the companion timestamps and the ``user.delete`` projection in one transaction."""
        async with get_async_db_session() as session:
            row = await ServiceAccountDao.aget(session, user_id, include_deleted=True)
            if row is None:
                raise ServiceAccountNotFoundError()
            await ServiceAccountDao.aset_timestamps(session, row, disabled_at=disabled_at, deleted_at=deleted_at)
            await cls._set_principal(session, user_id, delete=user_delete)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def _set_principal(cls, session, user_id: int, **fields: Any) -> None:
        """Patch the principal ``user`` row inside the caller's transaction."""
        principal = (await session.exec(select(User).where(User.user_id == user_id))).first()
        if principal is None:
            raise ServiceAccountNotFoundError()
        for key, value in fields.items():
            setattr(principal, key, value)
        principal.update_time = datetime.now()
        session.add(principal)
        await session.flush()

    @classmethod
    async def _principal_name(cls, user_id: int) -> str | None:
        principal = await UserDao.aget_user(user_id)
        return principal.user_name if principal else None

    @classmethod
    async def _search_principal_ids(cls, keyword: str) -> list[int]:
        """Name search resolves on the ``user`` table; the companion table has no name column."""
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(User.user_id).where(
                        User.user_type == USER_TYPE_SERVICE,
                        col(User.user_name).like(f"%{keyword}%"),
                    )
                )
            ).all()
        return [int(value) for value in rows]

    @classmethod
    async def _hydrate(cls, rows: list[ServiceAccount]) -> list[ServiceAccountItem]:
        """Resolve names, key counts, owner state and the idle flag for a page of rows."""
        if not rows:
            return []
        now = datetime.now()
        idle_days = settings.open_api.service_account_idle_days
        idle_before = now - timedelta(days=idle_days)

        wanted: set[int] = set()
        for row in rows:
            wanted.add(int(row.user_id))
            wanted.add(int(row.resource_owner_user_id))
            if row.created_by:
                wanted.add(int(row.created_by))
        # Deliberately ``aget_user_by_ids``: name hydration must keep resolving
        # service accounts and disabled users (AC-16 "可显示、不可选").
        users = {int(user.user_id): user for user in (await UserDao.aget_user_by_ids(list(wanted)) or [])}

        items: list[ServiceAccountItem] = []
        for row in rows:
            # One credential lookup per row: a page is at most page_size rows and
            # this list is an admin surface, not a hot path.
            keys = await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, str(row.user_id), now=now)
            last_used = [key.last_used_at for key in keys if key.last_used_at is not None]
            last_used_at = max(last_used) if last_used else None
            owner = users.get(int(row.resource_owner_user_id))
            owner_disabled = owner is None or owner.delete != 0
            principal = users.get(int(row.user_id))
            creator = users.get(int(row.created_by)) if row.created_by else None
            items.append(
                ServiceAccountItem(
                    id=int(row.user_id),
                    name=principal.user_name if principal else str(row.user_id),
                    description=row.description,
                    status=cls._status(row),
                    disabled_at=row.disabled_at,
                    deleted_at=row.deleted_at,
                    active_key_count=sum(1 for key in keys if key.is_valid),
                    resource_owner=ServiceAccountOwner(
                        user_id=int(row.resource_owner_user_id),
                        user_name=owner.user_name if owner else None,
                        disabled=owner_disabled,
                    ),
                    owner_disabled=owner_disabled,
                    last_used_at=last_used_at,
                    idle=last_used_at is None or last_used_at < idle_before,
                    created_by=row.created_by,
                    creator_name=creator.user_name if creator else None,
                    create_time=row.create_time,
                    update_time=row.update_time,
                )
            )
        return items

    @staticmethod
    def _status(row: ServiceAccount) -> str:
        """The only state source is the pair of timestamps (design D1)."""
        if row.deleted_at is not None:
            return "deleted"
        if row.disabled_at is not None:
            return "disabled"
        return "enabled"

    @classmethod
    async def _audit(
        cls,
        operator: UserPayload,
        action: str,
        row: ServiceAccount,
        *,
        name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        metadata: dict[str, Any] = {
            "service_account_id": int(row.user_id),
            "resource_owner_user_id": int(row.resource_owner_user_id),
            "status": cls._status(row),
        }
        if extra:
            metadata.update(extra)
        await AuditLogDao.ainsert_v2(
            tenant_id=row.tenant_id,
            operator_id=operator.user_id,
            operator_tenant_id=cls._acting_tenant_id(operator),
            action=action,
            target_type=AUDIT_TARGET_TYPE,
            target_id=str(row.user_id),
            metadata=metadata,
            object_name=name or await cls._principal_name(int(row.user_id)),
        )
