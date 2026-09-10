"""Persist only the DSH instance key in the existing global configuration table."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.models.config import Config
from bisheng.core.database import get_async_db_session

CONFIG_KEY = "dsh_management"


class DshSettingsRepository:
    async def read(self) -> str | None:
        async with get_async_db_session() as session:
            row = (await session.exec(select(Config).where(Config.key == CONFIG_KEY))).one_or_none()
            return row.value if row else None

    async def save(self, value: str) -> None:
        async with get_async_db_session() as session:
            statement = select(Config).where(Config.key == CONFIG_KEY).with_for_update()
            row = (await session.exec(statement)).one_or_none()
            if row is None:
                try:
                    async with session.begin_nested():
                        row = Config(key=CONFIG_KEY, value=value)
                        session.add(row)
                        await session.flush()
                except IntegrityError:
                    row = (await session.exec(statement)).one()
            row.value = value
            session.add(row)
            await session.commit()
