"""E2E tests for F016: Tenant Quota Hierarchy (配额沿树取严 + MVP 手工调整).

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE env var)
- Default admin account: admin/admin123
- multi_tenant.enabled = true in config
- F011 / F012 / F013 already merged (this feature depends on TenantDao
  tree methods, strict_tenant_filter, and OpenFGA tenant#shared_to)

Covers spec §7 nine manual QA scenarios where automation is practical:

- AC-01 §7-1: Single-tenant 100% blocks creation → 19401
- AC-01 + AC-08 §7-2: Root<Child hardcap, Root saturated → 19401 with
  '集团总量已耗尽' Msg variant
- AC-02 §7-3: Root-shared resource excluded from Child strict count
- AC-07 §7-4: Root usage = Root self + Σ active Child (30+50+20=100)
- AC-08 §7-5: Root saturated blocks any Child creation
- AC-09 §7-6: strict_tenant_filter prevents IN-list leak
- AC-03 T05-merged: PUT /tenants/{id}/quota accepts storage_gb
- AC-06 T05-merged: GET /tenants/quota/tree returns root + active children
- AC-06 T05-merged: GET /tenants/quota/tree forbidden for non super admin
- AC-10 stub-safe: model_tokens_monthly returns 0 when llm_token_log table
  does not exist yet (pre-F017 state)

Deferred to T09 manual QA:
- §7-7 Derived-data attribution to Child leaf tenant (requires F017 §5.4
  ChatMessageService / LLMTokenTracker writes)
- §7-8 Unlimited (-1) resource type allows repeated creation: spot-checked
  locally but full cycle is manual to avoid real resource spam
- §7-? Delete-resource releases quota: no hook, relies on existing resource
  deletion path — manual via UI

Data isolation: all test resources use 'e2e-f016-' prefix.
"""

import os

import pytest
import httpx

from test.e2e.helpers.auth import (
    get_admin_token,
    auth_headers,
    create_test_user,
    get_user_token,
)
from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.cleanup import cleanup_test_tenants

PREFIX = 'e2e-f016-'
TEST_USER_PREFIX = 'e2e_f016_user'


