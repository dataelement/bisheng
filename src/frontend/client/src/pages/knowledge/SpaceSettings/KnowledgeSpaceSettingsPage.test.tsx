/** @jest-environment node */

import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(
  join(process.cwd(), "src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.tsx"),
  "utf8",
);

describe("F050 knowledge full-page UI contract", () => {
  it("keeps business, auto-tag, visibility, and authorization sections", () => {
    expect(source).toContain("SettingsSectionHeader");
    expect(source).toContain("autoTagFeatureVisible");
    expect(source).toContain("autoTagLibraryId");
    expect(source).toContain("autoTagCustomText");
    expect(source).toContain("PermissionDraftPanel");
    expect(source).toContain("CreatedPermissionFailureState");
  });

  it("keeps the narrow-screen full-page layout and fixed action region", () => {
    expect(source).toContain("max-[768px]:px-0");
    expect(source).toContain("min-h-0 flex-1 overflow-y-auto");
    expect(source).toContain("SettingsFooter");
  });

  it("does not expose the member roster without manage permission", () => {
    expect(source).toContain("settings.canManagePermissions");
    expect(source).toContain("settings.canAddNonUserSubjects");
    expect(source).not.toContain("manage_space_relation");
  });
});
