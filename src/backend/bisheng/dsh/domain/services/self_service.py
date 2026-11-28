"""Browser self-service uses the authenticated identity, never an admin target."""

from uuid import UUID

from bisheng.common.errcode.dsh import DshUserDisabledError
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.user.application.dsh_session import platform_call


class DshSelfService:
    def __init__(self, runtime):
        self.runtime = runtime

    async def identity(self, user):
        with profile_scope(user.tenant_id):
            identity = await CurrentIdentityRecords().get(str(user.tenant_id), str(user.user_id))
        if not identity or not identity.active or not identity.tenant_active or not identity.natural_person:
            raise DshUserDisabledError()
        return identity

    async def profile(self, user):
        from bisheng.user.domain.services.dsh_display import read_dsh_display_profiles

        identity = await self.identity(user)
        with profile_scope(user.tenant_id):
            profiles = await read_dsh_display_profiles([user.user_id])
        return {"username": identity.username, "department_name": profiles.get(user.user_id, {}).get("department_name")}

    async def usage_summary(self, user):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from bisheng.dsh.admin_runtime import read_usage_time_summary

        await self.identity(user)
        end_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        start_at = end_at.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=364)
        with profile_scope(user.tenant_id):
            return await read_usage_time_summary(user.user_id, start_at, end_at, "day")

    async def usage(self, user):
        from types import SimpleNamespace

        from bisheng.dsh.admin_runtime import build_policy_view, read_available_models, read_unknown_pending
        from bisheng.dsh.runtime import get_model_runtime, read_persisted_usage, read_policy
        from bisheng.llm.domain.services.llm import LLMService

        await self.identity(user)

        async def live_reader(user_id, month):
            service = await get_model_runtime(self.runtime)
            return await service.prepare_month(SimpleNamespace(tenant_id=user.tenant_id, user_id=user_id), month)

        with profile_scope(user.tenant_id):
            policy = await read_policy(user.user_id)
            candidates = await read_available_models(
                [item.model_id for item in policy.model_configs] if policy else [],
                LLMService.get_dsh_model_snapshot,
            )
            view = build_policy_view(
                policy_reader=read_policy,
                live_reader=live_reader,
                persisted_reader=read_persisted_usage,
                billing_timezone=self.runtime.settings.billing_timezone,
                unknown_reader=read_unknown_pending,
            )
            result = await view(user.user_id)
        usage = result["usage"]
        amounts = usage.get("models") or {}
        return {
            "month": usage["month"],
            "billing_timezone": self.runtime.settings.billing_timezone,
            "source": usage["source"],
            "as_of": usage["as_of"],
            "unknown_pending": usage["unknown_pending"],
            "limit": usage["limit"],
            "used": usage["used"],
            "remaining": usage["remaining"],
            "models": [
                {
                    "model_id": model["id"],
                    "name": model["name"],
                    "limit": usage["limit"],
                    "used": amounts.get(str(model["id"])),
                    "remaining": usage["remaining"],
                }
                for model in candidates
            ],
        }

    async def sessions(self, user, *, cursor=None, limit=20):
        await self.identity(user)
        legacy = await self.runtime.sessions.page(user.tenant_id, user.user_id, cursor=cursor, limit=limit)
        if self.runtime.platform_sessions is None:
            return legacy
        with profile_scope(user.tenant_id):
            platform = await platform_call(
                self.runtime.platform_sessions.desktop_sessions(user.user_id, cursor=cursor, limit=limit)
            )
        items = sorted(legacy["items"] + platform["items"], key=lambda row: row["session_id"])
        has_more = legacy["has_more"] or platform["has_more"] or len(items) > limit
        items = items[:limit]
        return {
            "items": items,
            "has_more": has_more,
            "next_cursor": items[-1]["session_id"] if has_more else None,
        }

    async def revoke(self, user, session_id):
        await self.identity(user)
        # The UUID endpoint canonicalizes 32-character platform IDs to hyphenated UUIDs.
        platform_id = UUID(session_id).hex
        if self.runtime.platform_sessions is not None and await platform_call(
            self.runtime.platform_sessions.revoke_desktop_session(user.user_id, user.tenant_id, platform_id)
        ):
            return {"session_id": platform_id, "state": "REVOKED"}
        return await self.runtime.sessions.revoke(user.tenant_id, user.user_id, session_id)
