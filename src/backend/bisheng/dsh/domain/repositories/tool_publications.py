"""Atomic tenant-qualified publication records in the existing global Config table."""

from contextlib import asynccontextmanager
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import select

from bisheng.common.errcode.dsh import DshToolServiceUnavailableError
from bisheng.common.models.config import Config
from bisheng.core.database import get_async_db_session
from bisheng.dsh.domain.schemas.tool_publications import ToolCode, ToolPublication


@dataclass
class PublicationRecord:
    publication: ToolPublication | None
    created: bool = False


@asynccontextmanager
async def publication_session():
    try:
        async with get_async_db_session() as session:
            yield session
    except (SQLAlchemyError, ValidationError):
        raise DshToolServiceUnavailableError() from None


def decode_record(row, expected_key):
    publication = ToolPublication.model_validate_json(row.value)
    if row.key != expected_key or not row.key.endswith(":" + publication.tool_code):
        raise DshToolServiceUnavailableError()
    return publication


class ToolPublicationRepository:
    @staticmethod
    def prefix(tenant_id):
        if type(tenant_id) is not int or tenant_id < 1:
            raise ValueError("Invalid tenant")
        return f"dsh_tool_publication:{tenant_id}:"

    @classmethod
    def key(cls, tenant_id, code):
        return cls.prefix(tenant_id) + TypeAdapter(ToolCode).validate_python(code)

    async def list(self, tenant_id, offset=0, limit=50):
        prefix = self.prefix(tenant_id)
        async with publication_session() as session:
            # Escape underscores: SQL LIKE treats them as single-character wildcards.
            condition = Config.key.startswith(prefix, autoescape=True)
            total = (await session.exec(select(func.count()).select_from(Config).where(condition))).one()
            rows = (
                await session.exec(select(Config).where(condition).order_by(Config.key).offset(offset).limit(limit))
            ).all()
            return [decode_record(row, row.key) for row in rows], total

    @asynccontextmanager
    async def locked(self, tenant_id, code, initial=None):
        key = self.key(tenant_id, code)
        async with publication_session() as session:
            statement = select(Config).where(Config.key == key).with_for_update()
            row = (await session.exec(statement)).one_or_none()
            created = False
            if row is None and initial is not None:
                try:
                    async with session.begin_nested():
                        row = Config(key=key, value=initial.model_dump_json())
                        session.add(row)
                        await session.flush()
                        created = True
                except IntegrityError:
                    row = (await session.exec(statement)).one()
            record = PublicationRecord(decode_record(row, key) if row else None, created)
            yield record
            if row is not None and record.publication is not None:
                value = record.publication.model_dump_json()
                if value != row.value:
                    row.value = value
                    session.add(row)
            await session.commit()
