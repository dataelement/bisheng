"""Reads and writes for ``model_call_record`` (F051 writes, F056 reads)."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.open_api.domain.models.model_call_record import ModelCallRecord

_CURSOR_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def encode_cursor(create_time: datetime, row_id: int) -> str:
    payload = json.dumps([create_time.strftime(_CURSOR_FORMAT), row_id])
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, int] | None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        return datetime.strptime(payload[0], _CURSOR_FORMAT), int(payload[1])
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, IndexError):
        return None


class ModelCallRecordRepository:
    """Insert-and-read only; this table is never updated or deleted in place."""

    @classmethod
    async def ainsert_batch(cls, rows: list[ModelCallRecord]) -> None:
        if not rows:
            return
        # Every row already carries an explicit ``tenant_id``: the writer runs in
        # a background task with no request ContextVar, where the ``before_flush``
        # auto-fill writes nothing at all on a multi-tenant deployment.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                session.add_all(rows)
                await session.commit()

    @classmethod
    async def alist(
        cls,
        tenant_id: int | None,
        *,
        credential_id: int | None = None,
        app_id: str | None = None,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[ModelCallRecord], str | None]:
        """One page newest-first, plus the cursor for the next one.

        Ordered by ``(create_time DESC, id DESC)``: ``create_time`` is
        second-precision, so rows written inside the same second are otherwise
        unordered and a page boundary duplicates some rows while losing others.

        ``tenant_id=None`` reads **every** tenant — it is there for the platform
        super administrator's cross-tenant view and nothing else. The automatic
        filter is bypassed here (rows legitimately span tenants for that caller),
        so a tenant administrator's query must pass their tenant explicitly; an
        omitted argument is not a narrower read, it is a wider one.
        """

        statement = select(ModelCallRecord)
        if tenant_id is not None:
            statement = statement.where(ModelCallRecord.tenant_id == tenant_id)
        if credential_id is not None:
            statement = statement.where(ModelCallRecord.credential_id == credential_id)
        if app_id is not None:
            statement = statement.where(ModelCallRecord.app_id == app_id)
        if time_from is not None:
            statement = statement.where(ModelCallRecord.create_time >= time_from)
        if time_to is not None:
            statement = statement.where(ModelCallRecord.create_time <= time_to)
        if cursor:
            decoded = decode_cursor(cursor)
            if decoded is not None:
                cursor_time, cursor_id = decoded
                statement = statement.where(
                    (col(ModelCallRecord.create_time) < cursor_time)
                    | ((col(ModelCallRecord.create_time) == cursor_time) & (col(ModelCallRecord.id) < cursor_id))
                )
        statement = statement.order_by(col(ModelCallRecord.create_time).desc(), col(ModelCallRecord.id).desc())
        statement = statement.limit(limit)

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = list((await session.exec(statement)).all())
        next_cursor = None
        if len(rows) == limit and rows:
            last = rows[-1]
            if last.create_time is not None and last.id is not None:
                next_cursor = encode_cursor(last.create_time, last.id)
        return rows, next_cursor

    @classmethod
    async def aiter_export(
        cls,
        tenant_id: int | None,
        *,
        credential_id: int | None = None,
        app_id: str | None = None,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        page_size: int = 500,
    ):
        """Walk the same selection page by page, for F056's export."""

        cursor: str | None = None
        while True:
            rows, cursor = await cls.alist(
                tenant_id,
                credential_id=credential_id,
                app_id=app_id,
                time_from=time_from,
                time_to=time_to,
                cursor=cursor,
                limit=page_size,
            )
            for row in rows:
                yield row
            if cursor is None:
                return


__all__ = ["ModelCallRecordRepository", "decode_cursor", "encode_cursor"]
