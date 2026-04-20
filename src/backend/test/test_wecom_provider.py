"""F021 WeComProvider unit tests.

Uses httpx.MockTransport to stub WeCom API responses and fakeredis.aioredis
to stand in for the real Redis-backed token cache / distributed lock.

Covers AC-39 ~ AC-58 (see features/v2.5.1/021-wecom-org-sync-provider/spec.md).
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx
import pytest

from bisheng.common.errcode.org_sync import (
    OrgSyncAuthFailedError,
    OrgSyncFetchError,
    OrgSyncProviderError,
)
from bisheng.org_sync.domain.providers import wecom as wecom_mod
from bisheng.org_sync.domain.providers.wecom import (
    WECOM_BASE_URL,
    WeComProvider,
)


class _InMemoryAsyncRedis:
    """Minimal async Redis stand-in for token cache + distributed lock tests.

    Avoids the fakeredis/redis-py 7.x metaclass conflict while still covering
    get/set-with-nx-ex/delete/ttl, which is all WeComProvider needs.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[bytes, Optional[float]]] = {}

    def _is_expired(self, key: str) -> bool:
        expiry = self._store.get(key, (None, None))[1]
        if expiry is None:
            return False
        return time.monotonic() >= expiry

    async def get(self, key):
        k = key if isinstance(key, str) else key.decode()
        if k in self._store and not self._is_expired(k):
            return self._store[k][0]
        self._store.pop(k, None)
        return None

    async def set(self, key, value, nx=False, ex=None):
        k = key if isinstance(key, str) else key.decode()
        if nx and k in self._store and not self._is_expired(k):
            return None
        v = value if isinstance(value, bytes) else str(value).encode()
        expiry = time.monotonic() + ex if ex else None
        self._store[k] = (v, expiry)
        return True

    async def delete(self, *keys):
        count = 0
        for key in keys:
            k = key if isinstance(key, str) else key.decode()
            if k in self._store:
                self._store.pop(k)
                count += 1
        return count

    async def ttl(self, key):
        k = key if isinstance(key, str) else key.decode()
        if k not in self._store:
            return -2
        expiry = self._store[k][1]
        if expiry is None:
            return -1
        remaining = expiry - time.monotonic()
        return int(remaining) if remaining > 0 else -2

    async def flushall(self):
        self._store.clear()

    async def aclose(self):
        self._store.clear()


VALID_CONFIG = {
    'corpid': 'wwa04427c3f62b5769',
    'corpsecret': 'test-corpsecret-SENSITIVE',
    'agent_id': '1000017',
    '_config_id': 42,
}


# ---------------------------------------------------------------------------
# Test fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
async def fake_redis(monkeypatch):
    """Replace get_redis_client() with an in-memory stub."""
    redis = _InMemoryAsyncRedis()

    class _Stub:
        def __init__(self, conn):
            self.async_connection = conn

    async def _get():
        return _Stub(redis)

    monkeypatch.setattr(wecom_mod, 'get_redis_client', _get)
    yield redis
    await redis.flushall()


class WeComMockServer:
    """Tiny in-process MockTransport wrapper that records call history."""

    def __init__(self) -> None:
        self.token_responses: list[dict] = []
        self.dept_responses: list[dict] = []
        self.user_responses: list[dict] = []
        self.simplelist_responses: list[dict] = []
        self.calls: list[httpx.Request] = []

    def enqueue_token(self, **body):
        self.token_responses.append(body)

    def enqueue_dept(self, **body):
        self.dept_responses.append(body)

    def enqueue_user(self, **body):
        self.user_responses.append(body)

    def enqueue_simplelist(self, **body):
        self.simplelist_responses.append(body)

    def _pop_or_default(self, bucket: list[dict], default: dict) -> dict:
        return bucket.pop(0) if bucket else default

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            path = request.url.path
            if path.endswith('/cgi-bin/gettoken'):
                body = self._pop_or_default(
                    self.token_responses,
                    {
                        'errcode': 0, 'errmsg': 'ok',
                        'access_token': 'default-token',
                        'expires_in': 7200,
                    },
                )
            elif path.endswith('/cgi-bin/department/list'):
                body = self._pop_or_default(
                    self.dept_responses,
                    {'errcode': 0, 'errmsg': 'ok', 'department': []},
                )
            elif path.endswith('/cgi-bin/user/list'):
                body = self._pop_or_default(
                    self.user_responses,
                    {'errcode': 0, 'errmsg': 'ok', 'userlist': []},
                )
            elif path.endswith('/cgi-bin/user/simplelist'):
                body = self._pop_or_default(
                    self.simplelist_responses,
                    {'errcode': 0, 'errmsg': 'ok', 'userlist': []},
                )
            else:
                body = {'errcode': 999, 'errmsg': f'unmocked path: {path}'}
            return httpx.Response(200, json=body)
        return httpx.MockTransport(handler)

    def access_tokens_sent(self) -> list[Optional[str]]:
        tokens = []
        for req in self.calls:
            tokens.append(req.url.params.get('access_token'))
        return tokens

    def business_call_count(self, path_suffix: str) -> int:
        return sum(1 for req in self.calls if req.url.path.endswith(path_suffix))


