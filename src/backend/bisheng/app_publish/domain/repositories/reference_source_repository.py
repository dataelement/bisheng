"""APP source facts in one caller-owned transaction; no ORM read side effects."""

from copy import deepcopy

from sqlalchemy import func, select, update

from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession
from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding, RuntimeOperation, RuntimeRoute
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.open_api.domain.models.api_credential import ApiCredential


class HostedAppReferenceSourceRepository:
    @staticmethod
    def _context(session, root=None):
        tenant_id = get_current_tenant_id()
        if (
            is_tenant_filter_bypassed()
            or type(tenant_id) is not int
            or tenant_id <= 0
            or not session.in_transaction()
            or (root is not None and root["tenant_id"] != tenant_id)
        ):
            raise ResourceReferenceInvalidError(reason="app_source_transaction_scope")
        return tenant_id

    @classmethod
    async def _rows(cls, session, model, predicates, *, for_update=False, columns=None, order_by=()):
        cls._context(session)
        columns = columns or tuple(model.__table__.columns.keys())
        query = select(*(getattr(model, name) for name in columns)).where(*predicates)
        if order_by:
            query = query.order_by(*order_by)
        if for_update:
            query = query.with_for_update()
        with session.no_autoflush, strict_tenant_filter():
            rows = (await session.execute(query)).mappings().all()
        return tuple(deepcopy(dict(row)) for row in rows)

    @classmethod
    async def aget_root(cls, session, app_id, *, for_update=False, include_deleted=False):
        rows = await cls._rows(session, App, (App.id == app_id,), for_update=for_update)
        if (
            not rows
            or rows[0]["tenant_id"] != cls._context(session)
            or (rows[0]["state"] == "deleted" and not include_deleted)
        ):
            raise AppNotFoundError()
        return rows[0]

    @classmethod
    async def aget_version(cls, session, root, version_id, *, for_update=False):
        cls._context(session, root)
        rows = await cls._rows(
            session, AppVersion, (AppVersion.app_id == root["id"], AppVersion.id == version_id), for_update=for_update
        )
        return rows[0] if rows else None

    @classmethod
    async def alist_versions(cls, session, root, *, for_update=False):
        cls._context(session, root)
        return await cls._rows(
            session, AppVersion, (AppVersion.app_id == root["id"],), for_update=for_update, order_by=(AppVersion.id,)
        )

    @classmethod
    async def amax_version_no(cls, session, root):
        cls._context(session, root)
        with session.no_autoflush:
            return int(
                await session.scalar(select(func.max(AppVersion.version_no)).where(AppVersion.app_id == root["id"]))
                or 0
            )

    @classmethod
    async def ainsert_version(cls, session, root, values):
        cls._context(session, root)
        if values.get("app_id") != root["id"] or not values.get("id") or root["state"] == "deleted":
            raise ResourceReferenceInvalidError(reason="app_version_parent")
        row = AppVersion(**deepcopy(values))
        session.add(row)
        await session.flush()
        return await cls.aget_version(session, root, row.id)

    @classmethod
    async def aset_deleted(cls, session, root):
        tenant_id = cls._context(session, root)
        result = await session.execute(
            update(App)
            .where(App.id == root["id"], App.tenant_id == tenant_id, App.state == root["state"])
            .values(state="deleted")
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise KnowledgeOperationPlanConflictError(reason="app_source_changed")

    @classmethod
    async def aget_knowledge_candidates(cls, session, *, ids=(), names=(), for_update=False):
        if not ids and not names:
            return ()
        predicates = []
        if ids:
            predicates.append(Knowledge.id.in_(ids))
        if names:
            predicates.append(Knowledge.name.in_(names))
        from sqlalchemy import or_

        return await cls._rows(
            session,
            Knowledge,
            (or_(*predicates),),
            columns=("id", "tenant_id", "name", "type"),
            for_update=for_update,
            order_by=(Knowledge.id,),
        )

    @classmethod
    async def aget_runtime_identity(cls, session, root, credential_id, *, for_update=False):
        cls._context(session, root)
        credential = await cls._rows(
            session,
            ApiCredential,
            (ApiCredential.id == credential_id,),
            for_update=for_update,
            columns=("id", "tenant_id", "subject_kind", "subject_id", "scopes", "expires_at", "revoked_at"),
        )
        subject = await cls._rows(
            session, HostedAppSubject, (HostedAppSubject.app_id == root["id"],), for_update=for_update
        )
        route = await cls._rows(
            session,
            RuntimeRoute,
            (RuntimeRoute.app_id == root["id"], RuntimeRoute.route_key == f"app:{root['id']}"),
            for_update=for_update,
        )
        binding = await cls._rows(
            session,
            RuntimeCredentialBinding,
            (RuntimeCredentialBinding.app_id == root["id"], RuntimeCredentialBinding.credential_id == credential_id),
            for_update=for_update,
        )
        preview = await cls._rows(
            session,
            AppPreviewSession,
            (AppPreviewSession.app_id == root["id"], AppPreviewSession.credential_id == credential_id),
            for_update=for_update,
        )
        facts = {}
        for label, rows in (
            ("credential", credential),
            ("subject", subject),
            ("route", route),
            ("binding", binding),
            ("preview", preview),
        ):
            if len(rows) > 1:
                raise ResourceReferenceInvalidError(reason="app_identity_ambiguous")
            facts[label] = rows[0] if rows else None
        operation_id = facts["preview"]["operation_id"] if facts["preview"] else None
        operations = (
            await cls._rows(
                session,
                RuntimeOperation,
                (RuntimeOperation.app_id == root["id"], RuntimeOperation.id == operation_id),
                for_update=for_update,
            )
            if operation_id
            else ()
        )
        facts["operation"] = operations[0] if operations else None
        return facts
