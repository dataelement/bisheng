import { readFileSync } from "fs";
import { join } from "path";

const src = readFileSync(join(__dirname, "KnowledgeSpaceSidebar.tsx"), "utf8");

describe("KnowledgeSpaceSidebar — personal space actions", () => {
  it("computes isPersonal from spaceLevel in getItemPermissions", () => {
    expect(src).toMatch(/space\.spaceLevel\s*===\s*SpaceLevel\.PERSONAL/);
  });
  it("forces delete/manageMembers false for personal spaces", () => {
    expect(src).toMatch(/canDeleteSpace:\s*isPersonal\s*\?\s*false/);
    expect(src).toMatch(/canManageMembers:\s*isPersonal\s*\?\s*false/);
  });
});