@pytest.fixture()
def mock_server():
    return WeComMockServer()


@pytest.fixture()
def patched_client(monkeypatch, mock_server):
    """Monkeypatch httpx.AsyncClient so the provider uses our MockTransport.

    WeComProvider opens its own AsyncClient inside each public method; we
    inject the mock transport by overriding the class default.
    """
    transport = mock_server.transport()
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault('transport', transport)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, '__init__', patched_init)
    yield mock_server


async def _provider(config_overrides: Optional[dict] = None) -> WeComProvider:
    cfg = {**VALID_CONFIG}
    if config_overrides:
        cfg.update(config_overrides)
    return WeComProvider(cfg)


# ---------------------------------------------------------------------------
# Init / validation
# ---------------------------------------------------------------------------

class TestInit:

    @pytest.mark.parametrize('missing', ['corpid', 'corpsecret', 'agent_id'])
    async def test_missing_required_raises(self, missing):
        cfg = {k: v for k, v in VALID_CONFIG.items() if k != missing}
        with pytest.raises(OrgSyncProviderError, match=missing):
            WeComProvider(cfg)

    async def test_default_allow_dept_ids_is_root_1(self):
        p = await _provider()
        assert p._allow_dept_ids == [1]

    async def test_allow_dept_ids_preserved(self):
        p = await _provider({'allow_dept_ids': [2, 3]})
        assert p._allow_dept_ids == [2, 3]


# ---------------------------------------------------------------------------
# Token lifecycle (AC-50 ~ AC-53)
# ---------------------------------------------------------------------------

class TestTokenLifecycle:

    async def test_ensure_token_first_call_writes_redis(self, fake_redis, patched_client):
        patched_client.enqueue_token(
            errcode=0, errmsg='ok',
            access_token='fresh-token-1', expires_in=7200,
        )
        p = await _provider()
        async with httpx.AsyncClient() as client:
            token = await p._ensure_token(client)
        assert token == 'fresh-token-1'
        cached = await fake_redis.get(p._token_key())
        assert cached == b'fresh-token-1'
        ttl = await fake_redis.ttl(p._token_key())
        # TTL = expires_in - TOKEN_TTL_BUFFER (300) = 6900s
        assert 6800 < ttl <= 6900

    async def test_ensure_token_cache_hit_skips_gettoken(
        self, fake_redis, patched_client,
    ):
        p = await _provider()
        await fake_redis.set(p._token_key(), 'cached-token', ex=1000)
        async with httpx.AsyncClient() as client:
            token = await p._ensure_token(client)
        assert token == 'cached-token'
        assert patched_client.business_call_count('/cgi-bin/gettoken') == 0

    async def test_ensure_token_concurrent_lock(self, fake_redis, patched_client):
        """AC-52: concurrent callers ride one gettoken via the Redis lock."""
        patched_client.enqueue_token(
            errcode=0, errmsg='ok',
            access_token='coord-token', expires_in=7200,
        )
        p = await _provider()

        async def call_once():
            async with httpx.AsyncClient() as client:
                return await p._ensure_token(client)

        results = await asyncio.gather(*(call_once() for _ in range(5)))
        assert all(r == 'coord-token' for r in results)
        # Exactly one gettoken should have been made — the rest ride the cache.
        assert patched_client.business_call_count('/cgi-bin/gettoken') == 1

    async def test_ensure_token_42001_invalidates_and_retries(
        self, fake_redis, patched_client,
    ):
        """AC-53: 42001 → invalidate → refresh → retry, all in one business call."""
        # Pre-seed a "stale" token so the first attempt uses it.
        p = await _provider()
        await fake_redis.set(p._token_key(), 'stale-token', ex=1000)

        # First dept response: errcode 42001 (expired). Then a fresh gettoken,
        # then a successful dept response.
        patched_client.enqueue_dept(
            errcode=42001, errmsg='access_token expired',
        )
        patched_client.enqueue_token(
            errcode=0, errmsg='ok',
            access_token='new-token', expires_in=7200,
        )
        patched_client.enqueue_dept(
            errcode=0, errmsg='ok',
            department=[{'id': 1, 'name': 'Root', 'parentid': 0, 'order': 1}],
        )

        depts = await p.fetch_departments()
        assert len(depts) == 1
        assert depts[0].external_id == '1'

        # The stale token should have been deleted and replaced.
        cached = await fake_redis.get(p._token_key())
        assert cached == b'new-token'

    async def test_ensure_token_missing_access_token(self, fake_redis, patched_client):
        """gettoken returning errcode=0 but no token is a fetch error, not auth."""
        patched_client.enqueue_token(errcode=0, errmsg='ok')  # no access_token
        p = await _provider()
        with pytest.raises(OrgSyncFetchError):
            async with httpx.AsyncClient() as client:
                await p._ensure_token(client)


