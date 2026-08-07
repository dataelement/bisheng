import { expect, type Page } from '@playwright/test';

/**
 * 从环境变量读取积分 Gate 账号（密码不写死在 spec 里）。
 * @param kind admin=平台超管 / user=普通用户
 */
export function pointsCredentials(kind: 'admin' | 'user') {
  const password = process.env.E2E_POINTS_PASSWORD;
  if (!password) {
    throw new Error('E2E_POINTS_PASSWORD is required for Gate runs');
  }
  if (kind === 'admin') {
    return {
      username: process.env.E2E_POINTS_ADMIN || 'admin',
      password,
    };
  }
  return {
    username: process.env.E2E_POINTS_USER || 'gzx01',
    password,
  };
}

/**
 * 登录 Portal。
 * @param page Playwright 页面
 * @param kind 账号类型
 */
export async function loginPortal(page: Page, kind: 'admin' | 'user'): Promise<void> {
  const { username, password } = pointsCredentials(kind);
  // Portal 登录页在 /login；首页仅有入口按钮，无账号输入框。
  await page.goto('/login');
  const userInput = page.getByRole('textbox', { name: '账号' });
  const passInput = page.getByRole('textbox', { name: '密码' });
  await expect(userInput).toBeVisible({ timeout: 30_000 });
  await userInput.fill(username);
  await passInput.fill(password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 30_000 });
}
