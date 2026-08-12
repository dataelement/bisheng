import { test, expect } from '@playwright/test';
import { loginPortal } from '../fixtures/auth';
import { runGm2Trigger } from '../helpers/gm2';

/**
 * G-M2：自动发放主路径（API 造数 + Portal「我的积分」明细断言）。
 * 运行：E2E_POINTS_RUN_GATES=1 E2E_POINTS_PASSWORD=… npm run test:gm2
 */
test.describe('G-M2 auto award', () => {
  test.skip(!process.env.E2E_POINTS_RUN_GATES, 'Set E2E_POINTS_RUN_GATES=1 when stack is up');

  const userId = Number(process.env.E2E_POINTS_TARGET_USER_ID || '4');
  const adminId = Number(process.env.E2E_POINTS_ADMIN_USER_ID || '1');
  const deptSpaceId = Number(process.env.E2E_POINTS_DEPT_SPACE_ID || '10');

  test.beforeAll(() => {
    const ensured = runGm2Trigger(['ensure_g7']);
    expect(ensured.ok).toBeTruthy();
  });

  test('department upload awards G2 and is idempotent', async ({ page }) => {
    const fileId = 970000 + Math.floor(Math.random() * 9000);
    const first = runGm2Trigger(['award_g2', String(userId), String(fileId), String(deptSpaceId)]);
    const after = first.after as { count: number; balance: number; recent: { title: string; delta: number }[] };
    const before = first.before as { count: number; balance: number };
    expect(after.count).toBe(before.count + 1);
    expect(after.balance).toBeGreaterThanOrEqual(before.balance + 1);
    expect(after.recent[0]?.delta).toBeGreaterThan(0);

    const second = runGm2Trigger(['award_g2', String(userId), String(fileId), String(deptSpaceId)]);
    const after2 = second.after as { count: number; balance: number };
    expect(after2.count).toBe(after.count);
    expect(after2.balance).toBe(after.balance);

    await loginPortal(page, 'user');
    await page.goto('/points');
    await expect(page.getByText('我的积分').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('积分明细')).toBeVisible();
    // DB 中 G2 名称可能被运营改过；用流水标题或「部门」关键字兜底。
    const title = after.recent[0]?.title || '部门';
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  });

  test('inter-space SHARE awards G7 when rule enabled', async ({ page }) => {
    const shareId = 980000 + Math.floor(Math.random() * 9000);
    const result = runGm2Trigger(['award_g7', String(userId), String(shareId)]);
    const after = result.after as { count: number; recent: { title: string }[] };
    const before = result.before as { count: number };
    expect(after.count).toBe(before.count + 1);

    await loginPortal(page, 'user');
    await page.goto('/points');
    await expect(page.getByText(after.recent[0]?.title || '文档库间分享').first()).toBeVisible({
      timeout: 30_000,
    });
  });

  test('outer share-link does not create G7 ledger by link id', async () => {
    const fakeLinkId = 990000 + Math.floor(Math.random() * 9000);
    // 外链路径未挂 Facade；仅断言不会出现 earn:G7:{link_id}。
    const snap = runGm2Trigger(['share_link_neg', String(userId), String(fakeLinkId)]);
    expect(snap.count).toBe(0);
  });

  test('platform super-admin upload gets no auto G2', async () => {
    const fileId = 991000 + Math.floor(Math.random() * 9000);
    const result = runGm2Trigger(['award_admin_g2', String(adminId), String(fileId)]);
    expect(result.skipped).toBeTruthy();
  });
});