# ---------------------------------------------------------------------------
# Rate limit (AC-54)
# ---------------------------------------------------------------------------

class TestRateLimit:

    async def test_backoff_then_success(self, fake_redis, patched_client, monkeypatch):
        sleep_calls: list[float] = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        monkeypatch.setattr(wecom_mod.asyncio, 'sleep', fake_sleep)

        # First 3 dept calls → 45009; 4th → success.
        patched_client.enqueue_token(
            errcode=0, errmsg='ok', access_token='tok', expires_in=7200,
        )
        patched_client.enqueue_dept(errcode=45009, errmsg='rate limited')
        patched_client.enqueue_dept(errcode=45033, errmsg='rate limited')
        patched_client.enqueue_dept(errcode=45011, errmsg='rate limited')
        patched_client.enqueue_dept(
            errcode=0, errmsg='ok',
            department=[{'id': 1, 'name': 'Root', 'parentid': 0, 'order': 1}],
        )
        p = await _provider()
        depts = await p.fetch_departments()
        assert len(depts) == 1
        # 1s, 2s, 4s — three backoffs, then success on attempt index 3.
        assert sleep_calls == [1, 2, 4]

    async def test_exhausted_raises(self, fake_redis, patched_client, monkeypatch):
        async def fake_sleep(_delay):
            pass

        monkeypatch.setattr(wecom_mod.asyncio, 'sleep', fake_sleep)

        patched_client.enqueue_token(
            errcode=0, errmsg='ok', access_token='tok', expires_in=7200,
        )
        for _ in range(5):  # MAX_RATE_LIMIT_RETRIES + 1
            patched_client.enqueue_dept(errcode=45009, errmsg='rate limited')
        p = await _provider()
        with pytest.raises(OrgSyncFetchError, match='rate-limited'):
            await p.fetch_departments()


# ---------------------------------------------------------------------------
# Auth failures (AC-40, AC-41)
# ---------------------------------------------------------------------------

class TestAuthFailures:

    async def test_40013_invalid_corpid(self, fake_redis, patched_client):
        patched_client.enqueue_token(errcode=40013, errmsg='invalid corpid')
        p = await _provider()
        with pytest.raises(OrgSyncAuthFailedError) as excinfo:
            await p.authenticate()
        # Message must not leak corpsecret (AC-58)
        assert VALID_CONFIG['corpsecret'] not in str(excinfo.value)
        assert 'access_token 获取失败' in str(excinfo.value)

    async def test_40001_invalid_corpsecret(self, fake_redis, patched_client):
        patched_client.enqueue_token(
            errcode=40001, errmsg='invalid credential',
        )
        p = await _provider()
        with pytest.raises(OrgSyncAuthFailedError) as excinfo:
            await p.authenticate()
        assert VALID_CONFIG['corpsecret'] not in str(excinfo.value)

    async def test_60011_visible_range(self, fake_redis, patched_client):
        """AC-41: 60011 on a business call signals scope mismatch."""
        patched_client.enqueue_token(
            errcode=0, errmsg='ok', access_token='tok', expires_in=7200,
        )
        patched_client.enqueue_dept(errcode=60011, errmsg='no permission')
        p = await _provider()
        with pytest.raises(OrgSyncAuthFailedError, match='可见范围'):
            await p.fetch_departments()

    async def test_42009_unauthorized(self, fake_redis, patched_client):
        patched_client.enqueue_token(
            errcode=0, errmsg='ok', access_token='tok', expires_in=7200,
        )
        patched_client.enqueue_dept(errcode=42009, errmsg='unauthorized')
        p = await _provider()
        with pytest.raises(OrgSyncAuthFailedError, match='未授权'):
            await p.fetch_departments()


