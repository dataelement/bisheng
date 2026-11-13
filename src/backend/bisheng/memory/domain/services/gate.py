"""MemoryGate: eligibility registration at login-state endpoints and per-turn enablement.

Design decision 6: only logged-in natural-person sessions are eligible. Login
endpoints call ``open``; everything downstream (services, nodes, callbacks,
workers) calls ``resolve`` by ``chat_id`` and gets ``None`` when there is no
registration. Design decision 17: enablement = registered and eligible, user not
disabled, "my memory" on, and the app switch on.
"""

from __future__ import annotations

import uuid

from loguru import logger
from sqlmodel import select

from bisheng.memory.domain.config import aget_memory_config, get_memory_config
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.models.memory_user_setting import MemoryUserSetting
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.repositories.cursor_repository import CursorRepository


def _new_turn_id() -> str:
    return uuid.uuid4().hex


class MemoryGate:
    # ---- registration (login-state endpoints only) -----------------------------------
    @classmethod
    async def open(cls, chat_id: str | None, login_user, timezone: str | None = None) -> None:
        if not chat_id or login_user is None:
            return
        from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
        from bisheng.database.models.session import MessageSession

        tenant_id = get_current_tenant_id() or getattr(login_user, "tenant_id", None) or DEFAULT_TENANT_ID
        user_id = int(login_user.user_id)
        async with _db.async_session() as s:
            session_row = await s.get(MessageSession, chat_id)
            setting = (
                await s.exec(
                    select(MemoryUserSetting).where(
                        MemoryUserSetting.tenant_id == tenant_id, MemoryUserSetting.user_id == user_id
                    )
                )
            ).first()
        if session_row is not None and int(session_row.user_id) != user_id:
            logger.warning("memory: refuse to register chat {} for non-owner user {}", chat_id, user_id)
            return
        tz = timezone or (setting.timezone if setting else None)

        existing = await CursorRepository.get(chat_id)
        if existing is None:
            watermark = await CursorRepository.max_message_id(chat_id)
            created = await CursorRepository.create(
                MemorySessionCursor(
                    chat_id=chat_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    eligible=True,
                    timezone=tz,
                    last_message_id=watermark,
                    watermark_message_id=watermark,
                )
            )
            if created:
                return
            existing = await CursorRepository.get(chat_id)
            if existing is None:
                return
        if existing.tenant_id != tenant_id or existing.user_id != user_id:
            if existing.eligible:
                await CursorRepository.mark_ineligible(chat_id)
            return
        if tz and existing.timezone != tz:
            await CursorRepository.set_timezone(chat_id, tenant_id, user_id, tz)

    # ---- enablement -----------------------------------------------------------------------
    @staticmethod
    def _build(row, user, setting, scene, app_enabled, default_tz, app_id, app_name) -> MemoryContext | None:
        if row is None or not row.eligible:
            return None
        if user is None or int(getattr(user, "delete", 0) or 0) == 1:
            return None
        if setting is not None and not setting.enabled:
            return None
        if not app_enabled:
            return None
        timezone = row.timezone or (setting.timezone if setting else None) or default_tz
        return MemoryContext(
            tenant_id=int(row.tenant_id),
            user_id=int(row.user_id),
            timezone=timezone,
            chat_id=row.chat_id,
            turn_id=_new_turn_id(),
            scene=scene,
            app_id=app_id,
            app_name=app_name,
        )

    @classmethod
    async def resolve(
        cls,
        chat_id: str | None,
        scene: str,
        app_enabled: bool = True,
        app_id: str | None = None,
        app_name: str | None = None,
        actor_user_id: int | None = None,
    ) -> MemoryContext | None:
        """Context of the registration owner, or None.

        ``actor_user_id`` is the user acting in this turn when known (request
        handlers, workers). A registration that belongs to someone else is
        never resolved for them, even if they know the chat_id. The row is read
        by primary key without the tenant auto-filter: its own tenant and user
        are the identity (decision 6), not the current ContextVar.
        """
        if not chat_id:
            return None
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.user.domain.models.user import User

        with bypass_tenant_filter():
            async with _db.async_session() as s:
                row = await s.get(MemorySessionCursor, chat_id)
                if row is None or not row.eligible:
                    return None
                if actor_user_id is not None and int(actor_user_id) != int(row.user_id):
                    return None
                user = await s.get(User, row.user_id)
                setting = (
                    await s.exec(
                        select(MemoryUserSetting).where(
                            MemoryUserSetting.tenant_id == row.tenant_id, MemoryUserSetting.user_id == row.user_id
                        )
                    )
                ).first()
        config = await aget_memory_config()
        return cls._build(row, user, setting, scene, app_enabled, config.default_timezone, app_id, app_name)

    @classmethod
    def resolve_sync(
        cls,
        chat_id: str | None,
        scene: str,
        app_enabled: bool = True,
        app_id: str | None = None,
        app_name: str | None = None,
        actor_user_id: int | None = None,
    ) -> MemoryContext | None:
        """Context of the registration owner, or None.

        ``actor_user_id`` is the user acting in this turn when known (request
        handlers, workers). A registration that belongs to someone else is
        never resolved for them, even if they know the chat_id. The row is read
        by primary key without the tenant auto-filter: its own tenant and user
        are the identity (decision 6), not the current ContextVar.
        """
        if not chat_id:
            return None
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.user.domain.models.user import User

        with bypass_tenant_filter():
            with _db.sync_session() as s:
                row = s.get(MemorySessionCursor, chat_id)
                if row is None or not row.eligible:
                    return None
                if actor_user_id is not None and int(actor_user_id) != int(row.user_id):
                    return None
                user = s.get(User, row.user_id)
                setting = s.exec(
                    select(MemoryUserSetting).where(
                        MemoryUserSetting.tenant_id == row.tenant_id, MemoryUserSetting.user_id == row.user_id
                    )
                ).first()
        config = get_memory_config()
        return cls._build(row, user, setting, scene, app_enabled, config.default_timezone, app_id, app_name)
