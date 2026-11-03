import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: ".",
    reporter: "line",
    use: { trace: "off" },
});
