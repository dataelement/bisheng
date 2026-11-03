"""Database operations for Open API credentials."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, update
from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.models.credential_delegate_scope import ApiCredentialDelegateScope


class CredentialRepository:
    @classmethod
    async def create(cls, row: ApiCredential) -> ApiCredential:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def create_with_delegate_entries(
        cls,
        row: ApiCredential,
        entries: tuple[tuple[str, int], ...],
    ) -> ApiCredential:
        async with get_async_db_session() as session:
            async with session.begin():
                session.add(row)
                await session.flush()
                for subject_type, subject_id in entries:
                    session.add(
                        ApiCredentialDelegateScope(
                            tenant_id=row.tenant_id,
                            credential_id=row.id,
                            subject_type=subject_type,
                            subject_id=subject_id,
                        )
                    )
            await session.refresh(row)
        return row

    @classmethod
    async def create_in_transaction(cls, session, row, entries=(), *, audit_operator=None):
        """Flush into the caller transaction; no cache writes or independent session."""
        from bisheng.database.models.audit_log import AuditLog

        session.add(row)
        await session.flush()
        for subject_type, subject_id in entries:
            session.add(
                ApiCredentialDelegateScope(
                    tenant_id=row.tenant_id, credential_id=row.id, subject_type=subject_type, subject_id=subject_id
                )
            )
        if audit_operator is not None:
            session.add(
                AuditLog(
                    tenant_id=row.tenant_id,
                    operator_id=audit_operator.user_id,
                    operator_name=getattr(audit_operator, "user_name", None)
                    or ("system" if audit_operator.user_id == 0 else None),
                    operator_tenant_id=audit_operator.tenant_id,
                    action="open_api.api_key.issue",
                    target_type="api_credential",
                    target_id=str(row.id),
                    object_name=row.name,
                    audit_metadata={
                        "credential_id": row.id,
                        "subject_kind": row.subject_kind,
                        "subject_id": row.subject_id,
                        "scopes": list(row.scopes or []),
                        "key_mask": row.key_mask,
                        **await cls.trusted_app_metadata(session, row),
                    },
                )
            )
        await session.flush()
        # MySQL does not return server defaults on INSERT. Load them explicitly
        # before synchronous DTO construction, without committing the caller's UoW.
        await session.refresh(row)
        return row

    @classmethod
    async def trusted_app_metadata(cls, session, row):
        """Resolve the immutable hosted subject, never an owner's other apps."""
        from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
        from bisheng.database.models.app import App

        if row.subject_kind != "hosted_app":
            return {}
        statement = (
            select(App.id)
            .join(HostedAppSubject, HostedAppSubject.app_id == App.id)
            .where(HostedAppSubject.id == row.subject_id, App.tenant_id == row.tenant_id)
        )
        app_id = (await session.exec(statement)).first()
        if app_id is None:
            raise ValueError("credential_app_binding_invalid")
        return {"app_id": app_id}

    @classmethod
    async def audit_app_metadata(cls, row):
        if row.subject_kind != "hosted_app":
            return {}
        async with get_async_db_session() as session:
            return await cls.trusted_app_metadata(session, row)

    @staticmethod
    async def append_runtime_revoke_audit(session, *, row, binding, operation, reason):
        from bisheng.database.models.audit_log import AuditLog

        session.add(
            AuditLog(
                tenant_id=row.tenant_id,
                operator_id=0,
                operator_name="system",
                operator_tenant_id=row.tenant_id,
                action="open_api.api_key.revoke",
                target_type="api_credential",
                target_id=str(row.id),
                object_name=row.name,
                audit_metadata={
                    "app_id": binding.app_id,
                    "credential_id": row.id,
                    "operation_id": operation.id,
                    "reason": reason,
                    "subject_kind": row.subject_kind,
                    "subject_id": row.subject_id,
                    "key_mask": row.key_mask,
                },
            )
        )
        await session.flush()

    @classmethod
    async def revoke_runtime_binding(cls, session, binding, operation, *, reason):
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding, RuntimeOperation

        current = (
            await session.exec(
                select(RuntimeCredentialBinding)
                .where(
                    RuntimeCredentialBinding.id == binding.id,
                    RuntimeCredentialBinding.tenant_id == operation.tenant_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
        if current is None or current.app_id != operation.app_id:
            raise ValueError("credential_app_binding_invalid")
        row = (
            await session.exec(
                select(ApiCredential)
                .where(
                    ApiCredential.id == current.credential_id,
                    ApiCredential.tenant_id == current.tenant_id,
                )
                .with_for_update()
            )
        ).first()
        origin = (
            await session.exec(
                select(RuntimeOperation).where(
                    RuntimeOperation.id == current.operation_id,
                    RuntimeOperation.tenant_id == current.tenant_id,
                    RuntimeOperation.app_id == current.app_id,
                    RuntimeOperation.version_id == current.version_id,
                )
            )
        ).first()
        if (
            row is None
            or origin is None
            or (await cls.trusted_app_metadata(session, row)).get("app_id") != current.app_id
        ):
            raise ValueError("credential_app_binding_invalid")
        if current.state == "revoked":
            return False
        current.state = "revoked"
        session.add(current)
        # Binding state is the authentication fence. Keep the credential's own
        # revoked marker consistent; do not perform a separate cache transaction.
        if row.revoked_at is None:
            row.revoked_at = datetime.now()
            row.revoke_reason = reason
            session.add(row)
        await cls.append_runtime_revoke_audit(session, row=row, binding=current, operation=operation, reason=reason)
        return True

    @classmethod
    async def get(cls, credential_id: int) -> ApiCredential | None:
        async with get_async_db_session() as session:
            return (await session.exec(select(ApiCredential).where(ApiCredential.id == credential_id))).first()

    @classmethod
    async def get_by_ids(cls, credential_ids: list[int]) -> list[ApiCredential]:
        """Batch read for display — the audit page resolves the key mask of
        the credential an ``open_api.call`` / ``app.release.submit`` row names
        in ``metadata.credential_id`` (F056 AC-17). Tenant filter bypassed:
        a global super's audit page spans tenants and the rows themselves were
        already scoped by the audit query. Revoked rows are included on
        purpose — a mask must stay readable after the key is gone.
        """
        if not credential_ids:
            return []
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(ApiCredential).where(col(ApiCredential.id).in_(credential_ids))
                return list((await session.exec(statement)).all())

    @classmethod
    async def get_by_hash(cls, token_hash: str) -> ApiCredential | None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(ApiCredential).where(ApiCredential.token_hash == token_hash))).first()

    @classmethod
    def get_for_execution_sync(cls, credential_id: int) -> ApiCredential | None:
        with bypass_tenant_filter():
            with get_sync_db_session() as session:
                return session.exec(select(ApiCredential).where(ApiCredential.id == credential_id)).first()

    @classmethod
    async def list_by_subject(
        cls,
        subject_kind: str,
        subject_id: int,
        *,
        include_revoked: bool = True,
    ) -> list[ApiCredential]:
        statement = select(ApiCredential).where(
            ApiCredential.subject_kind == subject_kind,
            ApiCredential.subject_id == subject_id,
        )
        if not include_revoked:
            statement = statement.where(col(ApiCredential.revoked_at).is_(None))
        statement = statement.order_by(col(ApiCredential.id).desc())
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def list_by_subject_page(
        cls,
        subject_kind: str,
        subject_id: int,
        *,
        page: int,
        page_size: int,
        now: datetime,
    ) -> tuple[list[ApiCredential], int, int]:
        filters = (
            ApiCredential.subject_kind == subject_kind,
            ApiCredential.subject_id == subject_id,
        )
        statement = (
            select(ApiCredential)
            .where(*filters)
            .order_by(col(ApiCredential.id).desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_statement = select(func.count()).select_from(ApiCredential).where(*filters)
        active_statement = count_statement.where(
            col(ApiCredential.revoked_at).is_(None),
            col(ApiCredential.expires_at).is_(None) | (ApiCredential.expires_at > now),
        )
        async with get_async_db_session() as session:
            rows = list((await session.exec(statement)).all())
            total = int((await session.exec(count_statement)).one())
            active_count = int((await session.exec(active_statement)).one())
        return rows, total, active_count

    @classmethod
    async def list_natural_person_page(
        cls,
        *,
        tenant_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[ApiCredential], int]:
        filters = (
            ApiCredential.tenant_id == tenant_id,
            ApiCredential.subject_kind == "natural_person",
        )
        statement = (
            select(ApiCredential)
            .where(*filters)
            .order_by(col(ApiCredential.id).desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_statement = select(func.count()).select_from(ApiCredential).where(*filters)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = list((await session.exec(statement)).all())
                total = int((await session.exec(count_statement)).one())
        return rows, total

    @classmethod
    async def revoke_natural_person(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        reason: str,
    ) -> list[ApiCredential]:
        now = datetime.now()
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(ApiCredential).where(
                    ApiCredential.tenant_id == tenant_id,
                    ApiCredential.subject_kind == "natural_person",
                    ApiCredential.subject_id == user_id,
                    col(ApiCredential.revoked_at).is_(None),
                )
                rows = list((await session.exec(statement)).all())
                for row in rows:
                    row.revoked_at = now
                    row.revoke_reason = reason
                    row.update_time = now
                    session.add(row)
                await session.commit()
        return rows

    @classmethod
    async def migrate_natural_person_tenant(
        cls,
        *,
        user_id: int,
        tenant_id: int,
    ) -> list[tuple[ApiCredential, int]]:
        """Move active PAT metadata and dependent scope rows to the holder's tenant."""

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                async with session.begin():
                    statement = (
                        select(ApiCredential)
                        .where(
                            ApiCredential.subject_kind == "natural_person",
                            ApiCredential.subject_id == user_id,
                            ApiCredential.tenant_id != tenant_id,
                            col(ApiCredential.revoked_at).is_(None),
                        )
                        .with_for_update()
                    )
                    rows = list((await session.exec(statement)).all())
                    migrated: list[tuple[ApiCredential, int]] = []
                    now = datetime.now()
                    for row in rows:
                        old_tenant_id = int(row.tenant_id)
                        row.tenant_id = tenant_id
                        row.update_time = now
                        session.add(row)
                        await session.exec(
                            update(ApiCredentialDelegateScope)
                            .where(ApiCredentialDelegateScope.credential_id == row.id)
                            .values(tenant_id=tenant_id)
                        )
                        migrated.append((row, old_tenant_id))
                return migrated

    @classmethod
    async def save(cls, row: ApiCredential) -> ApiCredential:
        row.update_time = datetime.now()
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def save_with_delegate_entries(
        cls,
        row: ApiCredential,
        entries: tuple[tuple[str, int], ...],
    ) -> ApiCredential:
        row.update_time = datetime.now()
        async with get_async_db_session() as session:
            async with session.begin():
                session.add(row)
                await session.exec(
                    delete(ApiCredentialDelegateScope).where(ApiCredentialDelegateScope.credential_id == row.id)
                )
                for subject_type, subject_id in entries:
                    session.add(
                        ApiCredentialDelegateScope(
                            tenant_id=row.tenant_id,
                            credential_id=row.id,
                            subject_type=subject_type,
                            subject_id=subject_id,
                        )
                    )
            await session.refresh(row)
        return row

    @classmethod
    async def revoke_subject(cls, subject_kind: str, subject_id: int, *, reason: str) -> list[ApiCredential]:
        now = datetime.now()
        async with get_async_db_session() as session:
            statement = select(ApiCredential).where(
                ApiCredential.subject_kind == subject_kind,
                ApiCredential.subject_id == subject_id,
                col(ApiCredential.revoked_at).is_(None),
            )
            rows = list((await session.exec(statement)).all())
            for row in rows:
                row.revoked_at = now
                row.revoke_reason = reason
                row.update_time = now
                session.add(row)
            await session.commit()
        return rows

    @classmethod
    async def touch_last_used(cls, credential_id: int, *, used_at: datetime) -> bool:
        # Called from bearer validation, before the request's tenant context is
        # bound; the primary key already pins the row, so skip the tenant filter.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                row = (await session.exec(select(ApiCredential).where(ApiCredential.id == credential_id))).first()
                if row is None:
                    return False
                row.last_used_at = used_at
                row.update_time = used_at
                session.add(row)
                await session.commit()
        return True
