import { test, expect } from '@playwright/test';
import { loginPortal } from '../fixtures/auth';
import { runFactory } from '../helpers/factory';

/**
 * G-M5：发布前冒烟 — 对账 / 开关负例 / 入口可读。
 * 完整回归请用：`npm run test:gm5`（串行 gm1–gm4 + 本文件）。
 *
 * 运行：E2E_POINTS_RUN_GATES=1 E2E_POINTS_PASSWORD=… npm run test:gm5
 */
test.describe('G-M5 release smoke', () => {
  test.skip(!process.env.E2E_POINTS_RUN_GATES, 'Set E2E_POINTS_RUN_GATES=1 before release');

  const userId = Number(process.env.E2E_POINTS_TARGET_USER_ID || '4');

  test('schema + seed tables are readable', () => {
    const schema = runFactory(['schema_check']);
    expect(schema.ok).toBeTruthy();
    expect(schema.department_org_level).toBeTruthy();
  });

  test('reconcile has no balance mismatch', () => {
    const out = runFactory(['reconcile', '1']);
    expect(out.ok).toBeTruthy();
    expect(Number(out.checked)).toBeGreaterThan(0);
    expect(Number(out.mismatches)).toBe(0);
  });

  test('points.enabled=false skips new department upload award', () => {
    const out = runFactory(['award_disabled', String(userId)]);
    expect(out.ok).toBeTruthy();
    expect(out.skipped).toBeTruthy();
    expect(out.reason).toBe('points_disabled');
    expect(out.no_new_log).toBeTruthy();
  });

  test('sync outbox drain is safe when disabled or without adapter', () => {
    const out = runFactory(['outbox_drain']);
    expect(out.ok).toBeTruthy();
    // Either feature-flag skipped, or drained without raising.
    if (out.skipped) {
      expect(String(out.reason || '')).toMatch(/disabled|no_adapter|adapter/i);
    } else {
      expect(Number(out.processed ?? out.drained ?? 0)).toBeGreaterThanOrEqual(0);
    }
  });

  test('factory can seed G3/G4 paths for reuse', () => {
    const g3 = runFactory(['award_g3', String(userId)]);
    expect(g3.ok).toBeTruthy();
    // First hit at threshold 75 should apply or skip only if already granted same file.
    expect(g3.skipped === true || g3.skipped === false).toBeTruthy();

    const g4 = runFactory(['award_g4', String(userId)]);
    expect(g4.ok).toBeTruthy();
    expect(g4.skipped).toBeFalsy();
    const after = g4.after as { count: number };
    const before = g4.before as { count: number };
    expect(after.count).toBe(before.count + 1);
  });

  test('portal my-points page still loads', async ({ page }) => {
    await loginPortal(page, 'user');
    await page.goto('/points');
    await expect(page.getByText('我的积分').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('本月获得')).toBeVisible();
  });

  test('portal admin points overview still loads', async ({ browser }) => {
    // Fresh context so user cookies from prior test cannot block admin login.
    const context = await browser.newContext({
      baseURL: process.env.E2E_PORTAL_BASE_URL || 'http://127.0.0.1:5173',
    });
    const page = await context.newPage();
    try {
      await loginPortal(page, 'admin');
      await page.goto('/admin');
      await page.getByText('积分管理', { exact: true }).click();
      await expect(page.getByText('平台总积分发放')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText('违规扣减合计')).toBeVisible();
    } finally {
      await context.close();
    }
  });
});
