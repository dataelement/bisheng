/** @jest-environment node */

import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(
  join(process.cwd(), "src/components/permission/PermissionDraftPickerDialog.tsx"),
  "utf8",
);

describe("F050 permission subject picker contract", () => {
  it("preserves the 2.6 multi-subject selection flow", () => {
    expect(source).toContain('<TabsTrigger value="user"');
    expect(source).toContain('value="department"');
    expect(source).toContain('value="user_group"');
    expect(source).toContain("includeChildren");
    expect(source).toContain("onConfirm(subjects.map");
  });

  it("uses injectable create/edit candidate adapters and F048 models", () => {
    expect(source).toContain("searchApi?: PermissionDraftSearchApi");
    expect(source).toContain("usersApi={searchApi?.usersApi}");
    expect(source).toContain("departmentChildrenApi={searchApi?.departmentChildrenApi}");
    expect(source).toContain("userGroupsApi={searchApi?.userGroupsApi}");
    expect(source).toContain("modelKey: activeModel.id");
    expect(source).not.toContain("modelId:");
    expect(source).not.toContain("relation:");
  });
});