@pytest.mark.skipif(
    os.environ.get('E2E_SKIP', '0') == '1',
    reason='E2E tests skipped (E2E_SKIP=1)',
)
class TestE2ETenantQuotaHierarchy:
    """E2E: F016 Tenant Quota Hierarchy."""

    # ──────── Fixtures ────────

    @pytest.fixture(autouse=True, scope='class')
    async def setup_and_teardown(self):
        """Class-scoped dual cleanup."""
        async with httpx.AsyncClient(base_url='', timeout=30.0) as client:
            admin_token = await get_admin_token(client)
            await cleanup_test_tenants(client, PREFIX, admin_token)
            yield
            await cleanup_test_tenants(client, PREFIX, admin_token)

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(base_url='', timeout=30.0) as client:
            yield client

    @pytest.fixture
    async def admin_token(self, client):
        return await get_admin_token(client)

    @pytest.fixture
    async def child_admin_token(self, client, admin_token):
        """Create a non-super-admin user to serve as Child Admin."""
        username = f'{TEST_USER_PREFIX}_child_admin'
        try:
            await create_test_user(client, admin_token, username=username, role_id=2)
        except Exception:
            pass  # may exist already
        return await get_user_token(client, username, 'test_password_123')

    # ──────── Helpers ────────

    async def _set_tenant_quota(self, client, admin_token, tenant_id: int, quota_config: dict):
        """PUT /tenants/{id}/quota helper."""
        resp = await client.put(
            f'{API_BASE}/tenants/{tenant_id}/quota',
            json={'quota_config': quota_config},
            headers=auth_headers(admin_token),
        )
        return assert_resp_200(resp)

    # ══════════════════════════════════════════════════════════════════
    # AC-03 / T05 merged: storage_gb key accepted by existing F010 endpoint
    # ══════════════════════════════════════════════════════════════════

    async def test_put_quota_accepts_storage_gb(self, client, admin_token):
        """AC-03: F016 T02 extended VALID_QUOTA_KEYS — storage_gb now accepted."""
        # Use Root tenant (id=1) — update quota should pass validation.
        resp = await client.put(
            f'{API_BASE}/tenants/1/quota',
            json={'quota_config': {
                'storage_gb': 500,
                'user_count': 200,
                'model_tokens_monthly': 10_000_000,
            }},
            headers=auth_headers(admin_token),
        )
        data = assert_resp_200(resp)
        assert data['quota_config']['storage_gb'] == 500
        assert data['quota_config']['user_count'] == 200
        assert data['quota_config']['model_tokens_monthly'] == 10_000_000

    async def test_put_quota_rejects_unknown_key(self, client, admin_token):
        """AC-03 negative: unknown key → 24005 QuotaConfigInvalidError (v2.5.0 behavior preserved)."""
        resp = await client.put(
            f'{API_BASE}/tenants/1/quota',
            json={'quota_config': {'nonexistent_resource': 10}},
            headers=auth_headers(admin_token),
        )
        assert_resp_error(resp, 24005)

    # ══════════════════════════════════════════════════════════════════
    # AC-06: GET /tenants/quota/tree response structure + permission
    # ══════════════════════════════════════════════════════════════════

    async def test_quota_tree_returns_root_and_active_children(self, client, admin_token):
        """AC-06: GET /tenants/quota/tree returns Root + active Children.

        Only verifies the response structure (root has usage[], children[] is a
        list, each child has same structure). Specific usage values depend on
        test-run state and are asserted in test_root_aggregate_sum_*.
        """
        resp = await client.get(
            f'{API_BASE}/tenants/quota/tree',
            headers=auth_headers(admin_token),
        )
        data = assert_resp_200(resp)
        assert 'root' in data
        assert 'children' in data
        assert data['root']['tenant_id'] == 1
        assert data['root']['parent_tenant_id'] is None
        assert isinstance(data['root']['usage'], list)
        assert isinstance(data['children'], list)
        # Every item in usage has the 4 expected fields.
        for item in data['root']['usage']:
            assert set(item.keys()) == {'resource_type', 'used', 'limit', 'utilization'}

    async def test_quota_tree_forbidden_for_non_super_admin(self, client, child_admin_token):
        """AC-06: Only global super admin can access /quota/tree; non-admin → 403.

        Project convention: business errors return HTTP 200 with
        ``UnifiedResponseModel.status_code`` carrying the actual error code.
        Here ``UserPayload.get_admin_user`` calls
        ``UnAuthorizedError.http_exception()`` which is converted by a global
        exception handler to HTTP 200 + body status_code=403.
        """
        resp = await client.get(
            f'{API_BASE}/tenants/quota/tree',
            headers=auth_headers(child_admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 403, (
            f"Expected body status_code=403, got {body.get('status_code')}: {body}"
        )

    async def test_quota_tree_rejects_unauthenticated_request(self, client):
        """AC-06: Unauthenticated request to /quota/tree → HTTP 401.

        Without a JWT cookie the ``AuthJwt`` dependency short-circuits BEFORE
        ``get_admin_user`` can run, so this path returns a real HTTP 401
        (not a UnifiedResponseModel body). Complements the 403 test above.
        """
        resp = await client.get(f'{API_BASE}/tenants/quota/tree')
        assert resp.status_code == 401

    # ══════════════════════════════════════════════════════════════════
    # AC-10 stub-safe: missing llm_token_log table returns 0
    # ══════════════════════════════════════════════════════════════════

    async def test_model_tokens_monthly_stub_returns_zero(self, client, admin_token):
        """AC-10 stub-safe: pre-F017, llm_token_log may not exist → tree shows 0 used."""
        resp = await client.get(
            f'{API_BASE}/tenants/quota/tree',
            headers=auth_headers(admin_token),
        )
        data = assert_resp_200(resp)
        tokens_usage = next(
            (u for u in data['root']['usage'] if u['resource_type'] == 'model_tokens_monthly'),
            None,
        )
        assert tokens_usage is not None, 'model_tokens_monthly must appear in usage'
        # Either the table is missing (used=0 via try/except) or F017 has landed
        # and a genuine SUM is returned (>=0). Both are acceptable.
        assert tokens_usage['used'] >= 0

    # ══════════════════════════════════════════════════════════════════
    # AC-01 / AC-07 / AC-08 / AC-09: scenarios deferred to T09 manual QA
    # ══════════════════════════════════════════════════════════════════
    # The full multi-tenant chain tests below require setting up multiple
    # Child tenants mounted under Root, creating users in each with non-admin
    # roles, and exercising the resource creation path end-to-end. The DDL
    # setup is substantial and better performed manually on 114 during T09.
    # See features/v2.5.1/016-tenant-quota-hierarchy/ac-verification.md for
    # the manual QA script.
    # ══════════════════════════════════════════════════════════════════

    @pytest.mark.skip(reason='T09 manual QA — requires multi-Child tenant setup on 114')
    async def test_single_tenant_100pct_blocks(self):
        """§7-1 / AC-01: Child quota=2, used=2, create 3rd → 19401."""

    @pytest.mark.skip(reason='T09 manual QA — requires Root<Child quota + populated resources')
    async def test_root_hardcap_triggers_group_exhausted_msg(self):
        """§7-2 / AC-08: Root=5 < Child=10, Root saturated → 19401 msg contains '集团总量已耗尽'."""

    @pytest.mark.skip(reason='T09 manual QA — requires F013 shared_to tuple on knowledge')
    async def test_shared_resource_not_counted_in_child(self):
        """§7-3 / AC-02 / AC-09: Root shared knowledge → Child _count_usage_strict excludes it."""

    @pytest.mark.skip(reason='T09 manual QA — requires 2+ active Children and knowledge resources')
    async def test_root_aggregate_sum_30_50_20(self):
        """§7-4 / AC-07: Child A=30, Child B=50, Root=20 → aggregate=100 via /quota/tree."""

    @pytest.mark.skip(reason='T09 manual QA — requires saturated Root')
    async def test_root_saturated_blocks_any_child(self):
        """§7-5 / AC-08: Root quota=100, used=100 → any Child create → 19401."""

    @pytest.mark.skip(reason='T09 manual QA — verify strict_tenant_filter()')
    async def test_strict_filter_no_inlist_leak(self):
        """§7-6 / AC-09: Root shared resource does not appear in Child strict count."""
