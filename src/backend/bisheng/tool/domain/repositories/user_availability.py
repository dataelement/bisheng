"""Durable per-account availability, scoped by the authenticated tenant."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.models.config import Config
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session, get_sync_db_session


class UserToolAvailabilityRepository:
    @staticmethod
    def prefix(user_id: int) -> str:
        tenant_id = get_current_tenant_id()
        if type(tenant_id) is not int or tenant_id < 1 or user_id < 1 or is_tenant_filter_bypassed():
            raise PermissionError("Authenticated tenant and user are required")
        return f"user-tool-availability:{tenant_id}:{user_id}:"

    async def disabled_ids(self, user_id: int) -> set[int]:
        prefix = self.prefix(user_id)
        async with get_async_db_session() as session:
            rows = await session.exec(select(Config.key).where(Config.key.startswith(prefix), Config.value == "false"))
            return {int(key[len(prefix) :]) for key in rows if key[len(prefix) :].isdecimal()}

    def enabled_sync(self, user_id: int, tool_id: int) -> bool:
        key = f"{self.prefix(user_id)}{tool_id}"
        with get_sync_db_session() as session:
            value = session.exec(select(Config.value).where(Config.key == key)).first()
            return value != "false"

    async def save(self, user_id: int, tool_id: int, enabled: bool):
        key = f"{self.prefix(user_id)}{tool_id}"
        async with get_async_db_session() as session:
            for attempt in range(2):
                row = (await session.exec(select(Config).where(Config.key == key).with_for_update())).first()
                if row is None:
                    row = Config(key=key, value="true")
                row.value = "true" if enabled else "false"
                session.add(row)
                try:
                    await session.commit()
                    return
                except IntegrityError:
                    await session.rollback()
                    if attempt:
                        raise
