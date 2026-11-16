"""Minimal WeCom (企业微信) API client for the self-hosted SSO flow (F120).

Only the three calls a login needs: the application ``access_token``,
``code -> userid`` and the member detail. The org-sync provider
(``org_sync/domain/providers/wecom.py``) keeps its own, heavier client — paging
the whole directory needs rate-limit backoff and a Redlock — and dragging that
into the login hot path would buy nothing.

The token cache key is deliberately the same one the org-sync provider uses
(``org_sync:wecom:token:{config_id}``) so a login and a directory sync on the
same configuration reuse one token instead of each fetching its own.

Interface shapes (verify against a real tenant before shipping, see
``features/v3.0.1/120-wecom-sso/design.md`` §2):

- authorize (in-app): ``https://open.weixin.qq.com/connect/oauth2/authorize``
- authorize (PC scan): ``https://login.work.weixin.qq.com/wwlogin/sso/login``
- ``GET /cgi-bin/gettoken``
- ``GET /cgi-bin/auth/getuserinfo?access_token=&code=``
- ``GET /cgi-bin/user/get?access_token=&userid=``
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx
from loguru import logger

from bisheng.common.errcode.sso_sync import (
    WeComSsoCodeInvalidError,
    WeComSsoUpstreamError,
)
from bisheng.core.cache.redis_manager import get_redis_client

WECOM_API_BASE = "https://qyapi.weixin.qq.com"
WECOM_INAPP_AUTHORIZE_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"
WECOM_QR_AUTHORIZE_URL = "https://login.work.weixin.qq.com/wwlogin/sso/login"

TOKEN_KEY_FMT = "org_sync:wecom:token:{config_id}"
TOKEN_TTL_BUFFER = 300  # refresh 5 min before WeCom's own expiry

#: ``auth/getuserinfo`` errcode for an unusable code.
_ERRCODE_BAD_CODE = 40029
#: Credential / permission problems: retrying or degrading would hide a broken
#: configuration, so they surface as 19334.
_ERRCODE_AUTH_FAIL = {40001, 40013, 42009, 60011, 48002}


@dataclass(frozen=True)
class WeComMember:
    """The subset of a WeCom member a login needs."""

    userid: str
    name: str | None
    email: str | None
    phone: str | None
    primary_dept_id: str | None
    secondary_dept_ids: tuple[str, ...]


def build_authorize_url(
    *,
    mode: str,
    corpid: str,
    agent_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    """Return the WeCom authorization URL for ``mode`` (``silent``/``qr``)."""
    if mode == "silent":
        query = urlencode(
            {
                "appid": corpid,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "snsapi_base",
                "state": state,
                "agentid": agent_id,
            },
            quote_via=quote,
        )
        return f"{WECOM_INAPP_AUTHORIZE_URL}?{query}#wechat_redirect"
    query = urlencode(
        {
            "login_type": "CorpApp",
            "appid": corpid,
            "agentid": agent_id,
            "redirect_uri": redirect_uri,
            "state": state,
        },
        quote_via=quote,
    )
    return f"{WECOM_QR_AUTHORIZE_URL}?{query}"


class WeComOAuthClient:
    """WeCom API calls used by one login, bound to one org-sync configuration."""

    def __init__(
        self,
        *,
        corpid: str,
        corpsecret: str,
        agent_id: str,
        config_id: int | None,
        timeout: float = 10.0,
    ):
        self._corpid = corpid
        self._corpsecret = corpsecret
        self._agent_id = agent_id
        self._config_id = config_id
        self._timeout = timeout

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def corpid(self) -> str:
        return self._corpid

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------

    def _token_key(self) -> str:
        return TOKEN_KEY_FMT.format(config_id=self._config_id or "default")

    async def _cached_token(self) -> str | None:
        try:
            client = await get_redis_client()
            value = await client.async_connection.get(self._token_key())
            return value or None
        except Exception:
            # A cache miss is harmless: the token is fetched again below. This is
            # a best-effort cache, not a correctness requirement.
            logger.warning("wecom sso: token cache read failed; fetching a fresh token")
            return None

    async def _store_token(self, token: str, expires_in: int) -> None:
        ttl = max(int(expires_in) - TOKEN_TTL_BUFFER, 60)
        try:
            client = await get_redis_client()
            await client.async_connection.set(self._token_key(), token, ex=ttl)
        except Exception:
            # Same reasoning as above: the login still works without the cache.
            logger.warning("wecom sso: token cache write failed")

    async def _access_token(self, http: httpx.AsyncClient) -> str:
        cached = await self._cached_token()
        if cached:
            return cached
        try:
            resp = await http.get(
                f"{WECOM_API_BASE}/cgi-bin/gettoken",
                params={"corpid": self._corpid, "corpsecret": self._corpsecret},
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("wecom sso: gettoken transport failure: {!r}", exc)
            raise WeComSsoUpstreamError(detail="gettoken transport failure") from exc
        errcode = int(data.get("errcode", 0) or 0)
        if errcode != 0:
            logger.warning(
                "wecom sso: gettoken rejected errcode={} errmsg={}",
                errcode,
                data.get("errmsg"),
            )
            raise WeComSsoUpstreamError(detail=f"gettoken errcode={errcode}")
        token = data.get("access_token")
        if not token:
            raise WeComSsoUpstreamError(detail="gettoken returned no access_token")
        await self._store_token(token, int(data.get("expires_in", 7200) or 7200))
        return token

    # ------------------------------------------------------------------
    # Login calls
    # ------------------------------------------------------------------

    async def exchange_code(self, code: str) -> str:
        """Turn an authorization code into the member's WeCom userid."""
        if not code:
            raise WeComSsoCodeInvalidError()
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            token = await self._access_token(http)
            try:
                resp = await http.get(
                    f"{WECOM_API_BASE}/cgi-bin/auth/getuserinfo",
                    params={"access_token": token, "code": code},
                )
                data = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("wecom sso: getuserinfo transport failure: {!r}", exc)
                raise WeComSsoUpstreamError(detail="getuserinfo transport failure") from exc
        errcode = int(data.get("errcode", 0) or 0)
        if errcode == _ERRCODE_BAD_CODE:
            raise WeComSsoCodeInvalidError()
        if errcode != 0:
            logger.warning(
                "wecom sso: getuserinfo rejected errcode={} errmsg={}",
                errcode,
                data.get("errmsg"),
            )
            raise WeComSsoUpstreamError(detail=f"getuserinfo errcode={errcode}")
        userid = (data.get("userid") or "").strip()
        if not userid:
            # WeCom returns only ``openid`` when the member is outside the
            # app's visible range. That is a configuration problem, not a bad
            # code, so it must not be reported as "please scan again" forever.
            logger.warning(
                "wecom sso: getuserinfo returned no userid (member outside app visible scope?), keys={}",
                sorted(data.keys()),
            )
            raise WeComSsoUpstreamError(detail="member not in the app's visible scope")
        return userid

    async def fetch_member(self, userid: str) -> WeComMember | None:
        """Read the member's profile + departments.

        Returns ``None`` when WeCom refuses the contact read (missing 通讯录
        permission, member outside scope, transient error). The caller degrades
        to a department-less login instead of failing it — see spec AC-08.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            token = await self._access_token(http)
            try:
                resp = await http.get(
                    f"{WECOM_API_BASE}/cgi-bin/user/get",
                    params={"access_token": token, "userid": userid},
                )
                data = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("wecom sso: user/get transport failure: {!r}", exc)
                return None
        errcode = int(data.get("errcode", 0) or 0)
        if errcode != 0:
            logger.warning(
                "wecom sso: user/get failed errcode={} errmsg={} userid={}",
                errcode,
                data.get("errmsg"),
                userid,
            )
            if errcode in _ERRCODE_AUTH_FAIL:
                # Broken credentials must not be masked as "no department": the
                # user would silently land in the guest department forever.
                raise WeComSsoUpstreamError(detail=f"user/get errcode={errcode}")
            return None

        departments = [str(d) for d in (data.get("department") or [])]
        main_dept = data.get("main_department")
        if main_dept is not None:
            primary = str(main_dept)
            secondaries = tuple(d for d in departments if d != primary)
        elif departments:
            primary, secondaries = departments[0], tuple(departments[1:])
        else:
            primary, secondaries = None, ()
        return WeComMember(
            userid=str(data.get("userid") or userid).strip(),
            name=(data.get("name") or "").strip() or None,
            email=(data.get("email") or "").strip() or None,
            phone=(data.get("mobile") or "").strip() or None,
            primary_dept_id=primary,
            secondary_dept_ids=secondaries,
        )
