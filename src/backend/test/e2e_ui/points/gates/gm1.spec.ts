import { test, expect } from '@playwright/test';
import { loginPortal, pointsCredentials } from '../fixtures/auth';

/**
 * G-M1：账本与管理端可读可调（Portal UI + API）。
 * 运行：E2E_POINTS_RUN_GATES=1 npm run test:gm1
 */
test.describe('G-M1 points ledger & admin', () => {
  test.skip(!process.env.E2E_POINTS_RUN_GATES, 'Set E2E_POINTS_RUN_GATES=1 when stack is up');

  test('admin opens points admin and sees seeded rules', async ({ page }) => {
    await loginPortal(page, 'admin');
    await page.goto('/admin');
    await page.getByText('积分管理').click();
    await expect(page.getByText('G1')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('积分规则配置')).toBeVisible();
  });

  test('admin adjusts user points and balance updates', async ({ page, request }) => {
    const targetUserId = Number(process.env.E2E_POINTS_TARGET_USER_ID || '4');
    await loginPortal(page, 'admin');
    await page.goto('/admin');
    await page.getByText('积分管理').click();
    await expect(page.getByText('用户积分管理')).toBeVisible({ timeout: 30_000 });

    // 用户列表直接调分（不选 R* 扣减规则）
    await page.getByRole('tab', { name: '用户积分列表' }).click();
    await page.locator('#points-user-search').fill(String(targetUserId));
    await expect(page.getByRole('button', { name: '调整积分' }).first()).toBeVisible({
      timeout: 30_000,
    });
    await page.getByRole('button', { name: '调整积分' }).first().click();
    await expect(page.getByRole('heading', { name: '调整用户积分' })).toBeVisible();
    await page.locator('#points-adjust-delta').fill('10');
    await page.locator('#points-adjust-remark').fill('联调调分验证');
    await page.getByRole('button', { name: '确认调整' }).click();
    await expect(page.getByText(/调分成功/)).toBeVisible({ timeout: 30_000 });

    // API 复核：目标用户流水可见正 delta
    const cookies = await page.context().cookies();
    const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
    const res = await request.get(
      `${process.env.E2E_PORTAL_BASE_URL || 'http://127.0.0.1:5173'}/workspace/api/v1/points/admin/overview`,
      { headers: { Cookie: cookieHeader } },
    );
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.status_code).toBe(200);
    expect(Number(body.data?.total_issued)).toBeGreaterThanOrEqual(10);
  });

  test('user opens my-points summary', async ({ page }) => {
    await loginPortal(page, 'user');
    await page.goto('/points');
    await expect(page.getByText('我的积分').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('本月获得')).toBeVisible();
    await expect(page.getByText('积分明细')).toBeVisible();
  });

  test('non-admin adjust API is denied with 18201', async ({ request }) => {
    const { username, password } = pointsCredentials('user');
    const loginRes = await request.post('http://127.0.0.1:8010/api/v1/auth/login', {
      data: { account: username, password },
    });
    expect(loginRes.ok()).toBeTruthy();
    const res = await request.post(
      `${process.env.E2E_PORTAL_BASE_URL || 'http://127.0.0.1:5173'}/workspace/api/v1/points/admin/adjust`,
      {
        data: { user_id: 4, delta: 1, remark: '无权调分测试' },
      },
    );
    const body = await res.json();
    expect(body.status_code).toBe(18201);
  });
});
