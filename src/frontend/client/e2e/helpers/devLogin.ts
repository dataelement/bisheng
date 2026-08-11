import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

/** 通过 Client 隐藏 Dev Login 页登录（依赖 backend :7860）。 */
/** 通过 Client 隐藏 Dev Login 页登录（路由在 /workspace 之外）。 */
export async function devLogin(
    page: Page,
    username = process.env.E2E_ADMIN_USER ?? "admin",
    password = process.env.E2E_ADMIN_PASSWORD ?? "Bisheng@top1",
): Promise<void> {
    const origin = process.env.E2E_CLIENT_ORIGIN ?? "http://127.0.0.1:4001";
    await page.goto(`${origin}/workspace/__dev/login`);
    await page.getByPlaceholder("账号 / email").fill(username);
    await page.getByPlaceholder("密码").fill(password);
    await page.getByRole("button", { name: /登录/ }).click();
    await page.waitForURL(/\/(c\/new|knowledge)/, { timeout: 30_000 });
    await expect(page.locator("body")).toBeVisible();
}
