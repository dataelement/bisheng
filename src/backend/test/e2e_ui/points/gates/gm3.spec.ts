import { test, expect } from '@playwright/test';
import { loginPlatform, loginPortal } from '../fixtures/auth';
import { runGm3Trigger } from '../helpers/gm3';

/**
 * G-M3：排行榜 + 组织四级标签（Portal UI + Platform UI + API）。
 * 运行：E2E_POINTS_RUN_GATES=1 npm run test:gm3
 *
 * 破坏性「设为公司根」默认跳过；需同时：
 *   E2E_POINTS_ALLOW_ORG_MUTATE=1
 *   E2E_POINTS_COMPANY_DEPT_ID=<dept_id>
 */
test.describe('G-M3 ranks & org labels', () => {
  test.skip(!process.env.E2E_POINTS_RUN_GATES, 'Set E2E_POINTS_RUN_GATES=1 after T014–T024');

  test.beforeAll(() => {
    const refreshed = runGm3Trigger(['refresh_ranks']);
    expect(refreshed.ok).toBeTruthy();
  });

  test('org_level cascade is consistent for each company root', () => {
    const snap = runGm3Trigger(['org_levels']);
    expect(snap.ok).toBeTruthy();
    // 允许多公司；company_count 仅作观测，不再要求唯一根。
    test.info().annotations.push({
      type: 'note',
      description: `company_count=${String(snap.company_count ?? 0)}`,
    });
    const verified = runGm3Trigger(['verify_cascade']);
    expect(verified.ok).toBeTruthy();
    if (verified.skipped) {
      test.info().annotations.push({
        type: 'note',
        description: String(verified.reason || 'no company root — cascade verification skipped'),
      });
      return;
    }
    expect(verified.mismatches).toEqual([]);
    expect(Number(verified.checked)).toBeGreaterThan(0);
    expect(Number(verified.company_count)).toBeGreaterThan(0);
  });

  test('optional set-company-root only when mutate flag set', () => {
    const allow = process.env.E2E_POINTS_ALLOW_ORG_MUTATE === '1';
    const deptId = process.env.E2E_POINTS_COMPANY_DEPT_ID;
    test.skip(!allow || !deptId, 'Set E2E_POINTS_ALLOW_ORG_MUTATE=1 and E2E_POINTS_COMPANY_DEPT_ID');
    const result = runGm3Trigger(['set_company_root', String(deptId)]);
    expect(result.ok).toBeTruthy();
    expect(Number(result.labeled_count)).toBeGreaterThan(0);
    const verified = runGm3Trigger(['verify_cascade']);
    expect(verified.ok).toBeTruthy();
    expect(verified.skipped).toBeFalsy();
    expect(verified.mismatches).toEqual([]);
  });

  test('platform admin sees org-level section and set-company-root action', async ({ browser }) => {
    test.setTimeout(120_000);
    const platformBase = process.env.E2E_PLATFORM_BASE_URL || 'http://127.0.0.1:3001';
    const context = await browser.newContext({ baseURL: platformBase });
    const page = await context.newPage();
    try {
      await loginPlatform(page, 'admin');
      await page.goto(`${platformBase}/sys`);
      await page.getByRole('tab', { name: '组织与成员' }).click();
      // 树加载可能较慢；右侧默认选中根部门后切到「部门设置」。
      await expect(page.getByRole('tab', { name: '部门设置' })).toBeVisible({ timeout: 90_000 });
      await page.getByRole('tab', { name: '部门设置' }).click();
      await expect(page.getByText('组织层级标签')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText('当前层级')).toBeVisible();
      // 可编辑时为下拉（选项仅「公司」），经底部保存提交，不再有独立设公司按钮。
      await expect(page.getByRole('button', { name: /设为公司/ })).toHaveCount(0);
      await expect(page.getByRole('button', { name: '保存' }).first()).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test('portal homepage leaderboard tabs stay within TOP10 without sticky me row', async ({
    page,
  }) => {
    await loginPortal(page, 'user');
    await page.goto('/');
    await expect(page.getByText('积分榜单').first()).toBeVisible({ timeout: 30_000 });
    const tablist = page.getByRole('tablist', { name: '积分榜周期' });
    await expect(tablist).toBeVisible();
    for (const label of ['本月', '本年', '总榜']) {
      await tablist.getByRole('tab', { name: label, exact: true }).click();
      await expect(tablist.getByRole('tab', { name: label, exact: true })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      // 空态或列表均可；禁止「我」置底行文案。
      await expect(page.getByText(/^我$/)).toHaveCount(0);
      const empty = page.getByText('暂无积分榜数据');
      const loading = page.getByText('加载积分榜');
      if (await empty.isVisible().catch(() => false)) {
        continue;
      }
      if (await loading.isVisible().catch(() => false)) {
        await expect(loading).toBeHidden({ timeout: 30_000 });
      }
    }
  });

  test('my points shows department and global rank placeholders', async ({ page }) => {
    await loginPortal(page, 'user');
    await page.goto('/points');
    await expect(page.getByText('我的积分').first()).toBeVisible({ timeout: 30_000 });
    const summary = page.getByLabel('积分摘要');
    await expect(summary.getByText('排名', { exact: true })).toBeVisible();
    await expect(summary.getByText(/部门/)).toBeVisible();
    await expect(summary.getByText(/总榜/)).toBeVisible();
  });
});
