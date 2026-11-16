"""Self-hosted WeCom (企业微信) SSO orchestration (F120).

Three steps, all entry points of ``/api/v1/user/wecom/*``:

- ``availability`` decides whether the login entry exists at all
  (gateway absent + exactly one enabled WeCom org-sync config) and which
  authorization flavour fits the browser.
- ``authorize`` stores a one-time ``state`` in Redis and returns the URL the
  browser must be sent to.
- ``callback`` consumes the state, turns the code into a WeCom userid, then
  delegates every account/department/tenant decision to the existing
  ``LoginSyncService`` (INV-47) before handing the JWT back to the caller.

Credentials come from the org-sync configuration only (INV-45); this module
never reads or defines a second set. Design: ``features/v3.0.1/120-wecom-sso``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from loguru import logger

from bisheng.common.errcode.sso_sync import (
    WeComSsoConfigAmbiguousError,
    WeComSsoNotConfiguredError,
    WeComSsoUpstreamError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.audit_log import (
    AuditLog,
    AuditLogDao,
    EventType,
    ObjectType,
    SystemId,
)
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.database.models.user_group import UserGroupDao
from bisheng.org_sync.domain.models.org_sync import (
    OrgSyncConfigDao,
    decrypt_auth_config,
)
from bisheng.sso_sync.domain.constants import WECOM_SOURCE
from bisheng.sso_sync.domain.schemas.payloads import (
    LoginSyncRequest,
    UserAttrsDTO,
)
from bisheng.sso_sync.domain.services.login_sync_service import LoginSyncService
from bisheng.sso_sync.domain.services.org_sync_log_writer import (
    OrgSyncLogBuffer,
    flush_log,
)
from bisheng.sso_sync.domain.services.wecom_login_state import WeComLoginStateStore
from bisheng.sso_sync.domain.services.wecom_oauth_client import (
    WeComMember,
    WeComOAuthClient,
    build_authorize_url,
)

WECOM_PROVIDER = "wecom"
MODE_SILENT = "silent"
MODE_QR = "qr"
#: WeCom's in-app browser puts ``wxwork`` in the UA.
_WECOM_UA_MARK = "wxwork"
LOGIN_PATH = "/api/v1/user/wecom/authorize"
CALLBACK_PATH = "/api/v1/user/wecom/callback"


@dataclass(frozen=True)
class WeComLoginConfig:
    """The one enabled WeCom org-sync config, decrypted."""

    config_id: int
    corpid: str
    corpsecret: str
    agent_id: str

    def client(self) -> WeComOAuthClient:
        return WeComOAuthClient(
            corpid=self.corpid,
            corpsecret=self.corpsecret,
            agent_id=self.agent_id,
            config_id=self.config_id,
            timeout=float(settings.sso_sync.wecom.request_timeout_seconds),
        )


class WeComLoginService:
    """Entry points for the self-hosted WeCom login."""

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @classmethod
    async def _load_config(cls) -> WeComLoginConfig:
        """Resolve the single enabled WeCom org-sync configuration.

        Login runs before any tenant is known, so only the root tenant's
        configuration is considered: a WeCom app belongs to the whole
        deployment, not to a leaf tenant.
        """
        with bypass_tenant_filter():
            configs = await OrgSyncConfigDao.aget_list(tenant_id=ROOT_TENANT_ID, status="active")
        wecom_configs = [c for c in configs if c.provider == WECOM_PROVIDER]
        if not wecom_configs:
            raise WeComSsoNotConfiguredError()
        if len(wecom_configs) > 1:
            raise WeComSsoConfigAmbiguousError()
        config = wecom_configs[0]
        auth = decrypt_auth_config(config.auth_config)
        corpid = (auth.get("corpid") or "").strip()
        corpsecret = (auth.get("corpsecret") or "").strip()
        agent_id = str(auth.get("agent_id") or "").strip()
        if not (corpid and corpsecret and agent_id):
            logger.warning(
                "wecom sso: org-sync config {} is missing credentials",
                config.id,
            )
            raise WeComSsoNotConfiguredError()
        return WeComLoginConfig(
            config_id=int(config.id or 0),
            corpid=corpid,
            corpsecret=corpsecret,
            agent_id=agent_id,
        )

    @staticmethod
    def resolve_mode(user_agent: str | None) -> str:
        """In-app browser gets the silent flow; everything else scans a code."""
        return MODE_SILENT if _WECOM_UA_MARK in (user_agent or "").lower() else MODE_QR

    # ------------------------------------------------------------------
    # availability / authorize
    # ------------------------------------------------------------------

    @classmethod
    async def availability(cls, user_agent: str | None) -> dict:
        """What the login page needs to decide whether to render the entry."""
        disabled = {"enabled": False, "mode": None, "login_path": None}
        if settings.get_system_login_method().bisheng_pro:
            # The commercial gateway owns WeCom login there (AC-24).
            return disabled
        try:
            await cls._load_config()
        except (WeComSsoNotConfiguredError, WeComSsoConfigAmbiguousError) as exc:
            logger.info("wecom sso: entry disabled — {}", exc.message)
            return disabled
        return {
            "enabled": True,
            "mode": cls.resolve_mode(user_agent),
            "login_path": LOGIN_PATH,
        }

    @classmethod
    async def authorize(
        cls,
        *,
        return_to: str | None,
        force_mode: str | None,
        user_agent: str | None,
        public_origin: str,
        callback_url: str,
    ) -> str:
        """Persist the one-time state and return the WeCom authorization URL."""
        config = await cls._load_config()
        mode = cls.resolve_mode(user_agent)
        if force_mode in (MODE_SILENT, MODE_QR):
            mode = force_mode
        target = cls._safe_return_to(return_to, public_origin)
        state = WeComLoginStateStore.new_state()
        await WeComLoginStateStore.put(
            state,
            mode=mode,
            return_to=target,
            ttl=int(settings.sso_sync.wecom.state_ttl_seconds),
        )
        return build_authorize_url(
            mode=mode,
            corpid=config.corpid,
            agent_id=config.agent_id,
            redirect_uri=callback_url,
            state=state,
        )

    @staticmethod
    def _safe_return_to(return_to: str | None, public_origin: str) -> str:
        """Only same-origin (or explicitly allowed) absolute URLs are accepted.

        Anything else falls back to the deployment root: the callback must never
        become an open redirect. ``allowed_return_origins`` covers deployments
        where the SPA is served from a different host than the API.
        """
        fallback = f"{public_origin.rstrip('/')}/"
        if not return_to:
            return fallback
        parsed = urlparse(return_to)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            logger.warning("wecom sso: refusing non-absolute return_to {!r}", return_to)
            return fallback
        origin = f"{parsed.scheme}://{parsed.netloc}"
        allowed = {o.rstrip("/") for o in (settings.sso_sync.wecom.allowed_return_origins or [])}
        allowed.add(public_origin.rstrip("/"))
        if origin not in allowed:
            logger.warning(
                "wecom sso: refusing foreign return_to origin {} (allowed: {})",
                origin,
                sorted(allowed),
            )
            return fallback
        return return_to

    # ------------------------------------------------------------------
    # callback
    # ------------------------------------------------------------------

    @classmethod
    async def callback(
        cls,
        *,
        code: str,
        state: str,
        request_ip: str,
    ) -> tuple[str, str]:
        """Complete the login. Returns ``(return_to, access_token)``.

        Every failure that has a known target URL re-raises so the endpoint can
        turn it into ``?wecom_error=<code>``; the state itself decides where the
        user goes back to, and is consumed before any WeCom call so a replayed
        callback cannot re-run the login.
        """
        login_state = await WeComLoginStateStore.consume(state)
        config = await cls._load_config()
        client = config.client()

        userid = await client.exchange_code(code)
        member = await client.fetch_member(userid)

        payload = await cls._build_payload(userid, member)
        result = await LoginSyncService.execute(
            payload,
            request_ip=request_ip,
            row_source=WECOM_SOURCE,
            bootstrap_first_user_admin=True,
        )
        if not result.token:
            # A disabled account short-circuits inside LoginSyncService without
            # issuing a token; surface it as an upstream-style refusal so the
            # browser does not land on a logged-out page with no explanation.
            raise WeComSsoUpstreamError(detail="account disabled on the platform")
        await cls._write_login_audit(
            user_id=result.user_id,
            user_name=payload.user_attrs.name or userid,
            request_ip=request_ip,
            userid=userid,
        )
        await cls._write_org_sync_log()
        logger.info(
            "wecom sso: login ok user_id={} userid={} tenant={}",
            result.user_id,
            userid,
            result.leaf_tenant_id,
        )
        return login_state.return_to, result.token

    @classmethod
    async def _build_payload(cls, userid: str, member: WeComMember | None) -> LoginSyncRequest:
        """Assemble the LoginSync payload, degrading when a department is unknown.

        A department missing from the platform means the org chart has not been
        synced yet (spec AC-08): the login still proceeds and the user lands in
        the guest department, with a WARNING naming the missing id. Probing is
        read-only on purpose — swallowing ``SsoDeptParentMissingError`` from the
        login-sync step would also hide genuine concurrent-deletion failures
        (design §5 item 2).

        ``account_disabled`` is deliberately never set: that field makes the
        login-sync path re-enable a disabled account (design §5 item 1).
        """
        if member is None:
            logger.warning(
                "wecom sso: no member detail for userid={}; logging in without department",
                userid,
            )
            return LoginSyncRequest(
                source=WECOM_SOURCE,
                external_user_id=userid,
                ts=int(time.time()),
            )

        wanted = [d for d in (member.primary_dept_id, *member.secondary_dept_ids) if d]
        known = await cls._existing_departments(wanted)

        primary = member.primary_dept_id if member.primary_dept_id in known else None
        secondaries = [d for d in member.secondary_dept_ids if d in known]
        if member.primary_dept_id and primary is None:
            logger.warning(
                "wecom sso dept fallback: userid={} missing_department={}; org chart may not be synced yet",
                userid,
                member.primary_dept_id,
            )
        return LoginSyncRequest(
            source=WECOM_SOURCE,
            external_user_id=userid,
            primary_dept_external_id=primary,
            secondary_dept_external_ids=secondaries,
            user_attrs=UserAttrsDTO(
                name=member.name,
                email=member.email,
                phone=member.phone,
            ),
            # The schema requires the source timestamp; a login carries no
            # upstream revision, so "now" is the honest value (the ts guard only
            # gates bulk department pushes, which do not run here).
            ts=int(time.time()),
        )

    @staticmethod
    async def _existing_departments(external_ids: list[str]) -> set[str]:
        """Which of these WeCom department ids are already on the platform."""
        if not external_ids:
            return set()
        found: set[str] = set()
        with bypass_tenant_filter():
            for external_id in dict.fromkeys(external_ids):
                dept = await DepartmentDao.aget_by_source_external_id(WECOM_SOURCE, external_id)
                if dept is not None and int(getattr(dept, "is_deleted", 0) or 0) != 1:
                    found.add(external_id)
        return found

    # ------------------------------------------------------------------
    # Side effects
    # ------------------------------------------------------------------

    @staticmethod
    async def _write_login_audit(*, user_id: int, user_name: str, request_ip: str, userid: str) -> None:
        """Mirror the password-login audit row (``AuditLogService.user_login``).

        Written through the DAO rather than the API-layer service so the domain
        layer stays free of API imports — the same way
        ``LoginSyncService._upsert_user`` writes its migration audit row.
        """
        with bypass_tenant_filter():
            groups = UserGroupDao.get_user_group(user_id)
        group_ids = [one.group_id for one in groups]
        await AuditLogDao.ainsert_audit_logs(
            [
                AuditLog(
                    operator_id=user_id,
                    operator_name=user_name,
                    group_ids=group_ids,
                    system_id=SystemId.SYSTEM.value,
                    event_type=EventType.USER_LOGIN.value,
                    object_type=ObjectType.NONE.value,
                    object_id="",
                    object_name="",
                    ip_address=request_ip,
                    note=f"wecom_sso userid={userid}",
                )
            ]
        )

    @staticmethod
    async def _write_org_sync_log() -> None:
        """One ``sso_realtime`` row, matching the Gateway login-sync endpoint."""
        buffer = OrgSyncLogBuffer()
        buffer.member_updated += 1
        await flush_log(buffer, trigger_type="sso_realtime")


def build_callback_url(public_origin: str) -> str:
    """Absolute WeCom redirect target; must match the WeCom app's trusted domain."""
    return f"{public_origin.rstrip('/')}{CALLBACK_PATH}"


def quote_return_to(return_to: str) -> str:
    return quote(return_to, safe="")
