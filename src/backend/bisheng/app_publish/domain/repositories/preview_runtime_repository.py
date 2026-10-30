"""Preview rows participate in the runtime caller's transaction; never commit here."""

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select

from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession
from bisheng.common.errcode.app_publish import AppPreviewForbiddenError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion


@dataclass(frozen=True)
class PreviewBinding:
    session_id: str
    tenant_id: int
    app_id: str
    version_id: str
    viewer_user_id: int
    purpose: str
    approval_instance_id: int | None
    approval_task_id: int | None
    credential_id: int | None
    operation_id: str | None
    status: str
    expires_at: datetime
    reclaim_reason: str | None = None


def binding(row):
    return PreviewBinding(
        row.id,
        row.tenant_id,
        row.app_id,
        row.version_id,
        row.approver_user_id,
        row.purpose,
        row.approval_instance_id,
        row.approval_task_id,
        row.credential_id,
        row.operation_id,
        row.status,
        row.expires_at,
        row.reclaim_reason,
    )


class PreviewRuntimeRepository:
    @staticmethod
    async def lock_version(session, tenant_id, app_id, version_id):
        row = (
            await session.exec(
                select(AppVersion).where(AppVersion.id == version_id, AppVersion.app_id == app_id).with_for_update()
            )
        ).first()
        if row is None or row.tenant_id != tenant_id:
            raise AppPreviewForbiddenError(reason="preview_version_mismatch")

    @staticmethod
    async def get(session, session_id):
        return (
            await session.exec(select(AppPreviewSession).where(AppPreviewSession.id == session_id).with_for_update())
        ).first()

    @staticmethod
    async def reuse(session, *, tenant_id, app_id, version_id, viewer_user_id, purpose, task_id):
        rows = (
            await session.exec(
                select(AppPreviewSession)
                .where(
                    AppPreviewSession.app_id == app_id,
                    AppPreviewSession.version_id == version_id,
                    AppPreviewSession.approver_user_id == viewer_user_id,
                    AppPreviewSession.purpose == purpose,
                    AppPreviewSession.status.in_(["starting", "running"]),
                )
                .with_for_update()
            )
        ).all()
        return next(
            (
                row
                for row in rows
                if row.tenant_id == tenant_id and row.approval_task_id == task_id and row.expires_at > datetime.utcnow()
            ),
            None,
        )

    @staticmethod
    async def create(session, values):
        row = AppPreviewSession(**values)
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def by_reference(cls, *, session_id=None, credential_id=None, operation_id=None, session=None):
        async def load(db):
            query = select(AppPreviewSession)
            if session_id:
                query = query.where(AppPreviewSession.id == session_id)
            elif credential_id:
                query = query.where(AppPreviewSession.credential_id == credential_id)
            elif operation_id:
                query = query.where(AppPreviewSession.operation_id == operation_id)
            else:
                return None
            row = (await db.exec(query)).first()
            return binding(row) if row else None

        if session is not None:
            return await load(session)
        async with get_async_db_session() as db:
            return await load(db)

    @staticmethod
    async def read_application(app_id):
        # This exact-ID bootstrap is reauthorized by the current edit or task policy.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(App).where(App.id == app_id))).first()

    @classmethod
    async def bind_identity(cls, session, session_id, *, operation_id, credential_id):
        row = await cls.get(session, session_id)
        if row is None or row.status != "starting" or row.operation_id or row.credential_id:
            raise AppPreviewForbiddenError(reason="preview_already_bound")
        row.operation_id = operation_id
        row.credential_id = credential_id
        session.add(row)
        await session.flush()
        return binding(row)

    @classmethod
    async def activate(cls, session, *, session_id, tenant_id, app_id, version_id, operation_id):
        row = await cls.get(session, session_id)
        if (
            row is None
            or (row.tenant_id, row.app_id, row.version_id, row.operation_id)
            != (tenant_id, app_id, version_id, operation_id)
            or not row.credential_id
            or row.status not in {"starting", "running"}
            or row.expires_at <= datetime.utcnow()
        ):
            raise AppPreviewForbiddenError(reason="preview_binding_invalid")
        row.status = "running"
        session.add(row)
        await session.flush()
        return binding(row)

    @classmethod
    async def closing_identity(cls, session, *, session_id, tenant_id, app_id, version_id, operation_id):
        from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject

        row = await cls.get(session, session_id)
        if row is None:
            return None
        if (row.tenant_id, row.app_id, row.version_id, row.operation_id) != (
            tenant_id,
            app_id,
            version_id,
            operation_id,
        ):
            raise AppPreviewForbiddenError(reason="preview_binding_invalid")
        if row.status == "reclaimed":
            return None
        subject = (await session.exec(select(HostedAppSubject).where(HostedAppSubject.app_id == row.app_id))).first()
        if subject is None or not row.credential_id:
            raise AppPreviewForbiddenError(reason="preview_identity_missing")
        return binding(row), subject.id

    @classmethod
    async def mark_closed(cls, session, session_id, *, reason):
        row = await cls.get(session, session_id)
        row.status = "reclaimed"
        row.reclaim_reason = reason
        row.reclaimed_at = datetime.utcnow()
        session.add(row)
        await session.flush()

    @staticmethod
    async def current(qualification):
        q = qualification
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(AppPreviewSession)
                    .where(
                        AppPreviewSession.app_id == q.app_id,
                        AppPreviewSession.version_id == q.version_id,
                        AppPreviewSession.approver_user_id == q.viewer_user_id,
                        AppPreviewSession.purpose == q.purpose,
                        AppPreviewSession.status.in_(["starting", "running"]),
                    )
                    .order_by(AppPreviewSession.create_time.desc(), AppPreviewSession.id.desc())
                    .limit(20)
                )
            ).all()
        row = next(
            (row for row in rows if row.tenant_id == q.tenant_id and row.approval_task_id == q.approval_task_id), None
        )
        return binding(row) if row else None

    @staticmethod
    async def sweep_candidates(*, version_id=None, expired=False, approval_terminal=False):
        query = select(AppPreviewSession).where(
            AppPreviewSession.status.in_(["starting", "running"]),
            AppPreviewSession.purpose.in_(["management", "approval"]),
        )
        if version_id:
            query = query.where(AppPreviewSession.version_id == version_id)
        if expired:
            query = query.where(AppPreviewSession.expires_at <= datetime.utcnow())
        if approval_terminal:
            query = query.where(AppPreviewSession.purpose == "approval")
        # Only the bounded expiry/terminal sweep discovers resources across tenants.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = (
                    await session.exec(query.order_by(AppPreviewSession.expires_at, AppPreviewSession.id).limit(200))
                ).all()
        return tuple(binding(row) for row in rows)
