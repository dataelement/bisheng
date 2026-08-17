/** @jest-environment node */

import { readFileSync } from "node:fs";
import { join } from "node:path";

function source(file: string) {
  return readFileSync(join(process.cwd(), "src/components/permission", file), "utf8");
}

describe("F050 permission draft presentation contract", () => {
  it("keeps the 2.6 authorization tabs, list, and model menu", () => {
    const panel = source("PermissionDraftPanel.tsx");
    const editor = source("PermissionDraftEditor.tsx");
    expect(panel).toContain('data-testid="authorization-list"');
    expect(panel).toContain('data-testid="authorization-list-body"');
    expect(panel).toContain('const SUBJECT_TYPES: SubjectType[] = ["user", "department", "user_group"]');
    expect(editor).toContain("PermissionLevelMenu");
    expect(editor).toContain("row.protected");
    expect(editor).toContain("row.editable === false");
    expect(editor).toContain("row.modelKey");
    expect(editor).not.toContain("row.relation");
  });

  it("does not merge roster rows by subject", () => {
    const panel = source("PermissionDraftPanel.tsx");
    const draft = source("usePermissionDraft.ts");
    expect(panel).toContain("getPermissionDraftRowKey");
    expect(draft).toContain("row.assigneeId ??");
    expect(draft).toContain("sourceType?: string");
    expect(draft).toContain('scope?: "LOCAL" | "INHERITED"');
  });
});
