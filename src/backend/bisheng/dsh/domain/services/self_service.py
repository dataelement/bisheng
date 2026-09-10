"""Browser self-service uses the authenticated identity, never an admin target."""

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError, DshUserDisabledError
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.schemas.admin import SessionItem
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

    async def sessions(self, user, *, cursor=None, limit=20):
        await self.identity(user)
        result = await self.runtime.gateway.request(
            "self_sessions",
            {
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.user_id),
                "cursor": cursor,
                "limit": limit,
            },
        )
        try:
            if set(result) != {"items", "next_cursor", "has_more"} or type(result["has_more"]) is not bool:
                raise ValueError("Invalid session page")
            if not isinstance(result["items"], list) or len(result["items"]) > limit:
                raise ValueError("Invalid session page length")
            if result["next_cursor"] is not None and not isinstance(result["next_cursor"], str):
                raise ValueError("Invalid cursor")
            if result["has_more"] and not result["next_cursor"]:
                raise ValueError("Missing cursor")
            return {
                **result,
                "items": [SessionItem.model_validate(row).model_dump(exclude={"seat_id"}) for row in result["items"]],
            }
        except (ValueError, TypeError, KeyError) as exc:
            raise DshAuthorizationUnavailableError() from exc

    async def revoke(self, user, session_id):
        await self.identity(user)
        result = await self.runtime.gateway.request(
            "self_revoke",
            {
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.user_id),
                "session_id": session_id,
            },
        )
        if result != {"session_id": session_id, "state": "REVOKED"}:
            raise DshAuthorizationUnavailableError()
        return result

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
