/** @jest-environment node */

import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(
  join(process.cwd(), "src/pages/Subscription/ChannelSettings/ChannelSettingsPage.tsx"),
  "utf8",
);
const businessSource = readFileSync(
  join(process.cwd(), "src/pages/Subscription/ChannelSettings/ChannelBusinessSettings.tsx"),
  "utf8",
);

describe("F050 channel full-page UI contract", () => {
  it("keeps the 2.6 business, crawl, sync, and authorization regions", () => {
    expect(source).toContain("ChannelBusinessSettings");
    expect(source).toContain("ChannelPermissionSettings");
    expect(source).toContain("useCrawlQueue");
    expect(source).toContain("CrawlPreviewDialog");
    expect(source).toContain("CrawlFeedbackDialog");
    expect(businessSource).toContain("knowledgeSync");
  });

  it("keeps responsive two-column layout and blocks submit during crawl", () => {
    expect(source).toContain("grid grid-cols-2 items-start gap-10 max-[900px]:grid-cols-1");
    expect(source).toContain("min-h-0 flex-1 overflow-y-auto");
    expect(source).toContain("disabled={crawlQueue.inProgressCount > 0}");
    expect(source).toContain("SettingsFooter");
  });

  it("uses domain-scoped creation candidates and hides unauthorized roster", () => {
    expect(source).toContain('searchCreationUsers("channel"');
    expect(source).toContain('getCreationDepartmentChildren("channel"');
    expect(source).toContain("settings.showPermissionSection");
    expect(source).not.toContain("permission_ids");
  });
});
