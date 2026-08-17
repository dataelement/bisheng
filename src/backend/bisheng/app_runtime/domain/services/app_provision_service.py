"""Creating a hosted application — the row, its identity, its owner grant.

Split out of :mod:`app_state_service` deliberately. That module is the *state
machine* (决议-8: the only writer of ``app.state``), and creation is not a
transition — it is the act that brings the aggregate into existence at
``draft``. Keeping them apart also gives F055's publish pipeline exactly one
symbol to depend on for "first publish creates the app" without importing the
five action methods it must never call directly.

Three rules that are not obvious from the code:

* **``slug`` is a global identity, not a per-tenant name** (AC-08). It is the
  public entry segment ``/apps/{slug}``, resolved by app-proxy *before* any
  tenant context exists, so the uniqueness probe runs under
  ``bypass_tenant_filter()`` and a collision with **any** tenant's app is a
  refusal.
* **A declared slug that collides is refused; a generated one is nudged.** If
  the developer wrote ``slug:`` in ``bisheng-app.yaml``, silently renaming it
  would break the URL they already told their users about — so 16103, "pick
  another one". If the platform generated it from the display name, two people
  naming an app 「工具」 must not deadlock each other, so a suffix is appended.
* **The owner grant is part of creation, not an afterthought.** AC-11 ("visible
  to its owner only by default") is the F048 CUSTOM owner projection; if it
  fails, the row is removed rather than left behind as an app nobody — not even
  its owner — can see or manage.
"""

from __future__ import annotations

import re

from loguru import logger

from bisheng.app_runtime.domain.constants import AppState
from bisheng.common.errcode.app_factory import AppSlugConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App, AppDao
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.utils import generate_uuid

#: Same shape F055's manifest schema validates and app-proxy accepts.
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SLUG_MAX_LENGTH = 64

#: How many ``-2``, ``-3`` … variants to try before falling back to a random
#: suffix. Small on purpose: a long scan means the name is generic, and a
#: random suffix is a better answer than the 47th sequential one.
_SLUG_SUFFIX_ATTEMPTS = 5


class AppProvisionService:
    """Create the ``app`` row of a hosted application, at ``draft``."""

    @classmethod
    async def create_draft(
        cls,
        *,
        name: str,
        slug: str | None = None,
        description: str | None = None,
        owner_user_id: int,
        tenant_id: int,
    ) -> str:
        """Register a new hosted application and return its id.

        The application starts at ``draft``: it exists, it has an owner and an
        entry identity, and nothing is running. Everything after that (version
        records, approval, going online) belongs to F055 and to
        ``AppStateService`` respectively.
        """
        declared = (slug or "").strip().lower() or None
        set_current_tenant_id(tenant_id)
        resolved = await cls._resolve_slug(declared=declared, name=name)

        async with get_async_db_session() as session:
            row = App(
                slug=resolved,
                name=name,
                description=description,
                owner_user_id=owner_user_id,
                # Explicit rather than left to the before_flush hook: the first
                # publish arrives on a service-account credential whose tenant
                # context is the credential's, and the app must land in the
                # resource owner's tenant that the caller resolved (F049 D5).
                tenant_id=tenant_id,
                state=AppState.DRAFT.value,
            )
            await AppDao.acreate(session, row)
            await session.commit()
            app_id = row.id

        try:
            await cls._project_owner(app_id=app_id, owner_user_id=owner_user_id, tenant_id=tenant_id)
        except Exception:
            logger.exception("app_runtime.create_draft owner projection failed app_id={} — rolling back", app_id)
            await cls._remove_orphan(app_id)
            raise
        logger.info(
            "app_runtime.create_draft app_id={} slug={} owner={} tenant={}", app_id, resolved, owner_user_id, tenant_id
        )
        return app_id

    # -- slug -----------------------------------------------------------

    @classmethod
    async def _resolve_slug(cls, *, declared: str | None, name: str) -> str:
        if declared:
            if not _SLUG_PATTERN.match(declared) or len(declared) > _SLUG_MAX_LENGTH:
                raise AppSlugConflictError(msg="应用标识格式不合法, 只允许小写字母 / 数字 / 连字符", slug=declared)
            if await cls._slug_taken(declared):
                raise AppSlugConflictError(msg=f"应用标识 {declared} 已被占用, 请更换", slug=declared)
            return declared

        base = cls.slugify(name)
        if not await cls._slug_taken(base):
            return base
        for suffix in range(2, 2 + _SLUG_SUFFIX_ATTEMPTS):
            candidate = f"{base[: _SLUG_MAX_LENGTH - 4]}-{suffix}"
            if not await cls._slug_taken(candidate):
                return candidate
        return f"{base[: _SLUG_MAX_LENGTH - 9]}-{generate_uuid()[:8]}"

    @staticmethod
    def slugify(name: str) -> str:
        """ASCII-only entry segment derived from a display name.

        Names are commonly Chinese, which leaves nothing usable behind — hence
        the ``app-{random}`` fallback rather than an empty slug or a
        transliteration table nobody would maintain.
        """
        lowered = (name or "").strip().lower()
        parts = [chunk for chunk in re.split(r"[^a-z0-9]+", lowered) if chunk]
        candidate = "-".join(parts)[:_SLUG_MAX_LENGTH].strip("-")
        return candidate or f"app-{generate_uuid()[:8]}"

    @staticmethod
    async def _slug_taken(slug: str) -> bool:
        # bypass, not the current tenant: the constraint is global (AC-08) and
        # a tenant-filtered probe would report "free" for a slug another tenant
        # already owns, turning the refusal into a UNIQUE violation at INSERT.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return await AppDao.aget_by_slug(session, slug) is not None

    # -- owner projection -----------------------------------------------

    @staticmethod
    async def _project_owner(*, app_id: str, owner_user_id: int, tenant_id: int) -> None:
        adapter = await get_f048_resource_adapter("app")
        # Creation path: build a version-0 record without asking for the CURRENT
        # projected version. ``load_permission_record`` would query that version
        # — which this call is about to create — and raise 25008 before it
        # exists, rolling back every first publish (chicken-and-egg).
        record = await adapter.build_creation_record(app_id)
        if record is None:
            raise RuntimeError(f"app {app_id} vanished before its owner grant was written")
        await adapter.authorize_created(
            record=record,
            actor=PermissionActor(user_id=owner_user_id, current_tenant_id=tenant_id),
        )

    @staticmethod
    async def _remove_orphan(app_id: str) -> None:
        try:
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    await AppDao.adelete_row(session, app_id)
                    await session.commit()
        except Exception:  # pragma: no cover - best effort, original error wins
            logger.exception("app_runtime.create_draft could not remove orphan app_id={}", app_id)