# ---------------------------------------------------------------------------
# fetch_departments (AC-42 ~ AC-44)
# ---------------------------------------------------------------------------

class TestFetchDepartments:

    async def test_default_root_is_1(self, fake_redis, patched_client):
        patched_client.enqueue_dept(
            errcode=0, errmsg='ok',
            department=[
                {'id': 1, 'name': '集团总部', 'parentid': 0, 'order': 1},
                {'id': 2, 'name': '研发', 'parentid': 1, 'order': 2},
                {'id': 3, 'name': '销售', 'parentid': 1, 'order': 3},
            ],
        )
        p = await _provider()
        depts = await p.fetch_departments()
        assert {d.external_id for d in depts} == {'1', '2', '3'}
        root = next(d for d in depts if d.external_id == '1')
        assert root.parent_external_id is None
        non_root = next(d for d in depts if d.external_id == '2')
        assert non_root.parent_external_id == '1'
        assert non_root.sort_order == 2
        # Check the ?id=1 query param landed on the right call.
        dept_call = next(
            c for c in patched_client.calls
            if c.url.path.endswith('/cgi-bin/department/list')
        )
        assert dept_call.url.params.get('id') == '1'

    async def test_multi_root_merge_and_dedupe(self, fake_redis, patched_client):
        p = await _provider({'allow_dept_ids': [2, 3]})
        # Root 2 subtree
        patched_client.enqueue_dept(
            errcode=0, errmsg='ok',
            department=[
                {'id': 2, 'name': '研发', 'parentid': 1, 'order': 1},
                {'id': 10, 'name': '前端组', 'parentid': 2, 'order': 1},
                {'id': 11, 'name': '共享子部门', 'parentid': 2, 'order': 2},
            ],
        )
        # Root 3 subtree — note "共享子部门" repeated
        patched_client.enqueue_dept(
            errcode=0, errmsg='ok',
            department=[
                {'id': 3, 'name': '销售', 'parentid': 1, 'order': 1},
                {'id': 11, 'name': '共享子部门', 'parentid': 3, 'order': 2},
                {'id': 20, 'name': '华北销售', 'parentid': 3, 'order': 3},
            ],
        )
        depts = await p.fetch_departments()
        ids = [d.external_id for d in depts]
        # "11" appears once only
        assert ids.count('11') == 1
        # Both roots are in the result, both with parent=None relative to sync scope
        roots = [d for d in depts if d.external_id in {'2', '3'}]
        assert all(d.parent_external_id is None for d in roots)

    async def test_parentid_and_order_conversion(self, fake_redis, patched_client):
        patched_client.enqueue_dept(
            errcode=0, errmsg='ok',
            department=[
                {'id': 1, 'name': 'Root', 'parentid': 0, 'order': 100},
                {'id': 123, 'name': 'X', 'parentid': 1},  # missing order
            ],
        )
        p = await _provider()
        depts = await p.fetch_departments()
        d123 = next(d for d in depts if d.external_id == '123')
        assert d123.parent_external_id == '1'
        assert d123.sort_order == 0


# ---------------------------------------------------------------------------
# fetch_members (AC-45 ~ AC-49)
# ---------------------------------------------------------------------------

