/** @jest-environment node */

import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(
  join(process.cwd(), "src/pages/knowledge/SpaceSettings/useKnowledgeSpaceSettingsForm.ts"),
  "utf8",
);

describe("F050 knowledge settings orchestration contract", () => {
  it("retains all knowledge business fields and F048 initial grants", () => {
    for (const field of [
      "auto_tag_enabled",
      "auto_tag_library_id",
      "auto_tag_custom_tags",
      "auth_type",
      "is_released",
    ]) expect(source).toContain(field);
    expect(source).toContain('getCreationPermissionContext("knowledge_space")');
    expect(source).toContain("expected_catalog_release_id: catalogReleaseId");
    expect(source).toContain("creationRequestId: creationRequestIdRef.current");
  });

  it("saves business first and mutates only touched F048 changes", () => {
    expect(source.indexOf("updateSpaceApi(spaceId, payload)")).toBeLessThan(
      source.indexOf('mutateResourceGrants("knowledge_space"'),
    );
    expect(source).toContain("changes: permissionDiff.changes");
    expect(source).toContain('const latestContext = await getResourcePermissionContext("knowledge_space", spaceId)');
    expect(source).toContain("expected_resource_version: latestContext.resource_version");
    expect(source).not.toContain("authorizeResource");
    expect(source).not.toContain("manage_space_relation");
  });
});
