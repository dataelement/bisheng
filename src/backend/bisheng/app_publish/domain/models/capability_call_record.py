"""``app_capability_call_record`` — one row per non-model capability call (F055 T059 / AC-55).

Dual attribution is the whole point of the table: **actor** is the application
(``app_id`` / ``credential_id``) and **subject** is the person the call was made
for (``subject_user_id``). Both are columns rather than one "operator", because
the two answers to "who did this" are genuinely different here and collapsing
them is how an application's search of somebody's knowledge base ends up
attributed to its owner.

Its own table rather than an ``audit_log`` action, for the reason F051's
``model_call_record`` gives (design D9 / K7): a hosted application retrieves
once per question its users ask, and mixing that volume into ``audit_log``
drowns the human-scale events that page exists to show. The two tables are
siblings — model calls land in ``model_call_record``, which already carries the
same actor/subject pair, and everything else lands here.

What is **not** stored: the query text, the retrieved content, and the
credential plaintext. ``targets`` holds knowledge ids only — "which knowledge
base was searched" is the auditable fact; "what was asked" is the user's.

There is no ``subject_kind = 'app_self'`` row in this table by construction:
retrieval without an access user is refused before it happens (AC-52), so an
attributable subject always exists. Only the model face may attribute a call to
the application itself, and it records that in its own table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, text
from sqlmodel import Field
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType

#: ``capability`` values. Models are recorded by F051 in ``model_call_record``;
#: this column exists so a second non-model capability (PRD-2's secrets) does
#: not need a second table.
CAPABILITY_KNOWLEDGE = "knowledge"

#: ``result`` values.
RESULT_SUCCESS = "success"
RESULT_REFUSED = "refused"
RESULT_FAILED = "failed"


class AppCapabilityCallRecord(SQLModelSerializable, table=True):
    """One capability call, with both of its attributions."""

    __tablename__ = "app_capability_call_record"
    __table_args__ = (
        Index("ix_accr_app_time", "app_id", "create_time"),
        Index("ix_accr_tenant_time", "tenant_id", "create_time", "id"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=False, comment="The application's tenant")
    )
    #: Actor — the application. ``app_id`` is ``app.id`` (uuid), never the
    #: display name and never the credential subject surrogate.
    app_id: str = Field(sa_column=Column(String(64), nullable=False, comment="Acting application (app.id)"))
    app_name: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    credential_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True, comment="api_credential.id"),
    )
    #: Subject — the access user, established by the short-lived token F054
    #: injects per visitor. Never the owner, and never absent for a row that
    #: exists (see the module docstring).
    subject_kind: str = Field(default="user", sa_column=Column(String(16), nullable=False, comment="user"))
    subject_user_id: int = Field(
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False, comment="The access user"),
    )
    capability: str = Field(sa_column=Column(String(32), nullable=False, comment="knowledge | …"))
    #: What was reached for. Knowledge ids, as declared and as narrowed —
    #: ``{"requested": [...], "effective": [...]}``; never the query text.
    targets: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    result: str = Field(sa_column=Column(String(16), nullable=False))
    error_code: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    chunk_count: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    latency_ms: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    version_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, comment="Version whose declaration authorised the call"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )


class AppCapabilityCallRecordDao:
    """INSERT-only. Nothing updates a record of something that already happened."""

    @classmethod
    async def ainsert(cls, session: AsyncSession, row: AppCapabilityCallRecord) -> AppCapabilityCallRecord:
        session.add(row)
        await session.flush()
        return row


__all__ = [
    "CAPABILITY_KNOWLEDGE",
    "RESULT_FAILED",
    "RESULT_REFUSED",
    "RESULT_SUCCESS",
    "AppCapabilityCallRecord",
    "AppCapabilityCallRecordDao",
]