class TestFetchMembers:

    async def test_default_uses_allow_dept_ids(self, fake_redis, patched_client):
        p = await _provider()
        patched_client.enqueue_user(
            errcode=0, errmsg='ok',
            userlist=[
                {
                    'userid': 'alice', 'name': 'Alice', 'email': 'a@x.com',
                    'mobile': '13800000001', 'department': [1, 2],
                    'main_department': 1, 'status': 1,
                },
            ],
        )
        members = await p.fetch_members()
        call = next(
            c for c in patched_client.calls
            if c.url.path.endswith('/cgi-bin/user/list')
        )
        assert call.url.params.get('department_id') == '1'
        assert call.url.params.get('fetch_child') == '1'
        assert members[0].primary_dept_external_id == '1'
        assert members[0].secondary_dept_external_ids == ['2']

    async def test_main_department_fallback(self, fake_redis, patched_client):
        patched_client.enqueue_user(
            errcode=0, errmsg='ok',
            userlist=[
                {
                    'userid': 'bob', 'name': 'Bob',
                    'department': [5, 6, 7],  # no main_department
                    'status': 1,
                },
            ],
        )
        p = await _provider()
        members = await p.fetch_members()
        assert members[0].primary_dept_external_id == '5'
        assert members[0].secondary_dept_external_ids == ['6', '7']

    @pytest.mark.parametrize('raw_status,expected', [
        (1, 'active'), (2, 'disabled'), (4, 'disabled'), (5, 'disabled'),
    ])
    async def test_status_mapping(
        self, fake_redis, patched_client, raw_status, expected,
    ):
        patched_client.enqueue_user(
            errcode=0, errmsg='ok',
            userlist=[
                {
                    'userid': 'u', 'name': 'U', 'department': [1],
                    'main_department': 1, 'status': raw_status,
                },
            ],
        )
        p = await _provider()
        members = await p.fetch_members()
        assert members[0].status == expected

    async def test_dedupe_across_roots_merges_secondaries(
        self, fake_redis, patched_client,
    ):
        p = await _provider({'allow_dept_ids': [2, 3]})
        patched_client.enqueue_user(
            errcode=0, errmsg='ok',
            userlist=[
                {
                    'userid': 'carol', 'name': 'Carol', 'department': [2, 10],
                    'main_department': 2, 'status': 1,
                },
            ],
        )
        patched_client.enqueue_user(
            errcode=0, errmsg='ok',
            userlist=[
                {
                    'userid': 'carol', 'name': 'Carol', 'department': [3, 20],
                    'main_department': 3, 'status': 1,
                },
            ],
        )
        members = await p.fetch_members()
        assert len(members) == 1
        m = members[0]
        assert m.primary_dept_external_id == '2'
        # First-seen primary keeps; extras from both roots flow into secondary.
        assert set(m.secondary_dept_external_ids) == {'3', '10', '20'}


# ---------------------------------------------------------------------------
# test_connection (AC-39, AC-58)
# ---------------------------------------------------------------------------

class TestTestConnection:

    async def test_returns_summary_no_token(self, fake_redis, patched_client):
        patched_client.enqueue_dept(
            errcode=0, errmsg='ok',
            department=[
                {'id': 1, 'name': '总部', 'parentid': 0, 'order': 1},
                {'id': 2, 'name': '研发', 'parentid': 1, 'order': 2},
            ],
        )
        patched_client.enqueue_simplelist(
            errcode=0, errmsg='ok',
            userlist=[
                {'userid': 'a', 'name': 'A'},
                {'userid': 'b', 'name': 'B'},
                {'userid': 'c', 'name': 'C'},
            ],
        )
        p = await _provider()
        result = await p.test_connection()
        assert result == {
            'connected': True,
            'org_name': '总部',
            'total_depts': 2,
            'total_members': 3,
        }
        # No token / secret fields sneaked in
        for k in result:
            assert 'token' not in k.lower()
            assert 'secret' not in k.lower()


# ---------------------------------------------------------------------------
# Safety: never leak corpsecret (AC-58)
# ---------------------------------------------------------------------------

class TestNoSecretLeakage:

    async def test_error_chain_does_not_include_corpsecret(
        self, fake_redis, patched_client,
    ):
        patched_client.enqueue_token(errcode=40013, errmsg='invalid corpid')
        p = await _provider()
        try:
            await p.authenticate()
        except OrgSyncAuthFailedError as e:
            for text in (str(e), repr(e)):
                assert VALID_CONFIG['corpsecret'] not in text

    async def test_fetch_error_does_not_include_corpsecret(
        self, fake_redis, patched_client,
    ):
        patched_client.enqueue_token(
            errcode=0, errmsg='ok', access_token='tok', expires_in=7200,
        )
        patched_client.enqueue_dept(errcode=70000, errmsg='unknown error')
        p = await _provider()
        try:
            await p.fetch_departments()
        except OrgSyncFetchError as e:
            for text in (str(e), repr(e)):
                assert VALID_CONFIG['corpsecret'] not in text
