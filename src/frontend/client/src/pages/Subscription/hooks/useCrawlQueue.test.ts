/** @jest-environment node */

import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(
  join(process.cwd(), "src/pages/Subscription/hooks/useCrawlQueue.ts"),
  "utf8",
);

describe("2.6 crawl queue regression contract", () => {
  it("preserves bounded queueing, cancellation, failure, and preview", () => {
    expect(source).toContain("const CONCURRENCY = 3");
    expect(source).toContain('status: "pending"');
    expect(source).toContain('status: "crawling"');
    expect(source).toContain('status: "success"');
    expect(source).toContain('status: "failed"');
    expect(source).toContain("abortController.abort()");
    expect(source).toContain("preview");
  });

  it("keeps transient crawl and durable source creation as separate steps", () => {
    expect(source.lastIndexOf("crawlTempSourceApi")).toBeLessThan(
      source.lastIndexOf("addWebsiteSourceApi"),
    );
    expect(source).toContain("onSourceAddedRef.current(source)");
    expect(source).toContain("API_KEY_LIMIT_CODE");
  });
});
