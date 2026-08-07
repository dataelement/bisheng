import { defineConfig, devices } from '@playwright/test';

/**
 * F070 积分阶段性验收门禁（Portal UI）。
 * 中间件：192.168.106.171；应用本机起栈（见 README）。
 */
const portalBase = process.env.E2E_PORTAL_BASE_URL || 'http://127.0.0.1:5173';

export default defineConfig({
  testDir: './gates',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  outputDir: 'test-results',
  use: {
    baseURL: portalBase,
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    locale: 'zh-CN',
  },
  projects: [
    {
      name: 'points-gates',
      // Prefer installed Google Chrome to avoid flaky chromium zip downloads.
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],
});
