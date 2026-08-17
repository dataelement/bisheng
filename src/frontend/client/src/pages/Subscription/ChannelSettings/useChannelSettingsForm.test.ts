/** @jest-environment node */

import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(
  join(process.cwd(), "src/pages/Subscription/ChannelSettings/useChannelSettingsForm.ts"),
  "utf8",
);

describe("F050 channel settings orchestration contract", () => {
  it("retains channel source, filter, subchannel, and knowledge sync payloads", () => {
    expect(source).toContain("buildCreateChannelPayload(formData)");
    expect(source).toContain("buildChannelSettingsUpdatePayload(formData, isChannelCreator)");
    expect(source).toContain("knowledgeSync");
    expect(source).toContain("contentFilter");
    expect(source).toContain("subChannels");
  });

  it("uses effective actions and versioned F048 mutation only", () => {
    expect(source).toContain('detail?.actions?.includes("edit")');
    expect(source).toContain('detail?.actions?.includes("manage_permission")');
    expect(source).toContain('getCreationPermissionContext("channel")');
    expect(source).toContain('mutateResourceGrants("channel"');
    expect(source).toContain("changes: permissionDraft.diff.changes");
    expect(source).not.toContain("permission_ids");
    expect(source).not.toContain("authorizeChannelApi");
  });
});
