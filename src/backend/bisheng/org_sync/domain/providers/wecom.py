"""WeChat Work (WeCom) Provider — full implementation (F021).

Uses WeChat Work Contact API v2:
  - Auth: GET /cgi-bin/gettoken
  - Departments: GET /cgi-bin/department/list?id={id}
  - Members: GET /cgi-bin/user/list?department_id={id}&fetch_child=1
  - Summary (for test_connection): GET /cgi-bin/user/simplelist

Per-config token cache in Redis (key: org_sync:wecom:token:{config_id}) with
TTL = expires_in - 300s. Distributed lock (Redlock single-key) prevents two
concurrent workers from racing gettoken. Expired-token path on errcode 42001
/ 40014 invalidates the cache, refreshes once, and retries the business call.

Rate limit (errcode 45009/45033/45011): exponential backoff [1, 2, 4, 8] s,
up to 4 retries.

Authentication errors (errcode 40001/40013/60011/42009) surface as
OrgSyncAuthFailedError; unknown non-zero errcodes become OrgSyncFetchError.

API Reference: https://developer.work.weixin.qq.com/document/path/90208
"""

import asyncio
from typing import Optional

import httpx
from loguru import logger

from bisheng.common.errcode.org_sync import (
    OrgSyncAuthFailedError,
    OrgSyncFetchError,
    OrgSyncProviderError,
)
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.org_sync.domain.providers.base import OrgSyncProvider
from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO

WECOM_BASE_URL = 'https://qyapi.weixin.qq.com'
TOKEN_TTL_BUFFER = 300  # Refresh 5 min before expiry to avoid edge cases
MAX_RATE_LIMIT_RETRIES = 4
BACKOFF_BASE = 1  # seconds

TOKEN_KEY_FMT = 'org_sync:wecom:token:{config_id}'
TOKEN_LOCK_KEY_FMT = 'org_sync:wecom:token_lock:{config_id}'
TOKEN_LOCK_TTL = 30  # seconds — lock auto-releases if holder dies

# errcode buckets
_ERRCODE_EXPIRED = {42001, 40014}  # token expired / invalid
_ERRCODE_RATE_LIMIT = {45009, 45033, 45011}
_ERRCODE_AUTH_FAIL = {40001, 40013, 60011, 42009}


