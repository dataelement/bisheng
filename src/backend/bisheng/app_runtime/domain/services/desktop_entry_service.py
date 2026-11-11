"""Revalidate an app-scoped Desktop session before every entry verdict."""

from bisheng.app_runtime.domain.repositories.desktop_app_repository import DesktopAppRepository
from bisheng.app_runtime.domain.repositories.desktop_app_sessions import desktop_app_sessions
from bisheng.app_runtime.domain.services.desktop_apps_service import DesktopAppsService
from bisheng.app_runtime.domain.services.entry_authz_service import authorize_entry
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError
from bisheng.dsh.domain.services.access import DshPrincipal, principal_scope


async def redeem_desktop_ticket(ticket, slug, runtime):
    sessions = await desktop_app_sessions()
    token = await sessions.redeem(ticket, slug)
    record = await sessions.resolve(token, slug)
    principal = DshPrincipal.model_validate(record["principal"])
    service = DesktopAppsService(runtime, DesktopAppRepository(), sessions)
    await service.require(principal, record["app_id"], "use")
    return {"session": token, "max_age": 3600}


async def authorize_desktop_entry(*, slug, access_token, runtime, request_id="", client_ip=None):
    try:
        sessions = await desktop_app_sessions()
        record = await sessions.resolve(access_token, slug)
        principal = DshPrincipal.model_validate(record["principal"])
        service = DesktopAppsService(runtime, DesktopAppRepository(), sessions)
        with principal_scope(principal):
            actor = await service.actor(principal)
            result = await authorize_entry(
                slug=slug, access_token=None, desktop_actor=actor, request_id=request_id, client_ip=client_ip
            )
            if result.get("decision") == "allow" and result.get("app_id") != record["app_id"]:
                return {"decision": "forbidden", "reason": "application_identity_changed"}
            return result
    except DshAuthorizationUnavailableError:
        return {"decision": "unavailable", "reason": "desktop_session_unavailable"}
    except BaseErrorCode:
        return {"decision": "login", "reason": "desktop_session_invalid"}
