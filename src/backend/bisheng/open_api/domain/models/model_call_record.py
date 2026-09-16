"""One row per model call made through the model protocol face (F051).

Deliberately its own table rather than a new ``audit_log`` action: this face is
the high-frequency one (a local coding agent calls it in a loop), and mixing it
into the audit table would drown every human-scale audit event the page exists
to show. ``audit_log`` still carries one ``open_api.call`` row per request — the
two are complementary, not duplicates (design D9 / K7).

No message body, no key plaintext, no provider configuration is ever stored
here (AC-36).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable

# ``result`` values. ``model_unavailable`` covers the whole 26211-26216 family:
# the call reached model resolution and was refused there, which is exactly the
# boundary AC-20 draws for "gets a row" vs "is only an audit event".
RESULT_SUCCESS = "success"
RESULT_UPSTREAM_FAILED = "upstream_failed"
RESULT_MODEL_UNAVAILABLE = "model_unavailable"
RESULT_LIMIT_EXCEEDED = "limit_exceeded"
RESULT_CAPABILITY_UNDECLARED = "capability_undeclared"
RESULT_CLIENT_DISCONNECTED = "client_disconnected"

SUBJECT_KIND_USER = "user"
SUBJECT_KIND_APP_SELF = "app_self"


class ModelCallRecord(SQLModelSerializable, table=True):
    """Per-call model usage record; F051 writes it, F056 only reads it."""

    __tablename__ = "model_call_record"
    __table_args__ = (
        # AC-24's three filters (key / target application / time range) get one
        # index each. Service account, model and token counts are record
        # columns, not filters — no index for them on purpose.
        Index("ix_mcr_tenant_time", "tenant_id", "create_time", "id"),
        Index("ix_mcr_credential_time", "credential_id", "create_time"),
        Index("ix_mcr_app_time", "app_id", "create_time"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, comment="Credential's tenant"),
    )
    credential_id: int = Field(
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False, comment="api_credential.id"),
    )
    credential_mask: str | None = Field(
        default=None,
        sa_column=Column(String(32), nullable=True, comment="bs-sak-********xxxx; never the plaintext"),
    )
    actor_kind: str = Field(
        sa_column=Column(String(32), nullable=False, comment="service_account | natural_person | hosted_app"),
    )
    actor_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True),
    )
    actor_name: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    resource_owner_user_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True, comment="Traceable owner"),
    )
    app_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True, comment="Hosted application dimension (AC-21)"),
    )
    subject_kind: str | None = Field(
        default=None,
        sa_column=Column(String(16), nullable=True, comment="service_account | natural_person | user | app_self"),
    )
    subject_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True),
    )
    requested_model: str = Field(
        sa_column=Column(String(255), nullable=False, comment="Model name as the caller wrote it"),
    )
    model_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    server_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    model_name: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    server_name: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    server_type: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    is_stream: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    # NULL means "upstream did not say", which is not the same as zero (AC-23).
    prompt_tokens: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    completion_tokens: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    total_tokens: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    result: str = Field(sa_column=Column(String(32), nullable=False))
    error_code: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    http_status: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    latency_ms: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    ttft_ms: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    request_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    trace_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    create_time: datetime | None = Field(
        default=None,
        # ``text("CURRENT_TIMESTAMP")`` rather than ``func.now()``: the same
        # spelling api_credential uses, already proven on both MySQL and DM8.
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )


__all__ = [
    "RESULT_CAPABILITY_UNDECLARED",
    "RESULT_CLIENT_DISCONNECTED",
    "RESULT_LIMIT_EXCEEDED",
    "RESULT_MODEL_UNAVAILABLE",
    "RESULT_SUCCESS",
    "RESULT_UPSTREAM_FAILED",
    "SUBJECT_KIND_APP_SELF",
    "SUBJECT_KIND_USER",
    "ModelCallRecord",
]
