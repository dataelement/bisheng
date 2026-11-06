"""Dual-purpose previews with atomic registration and a current qualification fence."""

from datetime import UTC
from types import SimpleNamespace
from typing import Any

from loguru import logger

from bisheng.app_publish.application.preview_access import qualified_scope, resolve_preview_context
from bisheng.app_publish.application.preview_runtime import by_reference
from bisheng.app_publish.domain.repositories.preview_runtime_repository import PreviewBinding, PreviewRuntimeRepository
from bisheng.app_publish.domain.schemas.app_manifest import egress_domains_of
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.app_runtime.application.preview_operations import start_preview, stop_preview
from bisheng.common.errcode.app_publish import (
    AppPreviewNotRunnableError,
    AppPreviewSessionNotFoundError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope

_DEFAULT_HEALTH = {"path": "/", "interval": 10, "timeout": 3, "retries": 3, "start_period": 20}


def preview_entry_path(session_id):
    return f"/apps/preview/{session_id}"


class PreviewInstanceService:
    @classmethod
    async def describe(cls, app_id, version_id, *, actor, purpose=None):
        async with qualified_scope(app_id, version_id, actor=actor, purpose=purpose) as q:
            await cls.reclaim_expired()
            row = await cls._current_session(q)
            if row is not None:
                await resolve_preview_context(
                    session_id=row.session_id, viewer_user_id=q.viewer_user_id, allow_starting=True
                )
            version = await cls._load_version(app_id, version_id)
            reason = "settled" if q.purpose == "approval" and version.terminal_state else None
            return cls._payload(row, runnable_reason=reason, purpose=q.purpose)

    @classmethod
    async def start(cls, app_id, version_id, *, actor, purpose=None):
        async with qualified_scope(app_id, version_id, actor=actor, purpose=purpose) as q:
            from bisheng.app_publish.application.release_tenancy import require_release_eligible

            await require_release_eligible(app_id, version_id=version_id)
            version = await cls._load_version(app_id, version_id)
            if q.purpose == "approval" and version.terminal_state:
                raise AppPreviewNotRunnableError(reason="settled")
            session_id = await start_preview(q, actor=actor, payload_factory=cls._start_payload)
            row = await by_reference(session_id=session_id)
            return cls._payload(row, runnable_reason=None, purpose=q.purpose)

    @classmethod
    async def reclaim(cls, app_id, session_id, *, actor):
        with bypass_tenant_filter():
            row = await by_reference(session_id=session_id)
        if row is None or row.app_id != app_id or row.viewer_user_id != int(actor.user_id):
            raise AppPreviewSessionNotFoundError()
        async with qualified_scope(app_id, row.version_id, actor=actor, purpose=row.purpose):
            await stop_preview(session_id, reason="manual")
            row = await by_reference(session_id=session_id)
            return cls._payload(row, runnable_reason=None, purpose=row.purpose)

    @classmethod
    async def _sweep(cls, *, version_id=None, expired=False, approval_terminal=False):
        rows = await PreviewRuntimeRepository.sweep_candidates(
            version_id=version_id, expired=expired, approval_terminal=approval_terminal
        )
        count = 0
        for row in rows:
            with tenant_execution_scope(row.tenant_id):
                try:
                    count += bool(
                        await stop_preview(row.session_id, reason="expired" if expired else "approval_terminal")
                    )
                except Exception:
                    logger.exception("preview reclaim remains pending session={}", row.session_id)
        return count

    @classmethod
    async def reclaim_expired(cls):
        return await cls._sweep(expired=True)

    @classmethod
    async def reclaim_for_version(cls, version_id, **kwargs):
        return await cls._sweep(version_id=version_id, approval_terminal=True)

    @classmethod
    async def reclaim_on_release_terminal(cls, payload_snapshot):
        version_id = (payload_snapshot or {}).get("version_id")
        return await cls.reclaim_for_version(version_id) if version_id else 0

    @classmethod
    async def resolve_entry(cls, session_id):
        try:
            context = await resolve_preview_context(session_id=session_id)
        except Exception:
            return None
        if context is None:
            return None
        with bypass_tenant_filter():
            current = await by_reference(session_id=session_id)
        if current is None:
            return None
        return SimpleNamespace(
            id=context.session_id,
            app_id=context.app_id,
            version_id=context.version_id,
            tenant_id=context.tenant_id,
            approver_user_id=context.viewer_user_id,
            purpose=context.purpose,
            operation_id=context.operation_id,
            credential_id=context.credential_id,
            expires_at=current.expires_at,
        )

    @staticmethod
    async def _load_version(app_id, version_id):
        from bisheng.common.errcode.app_publish import AppVersionNotFoundError

        row = await VersionService.get_version(app_id, version_id)
        if row is None:
            raise AppVersionNotFoundError()
        return row

    @staticmethod
    async def _current_session(q):
        return await PreviewRuntimeRepository.current(q)

    @staticmethod
    def _payload(row, *, runnable_reason=None, purpose=None):
        state = row.status if row else "absent"
        return {
            "state": state,
            "session_id": row.session_id if row else None,
            "entry_url": preview_entry_path(row.session_id) if row and state == "running" else None,
            "expires_at": row.expires_at.isoformat() if row else None,
            "reclaim_reason": getattr(row, "reclaim_reason", None),
            "purpose": purpose,
            "runnable": runnable_reason is None,
            "not_runnable_reason": runnable_reason,
        }

    @classmethod
    async def _start_payload(cls, app, version, row: PreviewBinding) -> dict[str, Any]:
        manifest = version.manifest if isinstance(version.manifest, dict) else {}
        injections = version.injections if isinstance(version.injections, dict) else {}
        env = injections.get("env") if isinstance(injections.get("env"), dict) else {}
        health = manifest.get("health") if isinstance(manifest.get("health"), dict) else {}
        return {
            "session_id": row.session_id,
            "app_id": app.id,
            # Same fields ``AppStateService._deploy_payload`` sends, because the
            # container gets the same environment contract (contracts-runtime-
            # manager §5). A preview handed a partial environment is not a trial
            # of the release: an app never told ``BISHENG_APP_DB_URL`` exits on
            # start-up, and the approver reads that as a broken release.
            "slug": app.slug,
            "version_id": version.id,
            "version_no": version.version_no,
            "image_ref": version.image_ref or "",
            "tier": await cls._tier_payload(version.tier_id),
            "port": int(manifest.get("port") or 8080),
            # The manager reclaims the container on its own once this passes —
            # the platform has no timer of its own (see the module docstring).
            "expires_at": int(row.expires_at.replace(tzinfo=UTC).timestamp()),
            "env": {str(key): str(value) for key, value in env.items()},
            "health": {**_DEFAULT_HEALTH, **health},
            "platform_api_base": settings.app_runtime.entry_base_url or "",
            # The app rebuilds absolute URLs from this, and under a preview it
            # is not ``/apps/{slug}``: the same source has to work at both entry
            # points, which is exactly what ``base_path`` / ``X-Forwarded-Prefix``
            # are for (F054 D5.2).
            "base_path": preview_entry_path(row.session_id),
            # Same reason as every other field here: the trial must behave the
            # way the release will. A preview given a narrower outbound
            # whitelist than the release gets fails its own API calls, and the
            # approver reads that as a broken version (F054 AC-16).
            "egress_domains": egress_domains_of(manifest),
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
