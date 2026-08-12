import { test, expect, type Page } from '@playwright/test';
import { loginPortal, loginPortalAs } from '../fixtures/auth';
import { runAccept11Trigger } from '../helpers/accept_test11';
import { runFactory } from '../helpers/factory';
import { runGm2Trigger } from '../helpers/gm2';
import { runGm4Trigger } from '../helpers/gm4';

/**
 * 测试1-1 组织高标准验收：G1–G7 / R1–R3 / M1–M8 全启用场景（约 90% 主路径）。
 * 用户：gzx0022(33)、gzx0023(34)、gzx0024(35)、gzx0025(36)；admin 管运维。
 *
 * 运行：
 *   E2E_POINTS_RUN_GATES=1 E2E_POINTS_PASSWORD=… npx playwright test gates/accept_test11.spec.ts
 */

const USERS = {
  u22: { name: 'gzx0022', id: 33 },
  u23: { name: 'gzx0023', id: 34 },
  u24: { name: 'gzx0024', id: 35 },
  u25: { name: 'gzx0025', id: 36 },
} as const;

const deptSpaceId = Number(process.env.E2E_POINTS_DEPT_SPACE_ID || '10');
const teamSpaceId = Number(process.env.E2E_POINTS_TEAM_SPACE_ID || '11');
const teamKsSpaceId = Number(process.env.E2E_POINTS_TEAM_KS_SPACE_ID || '12');
const adminUserId = Number(process.env.E2E_POINTS_ADMIN_USER_ID || '1');

const ALL_RULES = [
  'G1',
  'G2',
  'G3',
  'G4',
  'G5',
  'G6',
  'G7',
  'R1',
  'R2',
  'R3',
  'M1',
  'M2',
  'M3',
  'M4',
  'M5',
  'M6',
  'M7',
  'M8',
] as const;

/** 清 Cookie 后回到登录页，避免多用户串号。 */
async function resetPortalSession(page: Page): Promise<void> {
  await page.context().clearCookies();
  await page.goto('/login');
}

/** 打开积分管理并切到用户列表。 */
async function openPointsAdminUsers(page: Page): Promise<void> {
  await page.goto('/admin');
  await page.getByText('积分管理').click();
  await expect(page.getByText('用户积分管理')).toBeVisible({ timeout: 30_000 });
  await page.getByRole('tab', { name: '用户积分列表' }).click();
}

/**
 * 按用户名精确点开「违规扣减」，并选中指定 R* 规则。
 * @param page Playwright 页面
 * @param userName 门户用户名
 * @param userId 用户 ID（用于行过滤，避免同名误点）
 * @param ruleCode R1|R2|R3
 */
async function deductViaUi(
  page: Page,
  userName: string,
  userId: number,
  ruleCode: 'R1' | 'R2' | 'R3',
): Promise<void> {
  await page.locator('#points-user-search').fill(userName);
  const row = page
    .locator('tr', { hasText: userName })
    .filter({ hasText: String(userId) })
    .first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole('button', { name: '违规扣减' }).click();
  const dialog = page.getByRole('dialog', { name: '违规扣减' });
  await expect(dialog).toBeVisible();
  // 校验弹窗目标用户，避免 GM4 误点其它行（CSS Modules 类名不可靠）
  await expect(dialog.locator('input').first()).toHaveValue(userName);

  const ruleSelect = page.locator('#points-deduct-rule');
  await expect(ruleSelect.locator(`option[value="${ruleCode}"]`)).toHaveCount(1, {
    timeout: 15_000,
  });
  await ruleSelect.evaluate((el, code) => {
    const select = el as HTMLSelectElement;
    select.value = code;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }, ruleCode);
  await expect(ruleSelect).toHaveValue(ruleCode);
  await page.locator('#points-deduct-remark').fill(`accept_test11 ${ruleCode} ${userName}`);
  await page.getByRole('button', { name: '确认扣减' }).click();
  await expect(page.getByText(/扣减成功/)).toBeVisible({ timeout: 30_000 });
}

