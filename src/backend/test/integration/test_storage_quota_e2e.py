"""End-to-end self-test for tenant storage quota (19403).

Runs against a real DB: loads the actual default tenant config, mocks only
the SQL-driven usage count to a value above the configured cap, then drives
QuotaService.check_quota through the same code path the @require_quota
decorator uses on /api/v1/knowledge/upload/{kid}.

Verifies:
  1. The decorator's resource_type='knowledge_space_file' correctly aliases
     to tenant.quota_config['storage_gb'] (otherwise the mock alone wouldn't
     trip a blocker — limit would be -1 and the chain would short-circuit).
  2. The exception is TenantStorageQuotaExceededError(19403) with kwargs
     containing used_gb / quota_gb / tenant_name / tenant_id / reason.
  3. main.handle_http_exception renders the exception into the JSON shape
     the platform request.ts interceptor expects, with kwargs flattened
     into response.data — this is what feeds i18next interpolation
     ({{used_gb}}, {{quota_gb}}) on the frontend.
  4. The platform i18n bundle errors.19403 contains the {{used_gb}} /
     {{quota_gb}} placeholders.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Allow `python -m test.integration.test_storage_quota_e2e` from src/backend
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def main() -> int:
    from bisheng.role.domain.services.quota_service import QuotaService
    from bisheng.common.errcode.tenant_quota import TenantStorageQuotaExceededError
    from bisheng.database.models.tenant import TenantDao

    # Real DB read of the default tenant (id=1). Confirms storage_gb is set.
    tenant = await TenantDao.aget_by_id(1)
    assert tenant is not None, 'default tenant id=1 must exist'
    storage_gb = (tenant.quota_config or {}).get('storage_gb')
    print(f'[setup] default tenant: id={tenant.id} name={tenant.tenant_name!r} '
          f'storage_gb={storage_gb!r}')
    assert storage_gb is not None, (
        'default tenant.quota_config[storage_gb] must be set for this test; '
        f'got quota_config={tenant.quota_config!r}'
    )

    # Pretend the tenant has used (storage_gb + 1) GB worth of knowledge files.
    # _count_usage_strict / _aggregate_root_usage are the only SQL-driven
    # usage queries — patching them is the minimum surface to simulate
    # storage exhaustion without touching the DB.
    fake_used = int(storage_gb) + 1
    print(f'[setup] forcing tenant_used = {fake_used} GB (cap = {storage_gb} GB)')

    # Non-admin user. login_user.is_admin() must return False or the entire
    # check_quota short-circuits.
    non_admin = MagicMock()
    non_admin.user_id = 5
    non_admin.is_admin.return_value = False
    non_admin.tenant_id = 1

    # No roles → DEFAULT_ROLE_QUOTA[knowledge_space_file]=500 (GB), which is
    # higher than the tenant cap, so the blocker must come from the tenant
    # chain (the bug being fixed).
    captured: list = []
    with patch(
        'bisheng.role.domain.services.quota_service.UserRoleDao.aget_user_roles',
        new=AsyncMock(return_value=[]),
    ), patch.object(
        QuotaService, '_count_usage_strict',
        new=AsyncMock(return_value=fake_used),
    ), patch.object(
        QuotaService, '_aggregate_root_usage',
        new=AsyncMock(return_value=fake_used),
    ):
        try:
            await QuotaService.check_quota(
                user_id=non_admin.user_id,
                # This is what @require_quota(KNOWLEDGE_SPACE_FILE) passes —
                # before the alias fix, tenant.quota_config['knowledge_space_file']
                # was -1 and check_quota silently returned True.
                resource_type='knowledge_space_file',
                tenant_id=1,
                login_user=non_admin,
            )
        except TenantStorageQuotaExceededError as e:
            captured.append(e)
        else:
            print('[FAIL] check_quota returned without raising — alias fix not active')
            return 1

    if not captured:
        print('[FAIL] no exception captured')
        return 1
    exc = captured[0]
    print(f'[ok] raised {type(exc).__name__}: code={exc.Code}')
    print(f'[ok] kwargs={exc.kwargs}')
    assert exc.Code == 19403, exc.Code
    assert exc.kwargs.get('used_gb') == fake_used, exc.kwargs
    assert exc.kwargs.get('quota_gb') == storage_gb, exc.kwargs
    assert exc.kwargs.get('tenant_name') == tenant.tenant_name, exc.kwargs
    assert exc.kwargs.get('tenant_id') == 1, exc.kwargs
    assert exc.kwargs.get('reason') in ('tenant_limit', 'root_hardcap'), exc.kwargs

    # Drive the real FastAPI exception handler so we see the exact JSON
    # the frontend interceptor would receive.
    from bisheng.main import handle_http_exception

    # handle_http_exception expects (req, exc); the request object is only
    # used for logging, so a MagicMock suffices.
    fake_req = MagicMock()
    fake_req.method = 'POST'
    fake_req.url = '/api/v1/knowledge/upload/1'

    response = handle_http_exception(fake_req, exc)
    body = json.loads(response.body)
    print(f'[ok] http response body: {json.dumps(body, ensure_ascii=False)}')
    assert body['status_code'] == 19403, body
    assert body['data']['used_gb'] == fake_used, body
    assert body['data']['quota_gb'] == storage_gb, body
    assert body['data']['tenant_name'] == tenant.tenant_name, body

    # Verify the i18n template carries the placeholders the frontend expects.
    repo_root = Path(__file__).resolve().parents[4]
    locales_dir = repo_root / 'src/frontend/platform/public/locales'
    for locale in ('zh-Hans', 'en-US', 'ja'):
        bs_path = locales_dir / locale / 'bs.json'
        bs = json.loads(bs_path.read_text(encoding='utf-8'))
        # bs.json schema: top-level "errors" namespace at multiple paths;
        # search recursively to be robust against future restructuring.
        def _find(node):
            if isinstance(node, dict):
                if '19403' in node and isinstance(node['19403'], str):
                    return node['19403']
                for v in node.values():
                    found = _find(v)
                    if found:
                        return found
            return None
        tpl = _find(bs)
        assert tpl, f'{bs_path} missing errors.19403'
        assert '{{used_gb}}' in tpl and '{{quota_gb}}' in tpl, (
            f'{bs_path}: errors.19403 lacks {{used_gb}}/{{quota_gb}} placeholders: {tpl!r}'
        )
        print(f'[ok] {locale}: {tpl}')

    print('\n[PASS] storage-quota end-to-end self-test')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
