import { test, expect } from '@playwright/test';
import { loginPortal } from '../fixtures/auth';
import { runGm4Trigger } from '../helpers/gm4';

/**
 * G-M4：运营配置与 R* 扣减（Portal UI + API）。
 * 运行：E2E_POINTS_RUN_GATES=1 npm run test:gm4
 *
 * T025 Client 文档页入口延后；本门禁用 Portal 管理端「违规扣减」作为浏览器扣减路径。
 */
test.describe('G-M4 ops console & deduct', () => {
  test.skip(!process.env.E2E_POINTS_RUN_GATES, 'Set E2E_POINTS_RUN_GATES=1 after T021–T025');

  const targetUserId = Number(process.env.E2E_POINTS_TARGET_USER_ID || '4');
  const publisherUserId = Number(process.env.E2E_POINTS_PUBLISHER_USER_ID || '5');

  test('admin sets G1 beneficiary to publisher and award lands on publisher', async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const before = runGm4Trigger(['get_beneficiary', 'G1']);
    expect(before.ok).toBeTruthy();
    const prevBeneficiary = String(before.beneficiary || 'uploader');

    try {
      await loginPortal(page, 'admin');
      await page.goto('/admin');
      await page.getByText('积分管理').click();
      await expect(page.getByText('积分规则配置')).toBeVisible({ timeout: 30_000 });
      await page.getByRole('tab', { name: '积分获取规则' }).click();

      const g1Row = page.locator('tr', { hasText: 'G1' }).first();
      await expect(g1Row).toBeVisible({ timeout: 30_000 });
      await g1Row.getByRole('button', { name: '编辑' }).click();
      await expect(page.getByRole('heading', { name: /编辑规则 G1/ })).toBeVisible();
      await page.locator('select').selectOption('publisher');
      await page.getByRole('button', { name: '保存' }).click();
      await expect(page.getByText(/已保存 G1/)).toBeVisible({ timeout: 30_000 });
      await expect(g1Row.getByText('发布人')).toBeVisible();

      const award = runGm4Trigger([
        'award_g1_split',
        String(targetUserId),
        String(publisherUserId),
      ]);
      expect(award.ok).toBeTruthy();
      expect(award.skipped).toBeFalsy();
      expect(award.beneficiary_config).toBe('publisher');
      const logs = (award.logs as Array<{ user_id: number; beneficiary_role: string }>) || [];
      expect(logs.length).toBe(1);
      expect(logs[0].user_id).toBe(publisherUserId);
      expect(logs[0].beneficiary_role).toBe('publisher');
    } finally {
      // Always restore so shared env does not stay on publisher.
      runGm4Trigger(['set_beneficiary', 'G1', prevBeneficiary]);
    }
  });

  test('admin deducts via R* rule and audit shows deduct', async ({ page }) => {
    test.setTimeout(120_000);
    await loginPortal(page, 'admin');
    await page.goto('/admin');
    await page.getByText('积分管理').click();
    await expect(page.getByText('用户积分管理')).toBeVisible({ timeout: 30_000 });

    await page.getByRole('tab', { name: '用户积分列表' }).click();
    await page.locator('#points-user-search').fill(String(targetUserId));
    await expect(page.getByRole('button', { name: '违规扣减' }).first()).toBeVisible({
      timeout: 30_000,
    });
    await page.getByRole('button', { name: '违规扣减' }).first().click();
    await expect(page.getByRole('heading', { name: '违规扣减' })).toBeVisible();
    const ruleSelect = page.locator('#points-deduct-rule');
    // Default is first enabled R*；用原生赋值避开 Playwright selectOption 的 label 解析问题。
    await expect(ruleSelect.locator('option[value="R1"]')).toHaveCount(1, { timeout: 15_000 });
    await ruleSelect.evaluate((el) => {
      const select = el as HTMLSelectElement;
      select.value = 'R1';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await expect(ruleSelect).toHaveValue('R1');
    await page.locator('#points-deduct-remark').fill('G-M4 联调违规扣减');
    await page.getByRole('button', { name: '确认扣减' }).click();
    await expect(page.getByText(/扣减成功/)).toBeVisible({ timeout: 30_000 });

    const latest = runGm4Trigger(['latest_deduct', String(targetUserId), 'R1']);
    expect(latest.ok).toBeTruthy();
    expect(latest.found).toBeTruthy();
    expect(Number(latest.delta)).toBeLessThan(0);
    expect(latest.direction).toBe('deduct');
    expect(latest.source).toBe('manual_deduct');

    await page.getByRole('tab', { name: '操作记录' }).click();
    await expect(page.getByText('R1').first()).toBeVisible({ timeout: 30_000 });
  });

  test('my-points rules modal hides M* and shows offline appeal copy', async ({ page }) => {
    await loginPortal(page, 'user');
    await page.goto('/points');
    await expect(page.getByText('我的积分').first()).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: '积分规则' }).click();
    await expect(page.getByRole('heading', { name: '积分规则' })).toBeVisible({
      timeout: 30_000,
    });
    // Public rules API already filters M*; assert modal copy does not surface monthly rewards.
    await expect(page.locator('#points-rules-title')).toBeVisible();
    await expect(page.getByText(/管理员月奖|月度奖励 M/)).toHaveCount(0);
    await expect(page.getByText(/线下/)).toBeVisible();
  });
});
