"""``app_deployment`` — one publish attempt of a hosted application (F055 design D1 / §4.2 ⑤).

Facts that are easy to get wrong:

* **This is not ``app_version``.** A deployment row records an *attempt*;
  a version row records a *result*. AC-02 / 决议-9 require that a submission
  which fails precheck or the secret scan never appears in the version list,
  and F054 pinned ``app_version`` to INSERT-only with a single-column
  ``terminal_state`` latch — so a failed attempt has nowhere to live there.
  Everything about progress, failure and the scan report belongs here.
* **``stage`` and ``status`` are explicit VARCHAR columns, never JSON keys.**
  The CLI polls by ``deployment_id`` and the app-level lookup filters on
  ``(app_id, status)``; ``JSON_EXTRACT`` / ``JSON_CONTAINS`` are banned on DM8
  (C2 / design K6). The same rule is why ``tier_code`` is a column rather than
  a lookup into ``manifest``.
* **``app_id`` is nullable for exactly one instant.** A first-time publish
  creates the row, then calls F054 ``create_draft`` and back-fills the id
  (design D2 备选 B). Every later stage reads it as present.
* **``manifest`` / ``failure`` / ``scan_result`` are ``JsonType``** (CLOB on
  DM8) and are only ever inspected in Python. ``failure`` always holds the
  five-tuple ``{stage, code, message, details, hints}`` — AC-11's only shape.
* **The DAO issues single-row writes only.** The tenant filter rewrites SELECT
  statements and nothing else (repo memory
  ``reference_tenant_filter_in_list_trap``), so a bulk UPDATE / DELETE would
  escape isolation without a trace. ``aadvance_stage`` and ``aset_failed`` are
  both pinned to the primary key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index, Integer, String, text, update
from sqlmodel import Field, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.utils import generate_uuid

# ---------------------------------------------------------------------------
# ``stage`` — where the linear pipeline currently stands (design D1).
#
# The order below *is* the pipeline order. ``secret_scan`` sits before the
# precheck stages because spec AC-01 / F053 AC-31a say so verbatim; moving it
# earlier (design D5's open question) means re-ordering PIPELINE_STAGES in the
# service and amending both specs — never one side alone.
# ---------------------------------------------------------------------------
STAGE_RECEIVED = "received"
STAGE_PRECHECK_MANIFEST = "precheck_manifest"
STAGE_PRECHECK_BUILD = "precheck_build"
STAGE_PRECHECK_PROBE = "precheck_probe"
STAGE_SECRET_SCAN = "secret_scan"
STAGE_VERSION_RECORDED = "version_recorded"
STAGE_APPROVAL_CREATED = "approval_created"
STAGE_APPROVED = "approved"
STAGE_PUBLISHING = "publishing"
STAGE_ONLINE = "online"
STAGE_PENDING_ONLINE = "pending_online"

DEPLOYMENT_STAGES: frozenset[str] = frozenset(
    {
        STAGE_RECEIVED,
        STAGE_PRECHECK_MANIFEST,
        STAGE_PRECHECK_BUILD,
        STAGE_PRECHECK_PROBE,
        STAGE_SECRET_SCAN,
        STAGE_VERSION_RECORDED,
        STAGE_APPROVAL_CREATED,
        STAGE_APPROVED,
        STAGE_PUBLISHING,
        STAGE_ONLINE,
        STAGE_PENDING_ONLINE,
    }
)

# ---------------------------------------------------------------------------
# ``status`` — the coarse outcome the CLI polls on.
#
# ``waiting_approval`` is deliberately distinct from ``running``: the CLI stops
# there by default (F053 AC-31b) and only ``--wait`` keeps polling. "待上线"
# (capacity / deploy failure after approval) is a *successful* terminal outcome
# of the pipeline — ``status=succeeded`` with ``stage=pending_online`` — not a
# failure (AC-31, design 坑 10).
# ---------------------------------------------------------------------------
STATUS_RUNNING = "running"
STATUS_WAITING_APPROVAL = "waiting_approval"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

DEPLOYMENT_STATUSES: frozenset[str] = frozenset(
    {STATUS_RUNNING, STATUS_WAITING_APPROVAL, STATUS_SUCCEEDED, STATUS_FAILED}
)

#: Statuses of an attempt that is still in flight — the predicate behind
#: "this app already has a deployment running" (AC-03's in-flight gate).
ACTIVE_STATUSES: tuple[str, ...] = (STATUS_RUNNING, STATUS_WAITING_APPROVAL)


class AppDeployment(SQLModelSerializable, table=True):
    """One publish attempt: the progress carrier of the pipeline."""

    __tablename__ = "app_deployment"
    __table_args__ = (
        Index("ix_app_deployment_app_status", "app_id", "status"),
        Index("ix_app_deployment_tenant_create", "tenant_id", "create_time"),
    )

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    # ``default=None`` on purpose: the before_flush hook fills it from the
    # current tenant context. A Python default would silently write
    # child-tenant rows to Root (same guard as ``app`` / ``api_credential``).
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant ID"),
    )
    app_id: str | None = Field(
        default=None,
        sa_column=Column(
            String(36),
            nullable=True,
            comment="Owning app.id; NULL only between row creation and create_draft on a first publish",
        ),
    )
    owner_user_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment="Application owner (natural person); the approval applicant"),
    )
    submitted_by_user_id: int = Field(
        sa_column=Column(
            Integer,
            nullable=False,
            comment="Acting subject of the /api/v2 call — the service-account user, not the owner",
        ),
    )
    version_id: str | None = Field(
        default=None,
        sa_column=Column(
            String(36),
            nullable=True,
            comment="Version id minted at receive time; the app_version row reuses it once precheck passes",
        ),
    )
    approval_instance_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment="approval_instance.id once the gate created one"),
    )
    stage: str = Field(
        sa_column=Column(String(32), nullable=False, comment="Pipeline stage; see DEPLOYMENT_STAGES"),
    )
    status: str = Field(
        sa_column=Column(String(16), nullable=False, comment="running | waiting_approval | succeeded | failed"),
    )
    code_object_key: str | None = Field(
        default=None,
        sa_column=Column(String(512), nullable=True, comment="MinIO key of the code snapshot; never inline"),
    )
    manifest: dict | None = Field(
        default=None,
        sa_column=Column(JsonType, nullable=True, comment="Parsed bisheng-app.yaml; inspected in Python only"),
    )
    tier_code: str | None = Field(
        default=None,
        sa_column=Column(String(32), nullable=True, comment="Resolved resource_tier.code of this attempt"),
    )
    failure: dict | None = Field(
        default=None,
        sa_column=Column(
            JsonType, nullable=True, comment="{stage, code, message, details, hints} — AC-11's only shape"
        ),
    )
    scan_result: dict | None = Field(
        default=None,
        sa_column=Column(JsonType, nullable=True, comment="Secret-scan report; hits never carry the matched value"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class AppDeploymentDao:
    """Single-row ORM access. Sessions and transactions belong to the caller.

    No bulk ``update()`` / ``delete()`` and no ``text()`` — see the module
    docstring for why that is an isolation requirement rather than a style
    preference.
    """

    @classmethod
    async def acreate(cls, session: AsyncSession, row: AppDeployment) -> AppDeployment:
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def aget(cls, session: AsyncSession, deployment_id: str) -> AppDeployment | None:
        """One attempt by id. The row carries ``tenant_id``, so the auto filter scopes it."""
        result = await session.exec(select(AppDeployment).where(AppDeployment.id == deployment_id))
        return result.first()

    @classmethod
    async def aget_active_by_app(cls, session: AsyncSession, app_id: str) -> AppDeployment | None:
        """The newest still-in-flight attempt of one app, or ``None``.

        Feeds the "already publishing" gate (AC-03). ``running`` and
        ``waiting_approval`` are both in flight; a succeeded / failed attempt
        never blocks a new submission.
        """
        statement = (
            select(AppDeployment)
            .where(AppDeployment.app_id == app_id, col(AppDeployment.status).in_(ACTIVE_STATUSES))
            .order_by(col(AppDeployment.create_time).desc(), col(AppDeployment.id).desc())
            .limit(1)
        )
        result = await session.exec(statement)
        return result.first()

    @classmethod
    async def alist_by_app(cls, session: AsyncSession, app_id: str, limit: int = 50) -> list[AppDeployment]:
        """Attempts of one app, newest first — the publish-face history and orphan sweep both read it."""
        statement = (
            select(AppDeployment)
            .where(AppDeployment.app_id == app_id)
            .order_by(col(AppDeployment.create_time).desc(), col(AppDeployment.id).desc())
            .limit(limit)
        )
        result = await session.exec(statement)
        return list(result.all())

    @classmethod
    async def aadvance_stage(
        cls,
        session: AsyncSession,
        deployment_id: str,
        *,
        stage: str,
        status: str = STATUS_RUNNING,
        app_id: str | None = None,
        version_id: str | None = None,
        approval_instance_id: int | None = None,
        code_object_key: str | None = None,
        manifest: dict | None = None,
        tier_code: str | None = None,
        scan_result: dict | None = None,
        failure: dict | None = None,
    ) -> bool:
        """Move one attempt to its next stage; ``True`` when the row was touched.

        A **single-row UPDATE pinned to the primary key**. The optional
        arguments exist because several stages produce a value at the same
        moment they advance (``received`` mints ``version_id`` and
        ``code_object_key``, ``approval_created`` learns the instance id); a
        stage that produces nothing simply omits them, and ``None`` means
        "leave this column alone" rather than "write NULL" — no stage of the
        pipeline ever needs to clear one of these columns.

        ``failure`` may be written here *without* ``status`` becoming
        ``failed``, and that is not a contradiction: ``status`` answers "did
        the pipeline finish the job it was given", ``failure`` answers "is
        there something to explain". An attempt parked in ``pending_online``
        succeeded as a pipeline run — precheck, scan, version record and
        approval all happened — and still owes the owner a reason. The CLI
        branches on ``status`` and ``stage``; ``failure`` is what it prints.
        """
        values: dict[str, Any] = {"stage": stage, "status": status, "update_time": datetime.now()}
        for key, value in (
            ("app_id", app_id),
            ("version_id", version_id),
            ("approval_instance_id", approval_instance_id),
            ("code_object_key", code_object_key),
            ("manifest", manifest),
            ("tier_code", tier_code),
            ("scan_result", scan_result),
            ("failure", failure),
        ):
            if value is not None:
                values[key] = value
        result = await session.exec(update(AppDeployment).where(AppDeployment.id == deployment_id).values(**values))
        return bool(result.rowcount)

    @classmethod
    async def aset_failed(
        cls,
        session: AsyncSession,
        deployment_id: str,
        *,
        failure: dict,
        stage: str | None = None,
    ) -> bool:
        """Latch the terminal failure of one attempt; ``True`` when the row was touched.

        ``failure`` is the five-tuple ``{stage, code, message, details, hints}``
        and is written whole — a partially filled failure is what turns a CLI
        error message into "something went wrong" (AC-11). ``stage`` defaults to
        the stage already on the row, so a failure detected inside a stage does
        not have to restate it.
        """
        values: dict[str, Any] = {
            "status": STATUS_FAILED,
            "failure": failure,
            "update_time": datetime.now(),
        }
        if stage is not None:
            values["stage"] = stage
        result = await session.exec(update(AppDeployment).where(AppDeployment.id == deployment_id).values(**values))
        return bool(result.rowcount)
