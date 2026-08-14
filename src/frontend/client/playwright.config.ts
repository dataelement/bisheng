import { defineConfig } from "@playwright/test";
import path from "node:path";
import os from "node:os";

const CLIENT_ORIGIN = process.env.E2E_CLIENT_ORIGIN ?? "http://127.0.0.1:4001";
const CLIENT_BASE = process.env.E2E_CLIENT_BASE_URL ?? `${CLIENT_ORIGIN}/workspace`;

/** 优先使用已下载的 Playwright Chromium，避免 headless_shell 未装完导致 launch 失败。 */
function resolveChromiumExecutable(): string | undefined {
    if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
        return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
    }
    const home = os.homedir();
    const candidates = [
        path.join(home, "Library/Caches/ms-playwright/chromium-1148/chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
        path.join(home, ".cache/ms-playwright/chromium-1148/chrome-linux/chrome"),
    ];
    for (const candidate of candidates) {
        try {
            if (require("node:fs").existsSync(candidate)) return candidate;
        } catch {
            /* ignore */
        }
    }
    return undefined;
}

const chromiumExecutable = resolveChromiumExecutable();

export default defineConfig({
    testDir: "./e2e",
    timeout: 90_000,
    expect: { timeout: 15_000 },
    fullyParallel: false,
    retries: process.env.CI ? 1 : 0,
    reporter: [["list"]],
    use: {
        baseURL: CLIENT_BASE,
        trace: "on-first-retry",
        screenshot: "only-on-failure",
    },
    projects: [
        {
            name: "chromium",
            use: {
                channel: "chrome",
                headless: true,
            },
        },
    ],
});
