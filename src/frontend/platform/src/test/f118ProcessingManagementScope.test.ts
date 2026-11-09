import { describe, expect, it } from "vitest";

import { requiresManagementScope } from "@/controllers/managementScope";

describe("F118 processing command management scope", () => {
  it.each([
    ["POST", "/api/v1/knowledge/space/42/copy/precheck"],
    ["POST", "/api/v1/knowledge/space/42/copy/confirm"],
    ["PUT", "/api/v1/knowledge/space/42/processing-settings"],
    ["POST", "/api/v1/knowledge/space/42/processing-jobs"],
    ["POST", "/api/v1/knowledge/space/42/processing-jobs/precheck"],
    ["POST", "/api/v1/knowledge/space/42/processing-jobs/job-42/retry"],
    ["post", "/api/v1/knowledge/space/42/processing-jobs/job-42/retry/"],
  ])("AC-04/05: pins the selected tenant for %s %s", (method, path) => {
    expect(requiresManagementScope(method, path)).toBe(true);
  });

  it.each([
    ["GET", "/api/v1/knowledge/space/42/processing-settings"],
    ["GET", "/api/v1/knowledge/space/42/processing-jobs"],
    ["GET", "/api/v1/knowledge/space/42/processing-jobs/job-42"],
    ["GET", "/api/v1/knowledge/space/42/processing-jobs/job-42/items"],
    ["POST", "/api/v1/knowledge/space/42/files"],
    ["POST", "/api/v1/knowledge/space/42/files/batch-delete"],
    ["POST", "/api/v1/knowledge/space/42/files/move"],
    ["PUT", "/api/v1/knowledge/space/42/files/10"],
    ["PUT", "/api/v1/knowledge/space/42/files/10/encoding"],
    ["POST", "/api/v1/knowledge/space/42/files/10/tag"],
    ["POST", "/api/v1/knowledge/space/42/files/batch-download"],
    ["POST", "/api/v1/knowledge/space/42/files/batch-tag"],
    ["POST", "/api/v1/knowledge/space/42/files/batch-retry"],
    ["POST", "/api/v1/knowledge/space/42/files/retry"],
    ["POST", "/api/v1/knowledge/space/42/folders"],
    ["POST", "/api/v1/knowledge/space/42/folders/upload"],
    ["PUT", "/api/v1/knowledge/space/42/folders/10"],
    ["DELETE", "/api/v1/knowledge/space/42/folders/10"],
    ["DELETE", "/api/v1/knowledge/space/42/files/10"],
    ["POST", "/api/v2/filelib/42/upload"],
    ["POST", "/api/v2/workflow/invoke"],
    ["POST", "/api/v1/knowledge/space/42/processing-jobs/job-42/items"],
    ["POST", "/api/v1/knowledge/space/42/processing-jobs/job-42/retry/extra"],
    ["POST", "/api/v1/knowledge/space/42/processing-settings"],
  ])(
    "AC-33/35/84: preserves the existing ordinary-call boundary for %s %s",
    (method, path) => {
      expect(requiresManagementScope(method, path)).toBe(false);
    },
  );
});
