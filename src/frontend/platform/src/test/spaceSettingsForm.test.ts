import { expect, it } from "vitest";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import {
  parseSpaceTags,
  spaceSettingsDraft,
  spaceSettingsPayload,
  validSpaceSettings,
} from "@/pages/KnowledgePage/components/spaceSettingsForm";
const info: KnowledgeSpaceInfo = {
  id: 7,
  name: "space",
  auth_type: "approval",
  is_released: true,
  auto_tag_enabled: true,
  auto_tag_mode: "custom",
  auto_tag_custom_tags: ["first", "second"],
};
it("restores saved custom tags without inventing a library binding", () => {
  expect(spaceSettingsDraft(info)).toMatchObject({
    customText: "first\nsecond",
    tagMode: "custom",
    libraryId: null,
  });
});
it("does not guess missing access/publication configuration", () => {
  expect(spaceSettingsDraft({ ...info, auth_type: undefined })).toBeNull();
  expect(spaceSettingsDraft({ ...info, is_released: undefined })).toBeNull();
});
it("preserves sharing and tags when those controls were not available or touched", () => {
  const draft = spaceSettingsDraft(info)!;
  draft.auth = "private";
  draft.autoTag = false;
  const payload = spaceSettingsPayload(draft, info, false, false);
  expect(payload).toEqual({
    name: "space",
    description: "",
    is_released: true,
  });
});
it("unpublishes private spaces and explicitly clears obsolete tag bindings", () => {
  const draft = spaceSettingsDraft(info)!;
  draft.auth = "private";
  draft.autoTag = false;
  expect(spaceSettingsPayload(draft, info, true, true)).toMatchObject({
    auth_type: "private",
    is_released: false,
    auto_tag_enabled: false,
    auto_tag_library_id: null,
    auto_tag_custom_tags: null,
  });
});
it("rejects over 200 custom tags rather than silently truncating user input", () => {
  const draft = spaceSettingsDraft(info)!;
  draft.customText = Array.from({ length: 201 }, (_, i) => `tag${i}`).join(
    "\n",
  );
  expect(validSpaceSettings(draft, true)).toBe(false);
  expect(parseSpaceTags(draft.customText)).toHaveLength(201);
});
it("normalizes duplicate tags and distinguishes shared/custom binding payloads", () => {
  const draft = spaceSettingsDraft(info)!;
  draft.customText = " one \r\none\ntwo";
  expect(
    spaceSettingsPayload(draft, info, true, true).auto_tag_custom_tags,
  ).toEqual(["one", "two"]);
  draft.tagMode = "library";
  draft.libraryId = 18;
  expect(spaceSettingsPayload(draft, info, true, true)).toMatchObject({
    auto_tag_library_id: 18,
    auto_tag_custom_tags: null,
  });
});