/** 断言「我的积分」页可见摘要与明细区。 */
async function assertMyPointsSummary(page: Page): Promise<void> {
  await page.goto('/points');
  await expect(page.getByText('我的积分').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('积分明细')).toBeVisible();
}

test.describe('accept_test11 测试1-1 积分验收', () => {
  // 主链路串行，避免多用户 Cookie / G1 beneficiary 互相干扰。
  test.describe.configure({ mode: 'serial' });
  test.skip(!process.env.E2E_POINTS_RUN_GATES, 'Set E2E_POINTS_RUN_GATES=1 when stack is up');

  test('preflight: all G*/R*/M* rules enabled', () => {
    const snap = runAccept11Trigger(['rules_snapshot']);
    expect(snap.ok).toBeTruthy();
    for (const code of ALL_RULES) {
      expect(snap.enabled).toEqual(expect.arrayContaining([code]));
    }
  });

  test('G1: publisher beneficiary awards to gzx0023', async ({ page }) => {
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

      // uploader=33 gzx0022，publisher=34 gzx0023 → 流水落在 34
      const award = runGm4Trigger([
        'award_g1_split',
        String(USERS.u22.id),
        String(USERS.u23.id),
      ]);
      expect(award.ok).toBeTruthy();
      expect(award.skipped).toBeFalsy();
      expect(award.beneficiary_config).toBe('publisher');
      const logs = (award.logs as Array<{ user_id: number; beneficiary_role: string }>) || [];
      expect(logs.length).toBe(1);
      expect(logs[0].user_id).toBe(USERS.u23.id);
      expect(logs[0].beneficiary_role).toBe('publisher');

      await resetPortalSession(page);
      await loginPortalAs(page, USERS.u23.name);
      await assertMyPointsSummary(page);
      await expect(page.getByText(/发布|公共库/).first()).toBeVisible({ timeout: 30_000 });
    } finally {
      runGm4Trigger(['set_beneficiary', 'G1', prevBeneficiary]);
    }
  });

  test('G2: department upload awards gzx0025 and is idempotent', async ({ page }) => {
    test.setTimeout(120_000);
    // 独立 file_id，避免与历史 Gate 冲突；Gate 默认强制同步入账
    const fileId = 940_000_000 + Math.floor(Math.random() * 90_000);
    const first = runGm2Trigger([
      'award_g2',
      String(USERS.u25.id),
      String(fileId),
      String(deptSpaceId),
    ]);
    const after = first.after as { count: number; balance: number; recent: { title: string }[] };
    const before = first.before as { count: number; balance: number };
    expect(after.count).toBe(before.count + 1);
    expect(after.balance).toBeGreaterThanOrEqual(before.balance + 1);

    const second = runGm2Trigger([
      'award_g2',
      String(USERS.u25.id),
      String(fileId),
      String(deptSpaceId),
    ]);
    const after2 = second.after as { count: number; balance: number };
    expect(after2.count).toBe(after.count);
    expect(after2.balance).toBe(after.balance);

    await loginPortalAs(page, USERS.u25.name);
    await assertMyPointsSummary(page);
    const title = after.recent[0]?.title || '部门';
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  });

  test('G2 negative: platform super-admin upload skipped', () => {
    const fileId = 941_000_000 + Math.floor(Math.random() * 90_000);
    const result = runGm2Trigger(['award_admin_g2', String(adminUserId), String(fileId)]);
    expect(result.skipped).toBeTruthy();
  });

  test('G3: favorite tier awards gzx0023', async ({ page }) => {
    test.setTimeout(120_000);
    const fileId = 942_000_000 + Math.floor(Math.random() * 90_000);
    const award = runFactory(['award_g3', String(USERS.u23.id), String(fileId)]);
    expect(award.ok).toBeTruthy();
    expect(award.skipped).toBeFalsy();
    const before = award.before as { count: number };
    const after = award.after as { count: number; recent: { title: string }[] };
    expect(after.count).toBe(before.count + 1);

    await loginPortalAs(page, USERS.u23.name);
    await assertMyPointsSummary(page);
    const title = after.recent[0]?.title || '收藏';
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  });

  test('G4: answer adopted awards gzx0024', async ({ page }) => {
    test.setTimeout(120_000);
    const answerId = 943_000_000 + Math.floor(Math.random() * 90_000);
    const award = runFactory(['award_g4', String(USERS.u24.id), String(answerId)]);
    expect(award.ok).toBeTruthy();
    expect(award.skipped).toBeFalsy();
    const before = award.before as { count: number };
    const after = award.after as { count: number; recent: { title: string }[] };
    expect(after.count).toBe(before.count + 1);

    await loginPortalAs(page, USERS.u24.name);
    await assertMyPointsSummary(page);
    const title = after.recent[0]?.title || '采纳';
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  });

  test('G5: team library upload awards gzx0022', async ({ page }) => {
    test.setTimeout(120_000);
    const fileId = 944_000_000 + Math.floor(Math.random() * 90_000);
    const award = runFactory([
      'award_g5',
      String(USERS.u22.id),
      String(fileId),
      String(teamSpaceId),
    ]);
    expect(award.ok).toBeTruthy();
    const before = award.before as { count: number };
    const after = award.after as { count: number; recent: { title: string }[] };
    expect(after.count).toBe(before.count + 1);

    await loginPortalAs(page, USERS.u22.name);
    await assertMyPointsSummary(page);
    const title = after.recent[0]?.title || '团队';
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  });

  test('G6: team_ks upload awards gzx0025', async ({ page }) => {
    test.setTimeout(120_000);
    const fileId = 945_000_000 + Math.floor(Math.random() * 90_000);
    const award = runFactory([
      'award_g6',
      String(USERS.u25.id),
      String(fileId),
      String(teamKsSpaceId),
    ]);
    expect(award.ok).toBeTruthy();
    const before = award.before as { count: number };
    const after = award.after as { count: number; recent: { title: string }[] };
    expect(after.count).toBe(before.count + 1);

    await loginPortalAs(page, USERS.u25.name);
    await assertMyPointsSummary(page);
    const title = after.recent[0]?.title || '科室';
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  });

  test('G7: inter-space share awards gzx0023', async ({ page }) => {
    test.setTimeout(120_000);
    const shareId = 946_000_000 + Math.floor(Math.random() * 90_000);
    const award = runFactory(['award_g7', String(USERS.u23.id), String(shareId)]);
    expect(award.ok).toBeTruthy();
    const before = award.before as { count: number };
    const after = award.after as { count: number; recent: { title: string }[] };
    expect(after.count).toBe(before.count + 1);

    await loginPortalAs(page, USERS.u23.name);
    await assertMyPointsSummary(page);
    const title = after.recent[0]?.title || '分享';
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  });

  test('R1–R3: admin UI deduct for three org users', async ({ page }) => {
    test.setTimeout(180_000);
    await loginPortal(page, 'admin');
    await openPointsAdminUsers(page);

    const cases: Array<{ user: (typeof USERS)[keyof typeof USERS]; rule: 'R1' | 'R2' | 'R3' }> =
      [
        { user: USERS.u22, rule: 'R1' },
        { user: USERS.u23, rule: 'R2' },
        { user: USERS.u24, rule: 'R3' },
      ];

    for (const c of cases) {
      await deductViaUi(page, c.user.name, c.user.id, c.rule);
      const latest = runGm4Trigger(['latest_deduct', String(c.user.id), c.rule]);
      expect(latest.ok).toBeTruthy();
      expect(latest.found).toBeTruthy();
      expect(Number(latest.delta)).toBeLessThan(0);
      expect(latest.direction).toBe('deduct');
      expect(latest.source).toBe('manual_deduct');
      // 关闭弹窗后列表仍在；清空搜索以便下一轮
      await page.locator('#points-user-search').fill('');
      await page.waitForTimeout(400);
    }

    await page.getByRole('tab', { name: '操作记录' }).click();
    await expect(page.getByText('R1').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('R2').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('R3').first()).toBeVisible({ timeout: 15_000 });
  });

  test('M1–M8: admin reward tab shows all enabled rules', async ({ page }) => {
    test.setTimeout(120_000);
    await loginPortal(page, 'admin');
    await page.goto('/admin');
    await page.getByText('积分管理').click();
    await expect(page.getByText('积分规则配置')).toBeVisible({ timeout: 30_000 });
    await page.getByRole('tab', { name: '管理员奖励' }).click();

    for (const code of ['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8'] as const) {
      const row = page.locator('tr', { hasText: code }).first();
      await expect(row).toBeVisible({ timeout: 30_000 });
      await expect(row.getByText(/启用|enabled/i).first()).toBeVisible();
    }
  });

  test('G1–G7: admin earn tab shows all enabled rules', async ({ page }) => {
    test.setTimeout(120_000);
    await loginPortal(page, 'admin');
    await page.goto('/admin');
    await page.getByText('积分管理').click();
    await expect(page.getByText('积分规则配置')).toBeVisible({ timeout: 30_000 });
    await page.getByRole('tab', { name: '积分获取规则' }).click();
    for (const code of ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7'] as const) {
      const row = page.locator('tr', { hasText: code }).first();
      await expect(row).toBeVisible({ timeout: 30_000 });
      await expect(row.getByText(/启用|enabled/i).first()).toBeVisible();
    }
  });

  test('M*: monthly engine awards for 2026-07 (idempotent re-run)', () => {
    const probe = runAccept11Trigger(['monthly_probe', '1', '2026-07']);
    expect(probe.ok).toBeTruthy();
    expect(probe.blocked).toBeFalsy();
    const result = probe.result as {
      awarded?: number;
      skipped?: number;
      error?: string;
      period_key?: string;
    };
    const ledger = (probe.ledger_by_rule || {}) as Record<
      string,
      { count: number; sum_delta: number }
    >;
    test.info().annotations.push({
      type: 'monthly_probe',
      description: JSON.stringify({
        blocked: probe.blocked,
        awarded: result.awarded,
        skipped: result.skipped,
        error: result.error,
        period_key: result.period_key || probe.period_key,
        ledger_by_rule: ledger,
      }),
    });
    // 首跑已实发；重跑应为幂等（awarded 可为 0，但流水仍在）
    expect(result.error).toBeFalsy();
    const totalLedger = Object.values(ledger).reduce((n, v) => n + Number(v.count || 0), 0);
    expect(totalLedger).toBeGreaterThan(0);
    // 至少覆盖多种 M*（环境无候选人的规则可缺失，但不能全空）
    expect(Object.keys(ledger).length).toBeGreaterThanOrEqual(3);
  });

  test('cross-cut: three org users open my-points', async ({ page }) => {
    test.setTimeout(180_000);
    for (const u of [USERS.u22, USERS.u23, USERS.u24]) {
      await resetPortalSession(page);
      await loginPortalAs(page, u.name);
      await assertMyPointsSummary(page);
    }
  });

});

test.describe('accept_test11 规则弹窗文案', () => {
  test.skip(!process.env.E2E_POINTS_RUN_GATES, 'Set E2E_POINTS_RUN_GATES=1 when stack is up');

  test('rules modal hides M* and shows appeal copy', async ({ page }) => {
    await loginPortalAs(page, USERS.u22.name);
    await page.goto('/points');
    await expect(page.getByText('我的积分').first()).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: '积分规则' }).click();
    await expect(page.getByRole('heading', { name: '积分规则' })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator('#points-rules-title')).toBeVisible();
    await expect(page.getByText(/管理员月奖|月度奖励 M|公共库所有者月奖/)).toHaveCount(0);
    // 产品文案当前为「申诉」；「线下」为高标准期望，缺失则本用例失败并记入报告
    await expect(page.getByText(/申诉|线下/)).toBeVisible({ timeout: 5_000 });
  });

  test('rules modal offline-appeal keyword (strict)', async ({ page }) => {
    await loginPortalAs(page, USERS.u22.name);
    await page.goto('/points');
    await page.getByRole('button', { name: '积分规则' }).click();
    await expect(page.locator('#points-rules-title')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/线下/)).toBeVisible({ timeout: 5_000 });
  });
});