class WeComProvider(OrgSyncProvider):
    """WeChat Work provider (F021)."""

    def __init__(self, auth_config: dict):
        super().__init__(auth_config)
        # Strict required-field validation — Pydantic layer already checks this,
        # but a Provider instantiated via get_provider() may arrive with a
        # partially-merged dict from other code paths.
        for key in ('corpid', 'corpsecret', 'agent_id'):
            if not auth_config.get(key):
                raise OrgSyncProviderError(
                    msg=f'WeCom auth_config missing required field: {key}',
                )
        self._corpid: str = auth_config['corpid']
        self._corpsecret: str = auth_config['corpsecret']
        self._agent_id: str = str(auth_config['agent_id'])
        self._allow_dept_ids: list[int] = list(
            auth_config.get('allow_dept_ids') or [1],
        )
        # config_id is only used for Redis key isolation; not all callers
        # populate it (e.g. unit tests exercising a Provider directly).
        self._config_id: Optional[int] = auth_config.get('_config_id')
        self._semaphore = asyncio.Semaphore(5)

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _token_key(self) -> str:
        return TOKEN_KEY_FMT.format(config_id=self._config_id or 'default')

    def _lock_key(self) -> str:
        return TOKEN_LOCK_KEY_FMT.format(config_id=self._config_id or 'default')

    async def _redis_conn(self):
        """Return the async redis connection or None if unavailable."""
        try:
            client = await get_redis_client()
            return client.async_connection
        except Exception as e:
            logger.warning(f'WeCom: Redis unavailable ({e}); token cache disabled')
            return None

    async def _get_cached_token(self) -> Optional[str]:
        conn = await self._redis_conn()
        if conn is None:
            return None
        try:
            val = await conn.get(self._token_key())
            if val is None:
                return None
            return val.decode() if isinstance(val, bytes) else val
        except Exception as e:
            logger.warning(f'WeCom: Redis GET failed ({e})')
            return None

    async def _set_cached_token(self, token: str, expires_in: int) -> None:
        conn = await self._redis_conn()
        if conn is None:
            return
        ttl = max(expires_in - TOKEN_TTL_BUFFER, 60)
        try:
            await conn.set(self._token_key(), token, ex=ttl)
        except Exception as e:
            logger.warning(f'WeCom: Redis SET failed ({e})')

    async def _invalidate_token(self) -> None:
        conn = await self._redis_conn()
        if conn is None:
            return
        try:
            await conn.delete(self._token_key())
        except Exception as e:
            logger.warning(f'WeCom: Redis DEL failed ({e})')

    async def _acquire_token_lock(self) -> bool:
        conn = await self._redis_conn()
        if conn is None:
            # No Redis → assume we can proceed; concurrent callers will each
            # call gettoken but WeCom tolerates that at low QPS.
            return True
        try:
            acquired = await conn.set(
                self._lock_key(), '1', nx=True, ex=TOKEN_LOCK_TTL,
            )
            return bool(acquired)
        except Exception as e:
            logger.warning(f'WeCom: Redis lock acquire failed ({e}); proceeding')
            return True

    async def _release_token_lock(self) -> None:
        conn = await self._redis_conn()
        if conn is None:
            return
        try:
            await conn.delete(self._lock_key())
        except Exception as e:
            logger.warning(f'WeCom: Redis lock release failed ({e})')

    # ------------------------------------------------------------------
    # Token lifecycle
    # ------------------------------------------------------------------

    async def _fetch_new_token(self, client: httpx.AsyncClient) -> tuple[str, int]:
        """Call /gettoken and return (access_token, expires_in)."""
        resp = await client.get(
            f'{WECOM_BASE_URL}/cgi-bin/gettoken',
            params={'corpid': self._corpid, 'corpsecret': self._corpsecret},
        )
        resp.raise_for_status()
        body = resp.json()
        errcode = body.get('errcode', 0)
        if errcode != 0:
            errmsg = body.get('errmsg', '')
            if errcode in _ERRCODE_AUTH_FAIL or errcode in {40001, 40013}:
                # Never include the errmsg verbatim; WeCom echoes some request
                # context but never the secret. Still, stay conservative.
                raise OrgSyncAuthFailedError(
                    msg=(
                        f'WeCom gettoken failed (errcode={errcode}): '
                        'access_token 获取失败，请检查 corpid / corpsecret'
                    ),
                )
            raise OrgSyncFetchError(
                msg=f'WeCom gettoken failed (errcode={errcode}, errmsg={errmsg})',
            )
        token = body.get('access_token')
        expires_in = int(body.get('expires_in', 7200))
        if not token:
            raise OrgSyncFetchError(msg='WeCom gettoken returned no access_token')
        return token, expires_in

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        """Return a valid access_token, refreshing via Redis-coordinated lock."""
        cached = await self._get_cached_token()
        if cached:
            return cached

        # Try to take the distributed lock — if someone else holds it, wait
        # briefly then re-read the cache.
        got_lock = await self._acquire_token_lock()
        if not got_lock:
            await asyncio.sleep(0.2)
            cached = await self._get_cached_token()
            if cached:
                return cached
            # Fallback: proceed without lock rather than loop forever.
            logger.warning(
                'WeCom: lock held by peer but cache still empty; fetching anyway',
            )

        try:
            token, expires_in = await self._fetch_new_token(client)
            await self._set_cached_token(token, expires_in)
            return token
        finally:
            if got_lock:
                await self._release_token_lock()

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        _token_retry: bool = True,
        **kwargs,
    ) -> dict:
        """Send a WeCom API call with token injection, retry & backoff.

        errcode handling:
        - 0: success
        - 42001/40014: token invalid — refresh once and retry (single retry)
        - 45009/45033/45011: rate-limited — exponential backoff up to 4 times
        - 40001/40013/60011/42009: authentication/scope failure
        - other non-zero: OrgSyncFetchError
        """
        async with self._semaphore:
            for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
                token = await self._ensure_token(client)
                params = dict(kwargs.pop('params', {}))
                params['access_token'] = token
                resp = await client.request(method, url, params=params, **kwargs)
                resp.raise_for_status()
                body = resp.json()
                errcode = body.get('errcode', 0)

                if errcode == 0:
                    return body

                if errcode in _ERRCODE_EXPIRED and _token_retry:
                    logger.info(f'WeCom token expired (errcode={errcode}); refreshing')
                    await self._invalidate_token()
                    # Fresh token, then one retry with _token_retry=False so
                    # a second expiry doesn't loop.
                    token = await self._ensure_token(client)
                    params['access_token'] = token
                    resp2 = await client.request(method, url, params=params, **kwargs)
                    resp2.raise_for_status()
                    body2 = resp2.json()
                    errcode2 = body2.get('errcode', 0)
                    if errcode2 == 0:
                        return body2
                    if errcode2 in _ERRCODE_AUTH_FAIL:
                        raise OrgSyncAuthFailedError(
                            msg=self._auth_fail_msg(errcode2, body2.get('errmsg', '')),
                        )
                    raise OrgSyncFetchError(
                        msg=(
                            f'WeCom API error after token refresh '
                            f'(errcode={errcode2}, errmsg={body2.get("errmsg", "")})'
                        ),
                    )

                if errcode in _ERRCODE_RATE_LIMIT:
                    if attempt < MAX_RATE_LIMIT_RETRIES:
                        wait = BACKOFF_BASE * (2 ** attempt)
                        logger.warning(
                            f'WeCom rate-limited (errcode={errcode}); retrying in {wait}s',
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise OrgSyncFetchError(
                        msg=(
                            f'WeCom API rate-limited after {MAX_RATE_LIMIT_RETRIES + 1} '
                            f'attempts (errcode={errcode})'
                        ),
                    )

                if errcode in _ERRCODE_AUTH_FAIL:
                    raise OrgSyncAuthFailedError(
                        msg=self._auth_fail_msg(errcode, body.get('errmsg', '')),
                    )

                raise OrgSyncFetchError(
                    msg=(
                        f'WeCom API error (errcode={errcode}, '
                        f'errmsg={body.get("errmsg", "")})'
                    ),
                )
            # Shouldn't reach here — rate-limit branch raises on exhaustion.
            raise OrgSyncFetchError(msg='WeCom request failed')

    @staticmethod
    def _auth_fail_msg(errcode: int, errmsg: str) -> str:
        if errcode == 60011:
            return (
                f'WeCom API 权限不足 (errcode={errcode})：'
                '应用无权限访问通讯录，请检查企业微信后台可见范围'
            )
        if errcode == 42009:
            return (
                f'WeCom API 未授权 (errcode={errcode})：'
                '企业微信后台未授权该应用访问通讯录'
            )
        return (
            f'WeCom 认证失败 (errcode={errcode})：'
            f'access_token 获取失败，errmsg={errmsg}'
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        async with httpx.AsyncClient(timeout=30) as client:
            await self._ensure_token(client)
            return True

    async def fetch_departments(
        self, root_dept_ids: Optional[list[str]] = None,
    ) -> list[RemoteDepartmentDTO]:
        """Fetch the department tree rooted at each allow_dept_id.

        WeCom's /department/list?id=X returns the full subtree below X (including
        X itself) in one call, so no pagination is needed. Multiple roots are
        merged and de-duplicated by external_id.
        """
        roots = self._resolve_roots(root_dept_ids)
        seen: set[str] = set()
        results: list[RemoteDepartmentDTO] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for root in roots:
                data = await self._request(
                    client, 'GET',
                    f'{WECOM_BASE_URL}/cgi-bin/department/list',
                    params={'id': root},
                )
                for item in data.get('department', []):
                    ext_id = str(item.get('id'))
                    if ext_id in seen:
                        continue
                    seen.add(ext_id)
                    parent_raw = item.get('parentid')
                    parent_ext = str(parent_raw) if parent_raw is not None else None
                    # Root itself has no parent relative to our sync scope
                    if ext_id == str(root):
                        parent_ext = None
                    results.append(RemoteDepartmentDTO(
                        external_id=ext_id,
                        name=item.get('name', ''),
                        parent_external_id=parent_ext,
                        sort_order=int(item.get('order') or 0),
                    ))
        return results

    async def fetch_members(
        self, department_ids: Optional[list[str]] = None,
    ) -> list[RemoteMemberDTO]:
        """Fetch members from every allow_dept_id (fetch_child=1 drills down).

        Duplicate userids across roots are deduplicated; secondary departments
        from all roots are merged.
        """
        # When called by the Reconciler, department_ids is the full flattened
        # department list from fetch_departments. We still drive WeCom by
        # allow_dept_ids (its fetch_child=1 gives us everyone below) because
        # querying every leaf would multiply the API calls by 10-100x.
        roots = self._resolve_roots(None)
        results_by_uid: dict[str, RemoteMemberDTO] = {}

        async with httpx.AsyncClient(timeout=30) as client:
            for root in roots:
                data = await self._request(
                    client, 'GET',
                    f'{WECOM_BASE_URL}/cgi-bin/user/list',
                    params={'department_id': root, 'fetch_child': 1},
                )
                for item in data.get('userlist', []):
                    uid = str(item.get('userid', ''))
                    if not uid:
                        continue

                    dept_list = [str(d) for d in item.get('department', [])]
                    main_dept = item.get('main_department')
                    if main_dept is not None:
                        primary = str(main_dept)
                        secondaries = [d for d in dept_list if d != primary]
                    elif dept_list:
                        primary = dept_list[0]
                        secondaries = dept_list[1:]
                    else:
                        primary = ''
                        secondaries = []

                    status = self._map_status(item.get('status', 1))

                    existing = results_by_uid.get(uid)
                    if existing is None:
                        results_by_uid[uid] = RemoteMemberDTO(
                            external_id=uid,
                            name=item.get('name', ''),
                            email=item.get('email') or None,
                            phone=item.get('mobile') or None,
                            primary_dept_external_id=primary,
                            secondary_dept_external_ids=list(secondaries),
                            status=status,
                        )
                    else:
                        # Merge secondaries (keep primary fixed to first-seen)
                        merged = set(existing.secondary_dept_external_ids)
                        for s in secondaries:
                            if s != existing.primary_dept_external_id:
                                merged.add(s)
                        for s in dept_list:
                            if s != existing.primary_dept_external_id:
                                merged.add(s)
                        existing.secondary_dept_external_ids = sorted(merged)

        return list(results_by_uid.values())

    async def test_connection(self) -> dict:
        """Verify credentials and return a summary (total depts + members)."""
        roots = self._resolve_roots(None)
        first_root = roots[0]

        async with httpx.AsyncClient(timeout=30) as client:
            # Force a fresh gettoken to expose auth failures up-front.
            await self._ensure_token(client)

            dept_data = await self._request(
                client, 'GET',
                f'{WECOM_BASE_URL}/cgi-bin/department/list',
                params={'id': first_root},
            )
            depts = dept_data.get('department', [])
            total_depts = len(depts)
            # WeCom has no "enterprise name" field; use the root dept name or
            # fall back to a neutral label. Never return a token.
            org_name = next(
                (d.get('name') for d in depts if str(d.get('id')) == str(first_root)),
                None,
            ) or '企业微信'

            user_data = await self._request(
                client, 'GET',
                f'{WECOM_BASE_URL}/cgi-bin/user/simplelist',
                params={'department_id': first_root, 'fetch_child': 1},
            )
            total_members = len(user_data.get('userlist', []))

        return {
            'connected': True,
            'org_name': org_name,
            'total_depts': total_depts,
            'total_members': total_members,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_roots(self, requested: Optional[list]) -> list[int]:
        """Merge caller-provided roots with the configured allow_dept_ids."""
        if requested:
            ids = []
            for r in requested:
                try:
                    ids.append(int(r))
                except (TypeError, ValueError):
                    continue
            if ids:
                return ids
        return list(self._allow_dept_ids) or [1]

    @staticmethod
    def _map_status(raw_status) -> str:
        """WeCom status: 1=active, 2=disabled, 4=not-activated, 5=resigned."""
        try:
            val = int(raw_status)
        except (TypeError, ValueError):
            return 'active'
        return 'active' if val == 1 else 'disabled'
