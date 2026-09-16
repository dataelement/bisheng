"""The approval-time temporary preview instance (F055 AC-26 … AC-30 / T053).

An approver looking at a release can read its code (the review view, T052) and
— here — *run* it: a throwaway instance of the version waiting to go live, with
a temporary empty database, reachable at ``/apps/preview/{session}`` and gone
again when the approval ends.

Four rules decide everything in this file:

* **Whoever may decide on the release may run it.** The access rule is F055's
  own :class:`ReviewAccess` — an approver holding a task on *that version*,
  plus the owner, the app's tenant administrator and a platform super admin.
  It is the AC-30 exception spelled out: a first-release application is
  invisible to everybody, and the review view and this preview are the two
  sanctioned ways in.
* **A preview is per approver, not per release.** Two approvers on one request
  each get their own instance, because each is injected with their own identity
  (AC-27) and sharing one would show approver B whatever approver A typed into
  the trial.
* **The instance is not the application's.** It goes up through the
  ``preview_*`` intents, which write no desired-state record in the
  orchestrator — so it holds no instance slot (AC-26), the reconciler never
  touches it, and the application's own container keeps serving its own version
  untouched. Its ``/data`` is a tmpfs: trial data cannot reach production
  (AC-29).
* **Reclaiming is idempotent and has three triggers** (AC-28): the approval
  reaching a terminal state, the approver pressing 「回收」, and the deadline
  (``settings.app_runtime.preview_ttl_days``, default 7 days) passing.
  Whichever arrives first closes the row and says why; the others change
  nothing. The orchestrator is always told, even when the row was already
  closed — a row and a container can disagree after a crash, and the container
  is the expensive half.

**The timeout has two enforcement points, deliberately, and neither is a
timer in this process.** The *container* is reclaimed by runtime-manager's own
reconcile pass, which reads the deadline off a label — the process that owns
the container is the one that must be alive for it to exist, and F054 AC-59
forbids the platform image growing a resident worker for the app factory
(``test_switch_off_no_resident_process_or_beat_task``). The *row* converges
here: :meth:`resolve_entry` refuses an expired session on the spot, so the
deadline is exact from a visitor's point of view, and :meth:`reclaim_expired`
runs whenever an approver opens the panel — one indexed query over
``(status, expires_at)``, which is cheap and bounded. A row that says
「运行中」 for a container the manager already removed is therefore the worst
that can happen, and it lasts until the next panel open.

**What this service deliberately does not do:** it never writes ``app.state``,
never touches ``app_version`` and never goes near the application's own
instance. A preview is an ephemeral side object; if it ever needs to change the
application, something has gone wrong with the design rather than with the code.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.constants import AppReleaseAuditAction
from bisheng.app_publish.domain.models.app_preview_session import (
    PREVIEW_STATUS_RECLAIMED,
    PREVIEW_STATUS_RUNNING,
    RECLAIM_REASON_APPROVAL_TERMINAL,
    RECLAIM_REASON_EXPIRED,
    RECLAIM_REASON_MANUAL,
    RECLAIM_REASON_START_FAILED,
    AppPreviewSession,
    AppPreviewSessionDao,
)
from bisheng.app_publish.domain.services.release_audit import write_release_audit
from bisheng.app_publish.domain.services.snapshot_browse_service import ReviewAccess
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.app_runtime.domain.services.orchestrator_client import orchestrator_client
from bisheng.common.errcode.app_factory import AppCapacityInsufficientError, AppProbeFailedError
from bisheng.common.errcode.app_publish import (
    AppPreviewForbiddenError,
    AppPreviewNotRunnableError,
    AppPreviewSessionNotFoundError,
    AppPreviewStartFailedError,
    AppVersionReviewForbiddenError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import AppDao

#: What the panel renders. ``absent`` is the fourth interface state ("not raised
#: yet"); the other three mirror the row's own status plus the transitional
#: window the platform cannot observe directly.
PREVIEW_STATE_ABSENT = "absent"
PREVIEW_STATE_RUNNING = "running"
PREVIEW_STATE_RECLAIMED = "reclaimed"

#: Health defaults of a preview, matching ``AppStateService._DEFAULT_HEALTH``.
#: Restated rather than imported: F055 must not reach into F054's private
#: module constants, and the manager applies its own defaults for anything the
#: manifest leaves out anyway.
_DEFAULT_HEALTH: dict[str, Any] = {"path": "/", "interval": 10, "timeout": 3, "retries": 3, "start_period": 20}

#: Entry prefix of a preview instance, the app-proxy's route for it. A constant
#: rather than an f-string at each use so the contract with app-proxy and with
#: F054's entry layout has one spelling.
PREVIEW_ENTRY_PREFIX = "/apps/preview"


def preview_entry_path(session_id: str) -> str:
    return f"{PREVIEW_ENTRY_PREFIX}/{session_id}"


class PreviewInstanceService:
    """Raise, describe and reclaim one approver's trial of a pending version."""

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    @classmethod
    async def describe(cls, app_id: str, version_id: str, *, actor) -> dict[str, Any]:
        """What the panel needs: this approver's own trial, and whether one is possible.

        Answering "can this version be previewed at all" here rather than only
        on the start call is what lets the panel grey the button out with a
        reason instead of offering an action that is going to fail.
        """
        app, _role = await cls._require_access(app_id, version_id, actor)
        version = await cls._load_version(app.id, version_id)
        # The panel opening is the platform's cue to close out whatever timed
        # out while nobody was looking — see the module docstring for why this
        # is not a scheduled task.
        await cls.reclaim_expired()
        session = await cls._current_session(version_id, cls._user_id(actor))
        return cls._payload(session, runnable_reason=cls._not_runnable_reason(version))

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    @classmethod
    async def start(cls, app_id: str, version_id: str, *, actor) -> dict[str, Any]:
        """AC-26 — bring the pending version up for this approver, or say why not.

        An already-running trial of the same version by the same person is
        **returned as-is** rather than replaced: the 「拉起预览」 button is the
        only way here, a double click is the normal way to press it twice, and
        tearing down a live instance to build an identical one would drop
        whatever the approver had already typed into it.
        """
        app, _role = await cls._require_access(app_id, version_id, actor)
        version = await cls._load_version(app.id, version_id)
        user_id = cls._user_id(actor)

        reason = cls._not_runnable_reason(version)
        if reason is not None:
            raise AppPreviewNotRunnableError(
                msg=cls._not_runnable_message(reason),
                details={"app_id": app.id, "version_id": version_id, "reason": reason},
                hints=cls._not_runnable_hints(reason),
            )

        existing = await cls._current_session(version_id, user_id)
        if existing is not None and cls._is_live(existing):
            return cls._payload(existing, runnable_reason=None)
        if existing is not None:
            # Past its deadline. ``describe`` sweeps before it reads, but this
            # call can arrive without one (a stale panel, a direct POST), and
            # handing back a session the entry would refuse is worse than
            # raising a new one.
            await cls._reclaim_one(existing, reason=RECLAIM_REASON_EXPIRED, app=app)

        row = await cls._insert_session(app=app, version_id=version_id, approver_user_id=user_id)
        payload = await cls._start_payload(app, version, row)
        try:
            await orchestrator_client.preview_start(**payload)
        except (AppCapacityInsufficientError, AppProbeFailedError) as exc:
            # The orchestrator already tore the container down on both of these,
            # so the only thing left over is our own row — close it, or the
            # panel would show a running trial that does not exist and the
            # sweep would keep asking the manager about it for seven days.
            await cls._close_row(row.id, reason=RECLAIM_REASON_START_FAILED)
            logger.warning(
                f"app_publish.preview_start_failed app_id={app.id} version_id={version_id} "
                f"session={row.id} error={exc!r}"
            )
            raise AppPreviewStartFailedError(
                msg="预览实例拉起失败",
                details={
                    "app_id": app.id,
                    "version_id": version_id,
                    "reason": getattr(exc, "Code", None),
                    "detail": str(getattr(exc, "msg", "") or exc),
                },
                hints=["可稍后重新点击「拉起预览」", "若持续失败, 请联系平台管理员查看运行环境容量与应用启动日志"],
            ) from exc
        except Exception:
            await cls._close_row(row.id, reason=RECLAIM_REASON_START_FAILED)
            logger.exception(f"app_publish.preview_start_error app_id={app.id} version_id={version_id}")
            raise

        await cls._audit(
            AppReleaseAuditAction.PREVIEW_STARTED,
            app=app,
            version=version,
            operator_id=user_id,
            metadata={"session_id": row.id, "expires_at": row.expires_at.isoformat()},
        )
        logger.info(
            f"app_publish.preview_started app_id={app.id} version_id={version_id} session={row.id} approver={user_id}"
        )
        return cls._payload(row, runnable_reason=None)

    # ------------------------------------------------------------------
    # reclaim
    # ------------------------------------------------------------------

    @classmethod
    async def reclaim(cls, app_id: str, session_id: str, *, actor) -> dict[str, Any]:
        """AC-26/AC-28 — the approver's 「手动回收」 button.

        The access rule is checked against the *session's own* version, not
        against whatever the caller claims, and the session must belong to this
        caller: an approver may reclaim their own trial and nobody else's, even
        though both of them could read the same code.
        """
        row = await cls._load_session(session_id)
        if row is None or str(row.app_id) != str(app_id):
            raise AppPreviewSessionNotFoundError(details={"session_id": session_id, "app_id": app_id})
        app, _role = await cls._require_access(row.app_id, row.version_id, actor)
        if int(row.approver_user_id or 0) != cls._user_id(actor):
            raise AppPreviewForbiddenError(
                msg="只能回收自己拉起的预览实例",
                details={"session_id": session_id, "reason": "not_owner_of_session"},
            )

        closed = await cls._reclaim_one(row, reason=RECLAIM_REASON_MANUAL, app=app)
        refreshed = await cls._load_session(session_id)
        logger.info(f"app_publish.preview_reclaimed session={session_id} reason=manual closed={closed}")
        return cls._payload(refreshed, runnable_reason=None)

    @classmethod
    async def reclaim_for_version(cls, app_id: str, version_id: str, *, reason: str) -> int:
        """Every live trial of one version — the terminal-approval trigger (AC-28).

        Best effort by construction: it is called from the approval callbacks,
        where raising would tell the outbox the *approval* failed. A preview
        that outlives its approval is a wasted container; a failed approval
        callback pages an administrator.
        """
        try:
            rows = await cls._list_running(version_id)
        except Exception:
            logger.exception(f"app_publish.preview_reclaim_scan_failed app_id={app_id} version_id={version_id}")
            return 0

        reclaimed = 0
        for row in rows:
            try:
                if await cls._reclaim_one(row, reason=reason):
                    reclaimed += 1
            except Exception:
                logger.exception(f"app_publish.preview_reclaim_failed session={row.id}")
        if reclaimed:
            logger.info(
                f"app_publish.preview_reclaimed_for_version app_id={app_id} version_id={version_id} "
                f"count={reclaimed} reason={reason}"
            )
        return reclaimed

    @classmethod
    async def reclaim_on_release_terminal(cls, payload_snapshot: dict) -> int:
        """Adapter for the approval callbacks — they all carry the same snapshot."""
        return await cls.reclaim_for_version(
            str(payload_snapshot.get("app_id") or ""),
            str(payload_snapshot.get("version_id") or ""),
            reason=RECLAIM_REASON_APPROVAL_TERMINAL,
        )

    @classmethod
    async def reclaim_expired(cls, *, now: datetime | None = None, limit: int = 200) -> int:
        """AC-28's timeout leg on the platform side — close rows past their deadline.

        Cross-tenant and read under ``bypass_tenant_filter``: the caller is an
        approver of *one* tenant opening a panel, and the sweep is meant to
        cover everything, so scoping it to the caller's tenant would leave
        other tenants' rows saying 「运行中」 forever. Each reclaim then
        re-establishes nothing — closing a row and telling the orchestrator are
        both keyed by id.

        Never raises: it runs as a side errand of a read, and an approver must
        not be shown an error because somebody else's trial would not close.
        """
        deadline = now or datetime.now()
        try:
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    rows = await AppPreviewSessionDao.alist_expired(session, now=deadline, limit=limit)
        except Exception:
            logger.exception("app_publish.preview_expire_scan_failed")
            return 0
        reclaimed = 0
        for row in rows:
            try:
                if await cls._reclaim_one(row, reason=RECLAIM_REASON_EXPIRED):
                    reclaimed += 1
            except Exception:
                logger.exception(f"app_publish.preview_expire_failed session={row.id}")
        if reclaimed:
            logger.info(f"app_publish.preview_expired count={reclaimed}")
        return reclaimed

    # ------------------------------------------------------------------
    # entry resolution (consumed by F054's entry authorization, T090)
    # ------------------------------------------------------------------

    @classmethod
    async def resolve_entry(cls, session_id: str) -> AppPreviewSession | None:
        """The live session behind ``/apps/preview/{session}``, or ``None``.

        ``None`` covers "no such session", "already reclaimed" and "past its
        deadline" alike — the entry path answers all three with the same page,
        so a stranger cannot use the difference to learn that a session id was
        ever real.
        """
        row = await cls._load_session(session_id)
        return row if row is not None and cls._is_live(row) else None

    @staticmethod
    def _is_live(row: AppPreviewSession) -> bool:
        """Running **and** inside its deadline.

        The deadline is checked in Python rather than left to whatever reclaims
        the container: the sweep runs on the manager's own cadence, and a
        visitor must not get in during the gap. This is what makes the expiry
        exact from the approver's point of view (AC-28).
        """
        if row.status != PREVIEW_STATUS_RUNNING:
            return False
        return row.expires_at is None or row.expires_at > datetime.now()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _user_id(actor) -> int:
        return int(getattr(actor, "user_id", 0) or 0)

    @classmethod
    async def _require_access(cls, app_id: str, version_id: str, actor):
        """``ReviewAccess``, re-raised in this feature's own vocabulary.

        The rule is shared with the review view on purpose — "who may look at
        this release" has exactly one answer — but the *copy* must not be: 16257
        says "you cannot view the source", which is the wrong sentence next to a
        button that runs the thing.
        """
        app = await ReviewAccess.load_app(app_id)
        try:
            role = await ReviewAccess.require(app, actor, (version_id,))
        except AppVersionReviewForbiddenError as exc:
            raise AppPreviewForbiddenError(
                msg="没有预览该版本的权限",
                details={"app_id": app_id, "version_id": version_id, "reason": "not_reviewer"},
                hints=["只有应用负责人、租户管理员和该版本的审批人可以预览"],
            ) from exc
        set_current_tenant_id(int(app.tenant_id or 0))
        return app, role

    @staticmethod
    async def _load_version(app_id: str, version_id: str):
        from bisheng.common.errcode.app_publish import AppVersionNotFoundError

        version = await VersionService.get_version(app_id, version_id)
        if version is None:
            raise AppVersionNotFoundError(
                msg="版本记录不存在",
                details={"app_id": app_id, "version_id": version_id},
            )
        return version

    @staticmethod
    def _not_runnable_reason(version) -> str | None:
        """Why this version cannot be tried, or ``None`` when it can.

        Two reasons, and the order matters: a version that ended its approval
        is reported as ``settled`` even if it also has no image, because
        "this release is over" is the more useful sentence.
        """
        if version.terminal_state:
            return "settled"
        if not (version.image_ref or "").strip():
            return "no_image"
        return None

    @staticmethod
    def _not_runnable_message(reason: str) -> str:
        return {
            "settled": "该版本的审批已结束, 不能再拉起预览",
            "no_image": "该版本还没有构建产物, 暂时无法预览",
        }.get(reason, "该版本暂时无法预览")

    @staticmethod
    def _not_runnable_hints(reason: str) -> list[str]:
        return {
            "settled": ["如需再次试用, 请等待新的发布申请"],
            "no_image": ["请等待发布流程完成构建后重试"],
        }.get(reason, [])

    @classmethod
    async def _insert_session(cls, *, app, version_id: str, approver_user_id: int) -> AppPreviewSession:
        ttl_days = max(int(settings.app_runtime.preview_ttl_days), 1)
        row = AppPreviewSession(
            tenant_id=int(app.tenant_id or 0),
            app_id=app.id,
            version_id=version_id,
            approver_user_id=approver_user_id,
            status=PREVIEW_STATUS_RUNNING,
            # Stamped now, from the setting as it stands now: shortening the
            # deployment setting later must not retroactively kill a trial
            # somebody is in the middle of.
            expires_at=datetime.now() + timedelta(days=ttl_days),
        )
        async with get_async_db_session() as session:
            await AppPreviewSessionDao.acreate(session, row)
            await session.commit()
        return row

    @classmethod
    async def _start_payload(cls, app, version, row: AppPreviewSession) -> dict[str, Any]:
        manifest = version.manifest if isinstance(version.manifest, dict) else {}
        injections = version.injections if isinstance(version.injections, dict) else {}
        env = injections.get("env") if isinstance(injections.get("env"), dict) else {}
        health = manifest.get("health") if isinstance(manifest.get("health"), dict) else {}
        return {
            "session_id": row.id,
            "app_id": app.id,
            "version_id": version.id,
            "image_ref": version.image_ref or "",
            "tier": await cls._tier_payload(version.tier_id),
            "port": int(manifest.get("port") or 8080),
            # The manager reclaims the container on its own once this passes —
            # the platform has no timer of its own (see the module docstring).
            "expires_at": int(row.expires_at.timestamp()),
            "env": {
                **{str(key): str(value) for key, value in env.items()},
                # The app rebuilds absolute URLs from this, and under a preview
                # it is not ``/apps/{slug}``: the same source has to work at
                # both entry points, which is exactly what ``base_path`` /
                # ``X-Forwarded-Prefix`` are for (F054 D5.2).
                "BISHENG_APP_BASE_PATH": preview_entry_path(row.id),
            },
            "health": {**_DEFAULT_HEALTH, **health},
        }

    @staticmethod
    async def _tier_payload(tier_id: str | None) -> dict[str, Any]:
        """``{cpu: vCPU float, mem: MiB int}`` for the tier this version froze.

        ``resolve_spec``, not ``resolve_tier``: the version already chose its
        tier at submit time and AC-47 keeps a retired tier resolvable for the
        releases that froze it. Refusing to preview a release because an
        administrator retired its tier in the meantime would block an approval
        over a change that has nothing to do with the release.
        """
        from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService
        from bisheng.database.models.resource_tier import DEFAULT_TIER_CODE

        tier = await ResourceTierService.resolve_spec(tier_id or DEFAULT_TIER_CODE)
        return {"cpu": tier.cpu_millicores / 1000, "mem": tier.memory_mb}

    @staticmethod
    async def _current_session(version_id: str, approver_user_id: int) -> AppPreviewSession | None:
        async with get_async_db_session() as session:
            return await AppPreviewSessionDao.aget_running_for(
                session, version_id=version_id, approver_user_id=approver_user_id
            )

    @staticmethod
    async def _load_session(session_id: str) -> AppPreviewSession | None:
        if not session_id:
            return None
        # Bypass, not the current tenant: the entry path resolves a session
        # before any tenant context exists, and the row's own tenant_id is what
        # establishes it afterwards.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return await AppPreviewSessionDao.aget(session, session_id)

    @staticmethod
    async def _list_running(version_id: str) -> list[AppPreviewSession]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return await AppPreviewSessionDao.alist_running_by_version(session, version_id)

    @staticmethod
    async def _close_row(session_id: str, *, reason: str) -> bool:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                closed = await AppPreviewSessionDao.amark_reclaimed(session, session_id, reason=reason)
                await session.commit()
        return closed

    @classmethod
    async def _reclaim_one(cls, row: AppPreviewSession, *, reason: str, app=None) -> bool:
        """Close the row, then tell the orchestrator. Order is deliberate.

        The row first: if the process dies between the two, the panel already
        says 「已回收」 and the sweep will not re-offer a session nobody can
        open, while the container is picked up by the next reclaim of the same
        session (``preview_stop`` is idempotent). The other order would leave a
        row claiming a running instance that is already gone.
        """
        closed = await cls._close_row(row.id, reason=reason)
        # Told even when the row was already closed: a row and a container can
        # disagree after a crash, and the container is the expensive half.
        try:
            await orchestrator_client.preview_stop(session_id=row.id)
        except Exception:
            logger.exception(f"app_publish.preview_stop_failed session={row.id} reason={reason}")
        if closed:
            await cls._audit_reclaim(row, reason=reason, app=app)
        return closed

    @classmethod
    async def _audit_reclaim(cls, row: AppPreviewSession, *, reason: str, app=None) -> None:
        app_row = app if app is not None else await cls._load_app(row.app_id)
        if app_row is None:
            return
        version = await VersionService.get_version(row.app_id, row.version_id)
        await cls._audit(
            AppReleaseAuditAction.PREVIEW_RECLAIMED,
            app=app_row,
            version=version,
            operator_id=int(row.approver_user_id or 0),
            metadata={"session_id": row.id, "reclaim_reason": reason},
            reason=reason,
        )

    @staticmethod
    async def _load_app(app_id: str):
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return await AppDao.aget(session, app_id)

    @staticmethod
    async def _audit(
        action: AppReleaseAuditAction,
        *,
        app,
        version,
        operator_id: int,
        metadata: dict[str, Any],
        reason: str | None = None,
    ) -> None:
        from types import SimpleNamespace

        await write_release_audit(
            action,
            deployment=SimpleNamespace(
                id=None,
                app_id=app.id,
                tenant_id=int(app.tenant_id or 0),
                version_id=getattr(version, "id", None),
                submitted_by_user_id=operator_id,
                stage=None,
            ),
            version_no=getattr(version, "version_no", None),
            operator_id=operator_id,
            metadata=metadata,
            reason=reason,
        )

    @staticmethod
    def _payload(row: AppPreviewSession | None, *, runnable_reason: str | None) -> dict[str, Any]:
        """The four interface states of AC-26, as one shape.

        ``absent`` and ``reclaimed`` are different answers on purpose: the first
        says "you have not tried this yet", the second says "your trial is
        over" — and only the second explains why. The 「拉起中」 state the panel
        shows is the client's own, covering the seconds its request is in
        flight; the platform never observes a half-started preview because
        ``preview_start`` returns only after the readiness gate.

        ``reclaimed`` is what the reclaim *call* answers with. A later read of
        the same version comes back ``absent``, and deliberately so: the
        finished trial has nothing left to offer, and 「已回收」 kept on screen
        forever would read as a state the approver is stuck in rather than one
        they can leave by pressing the button again.
        """
        if row is None:
            return {
                "state": PREVIEW_STATE_ABSENT,
                "session_id": None,
                "entry_url": None,
                "expires_at": None,
                "reclaim_reason": None,
                "runnable": runnable_reason is None,
                "not_runnable_reason": runnable_reason,
            }
        running = row.status == PREVIEW_STATUS_RUNNING
        return {
            "state": PREVIEW_STATE_RUNNING if running else PREVIEW_STATE_RECLAIMED,
            "session_id": row.id,
            "entry_url": preview_entry_path(row.id) if running else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "reclaim_reason": row.reclaim_reason if row.status == PREVIEW_STATUS_RECLAIMED else None,
            "runnable": runnable_reason is None,
            "not_runnable_reason": runnable_reason,
        }
