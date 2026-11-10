"""``hosted_app_subject`` — the integer identity a hosted application borrows
to become an Open API credential subject (F055 design D13 / T055).

Why this table exists at all: ``api_credential.subject_id`` is a ``BIGINT``
("typed subject identifier") while ``app.id`` is a uuid **string** — the three
legs of the build-page UNION forced that (``database/models/app.py``). A hosted
application therefore has no integer to put in ``subject_id``, and the two
alternatives were both worse:

* widening ``subject_id`` to a string would touch every service-account and
  personal-token row and every index over them, for one subject kind;
* reusing ``owner_user_id`` would make ``revoke_subject('hosted_app', owner)``
  revoke **every** application that person owns — one stop would silently take
  down their other apps.

So each application is assigned one surrogate here, once, and everything on the
credential side (the subject index, ``list_by_subject``, ``revoke_subject``)
keeps working unchanged.

Two properties are load bearing:

* **No ``tenant_id`` column.** The mapping is pure identity; isolation is
  derived from the ``app`` row, exactly as ``app_version`` derives it (design
  K5 ②). The credential row carries its own ``tenant_id`` and the resolver
  cross-checks it against ``app.tenant_id``, so a surrogate leaking across
  tenants still authenticates nothing.
* **Rows are never deleted.** Deleting an application revokes its credentials
  (AC-58) but leaves this row, so the surrogate is never handed to a different
  application and old audit rows keep resolving.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class HostedAppSubject(SQLModelSerializable, table=True):
    """One application's stable integer handle on the credential side."""

    __tablename__ = "hosted_app_subject"
    __table_args__ = (UniqueConstraint("app_id", name="uk_hosted_app_subject_app"),)

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    app_id: str = Field(
        sa_column=Column(String(36), nullable=False, comment="app.id this subject stands for"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class HostedAppSubjectDao:
    """Single-row reads and one insert. Sessions are the caller's job."""

    @classmethod
    async def aget(cls, session: AsyncSession, subject_id: int) -> HostedAppSubject | None:
        result = await session.exec(select(HostedAppSubject).where(HostedAppSubject.id == subject_id))
        return result.first()

    @classmethod
    async def aget_by_app(cls, session: AsyncSession, app_id: str) -> HostedAppSubject | None:
        result = await session.exec(select(HostedAppSubject).where(HostedAppSubject.app_id == app_id))
        return result.first()

    @classmethod
    async def acreate(cls, session: AsyncSession, app_id: str) -> HostedAppSubject:
        row = HostedAppSubject(app_id=app_id)
        session.add(row)
        await session.flush()
        return row
