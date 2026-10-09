"""Browser self-service uses the authenticated identity, never an admin target."""

from bisheng.common.errcode.dsh import DshUserDisabledError
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.services.profile import profile_scope


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
        limits, amounts = usage.get("model_limits") or {}, usage.get("models") or {}
        return {
            "month": usage["month"],
            "billing_timezone": self.runtime.settings.billing_timezone,
            "source": usage["source"],
            "as_of": usage["as_of"],
            "unknown_pending": usage["unknown_pending"],
            "models": [
                {
                    "model_id": model["id"],
                    "name": model["name"],
                    "limit": limits.get(str(model["id"])),
                    "used": amounts.get(str(model["id"])),
                    "remaining": max(limits[str(model["id"])] - amounts[str(model["id"])], 0)
                    if str(model["id"]) in limits and str(model["id"]) in amounts
                    else None,
                }
                for model in candidates
            ],
        }
