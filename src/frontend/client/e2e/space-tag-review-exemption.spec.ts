/**
 * 浏览器 E2E：编辑标签弹窗 — 免审 vs 待审 UI 与保存请求。
 *
 * 环境变量：
 *   E2E_SPACE_ID — 知识库 ID（必填）
 *   E2E_FILE_ID — 文件 ID（必填）
 *   E2E_CLIENT_BASE_URL — 默认 http://127.0.0.1:4001/workspace
 *   E2E_ADMIN_USER / E2E_ADMIN_PASSWORD
 */
import { test, expect } from "@playwright/test";
import { devLogin } from "./helpers/devLogin";

const spaceId = process.env.E2E_SPACE_ID;
const fileId = process.env.E2E_FILE_ID;

test.describe("Space tag review exemption browser UI", () => {
    test.skip(!spaceId || !fileId, "set E2E_SPACE_ID and E2E_FILE_ID to run browser UI e2e");

    test.beforeEach(async ({ page }) => {
        await devLogin(page);
    });

    test("UI-BRW-01: public 库管理员新建标签保存走 tag_ids（免审）", async ({ page }) => {
        const tagName = `e2e-ui-exempt-${Date.now()}`;
        let savePayload: { tag_ids?: number[]; review_tag_ids?: number[] } | null = null;

        await page.route("**/api/v1/knowledge/space/*/files/*/tag", async (route) => {
            if (route.request().method() === "POST") {
                savePayload = route.request().postDataJSON();
            }
            await route.continue();
        });

        await page.goto(`/knowledge/space/${spaceId}`);
        await page.waitForLoadState("networkidle");

        const row = page.getByTestId(`file-tree-row-${fileId}`);
        await row.hover();
        await row.getByTitle(/edit_tags|编辑标签/).click({ force: true });

        await expect(page.getByTestId("edit-tags-dialog")).toBeVisible({ timeout: 20_000 });

        const input = page.locator("#tag-input");
        await input.fill(tagName);
        await input.press("Enter");
        await page.getByRole("button", { name: /confirm|确认/ }).click();

        await expect.poll(() => savePayload, { timeout: 30_000 }).not.toBeNull();
        expect((savePayload?.review_tag_ids ?? []).length).toBe(0);
        expect((savePayload?.tag_ids ?? []).length).toBeGreaterThan(0);

        // 输入区 chip 应为已通过色（非待审灰字 class）
        const chip = page.getByTestId("edit-tags-dialog-body").getByText(tagName, { exact: true }).first();
        await expect(chip).toBeVisible();
        const chipClass = (await chip.evaluate((el) => el.parentElement?.className)) ?? "";
        expect(chipClass).toContain("text-[#4e5969]");
    });
});
