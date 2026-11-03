"""Application metadata — one implementation, two callers (AC-06).

The detail page's PATCH and F055's "metadata lands with the deploy, before the
approval verdict" are the *same* operation. Writing it twice would guarantee
drift the first time either side grew a rule (a length cap, a logo whitelist, an
extra audit field), so the pipeline calls this method rather than the ``app``
table.

Three invariants the name of this module does not convey:

* **Metadata is not a capability.** Renaming an app changes no behaviour, so it
  produces **no ``app_version`` row** and does **not** touch ``app.state``. An
  approval gate on a typo fix would be theatre.
* **``slug`` is not metadata.** It is the entry identity ``/apps/{slug}``,
  already printed on links and QR codes; it is deliberately absent from the
  writable field set (AC-08).
* **``logo`` holds an object name, never a presigned URL.** Presigned URLs
  expire; storing one would give every app a logo that works for a day. The
  read side signs it at render time.
"""

from __future__ import annotations

from loguru import logger

from bisheng.app_runtime.domain.constants import AppAuditAction, AppState
from bisheng.common.errcode.app_factory import AppManageForbiddenError, AppNotFoundError
from bisheng.common.permission_identity import check_tenant_admin
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App, AppDao
from bisheng.database.models.audit_log import AuditLogDao

#: The complete writable set. Anything not here is either identity (``slug``),
#: state (``AppStateService``) or a frozen version fact (F055).
EDITABLE_FIELDS = ("name", "description", "logo")


class AppMetaService:
    """Update name / description / icon of a hosted application."""

    @classmethod
    async def update_meta(
        cls,
        *,
        app_id: str,
        name: str | None = None,
        description: str | None = None,
        logo: str | None = None,
        actor=None,
    ) -> App:
        """Apply the metadata patch and audit it. ``None`` means "leave alone".

        ``actor`` is optional because the publish pipeline runs on a service
        account that has already been authorised upstream (it owns the app by
        F055's ownership check). When a human calls through the HTTP surface the
        actor is present and the owner or administrator rule applies.
        """
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, app_id)
            if row is None or row.state == AppState.DELETED.value:
                raise AppNotFoundError(app_id=app_id)
            set_current_tenant_id(int(row.tenant_id or 0))
            if actor is not None:
                await cls._require_editor(row, actor)

            patch = {"name": name, "description": description, "logo": logo}
            changed = {key: value for key, value in patch.items() if value is not None and value != getattr(row, key)}
            if not changed:
                return row
            for key, value in changed.items():
                setattr(row, key, value)
            session.add(row)
            await session.commit()
            await session.refresh(row)

        await AuditLogDao.ainsert_v2(
            tenant_id=int(row.tenant_id or 0),
            operator_id=int(getattr(actor, "user_id", 0) or 0),
            operator_tenant_id=int(getattr(actor, "tenant_id", 0) or row.tenant_id or 0),
            operator_name=getattr(actor, "user_name", None),
            action=AppAuditAction.META_UPDATE.value,
            target_type="app",
            target_id=row.id,
            object_name=row.name,
            metadata={"fields": sorted(changed), "state": row.state},
        )
        logger.info("app_runtime.update_meta app_id={} fields={}", app_id, sorted(changed))
        return row

    @staticmethod
    async def _require_editor(app: App, actor) -> None:
        user_id = int(getattr(actor, "user_id", 0) or 0)
        if user_id == int(app.owner_user_id or 0) or bool(getattr(actor, "is_global_super", False)):
            return
        if await check_tenant_admin(user_id, int(app.tenant_id or 0)):
            return
        raise AppManageForbiddenError(app_id=app.id)
