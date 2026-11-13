import { expect, it } from "vitest";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import {
  parseSpaceTags,
  spaceSettingsDraft,
  spaceSettingsPayload,
  validSpaceSettings,
  getSpaceTextLength,
  truncateSpaceText,
} from "@/pages/KnowledgePage/components/spaceSettingsForm";
// CJK input samples for character-width validation, independent of UI copy.
const ideograph = String.fromCodePoint(0x4e00);
const info: KnowledgeSpaceInfo = {
  id: 7,
  name: "space",
  auth_type: "approval",
  is_released: true,
  auto_tag_enabled: true,
  auto_tag_mode: "custom",
  auto_tag_custom_tags: ["first", "second"],
};
it("matches the client's full-width name and description limits", () => {
  const draft = spaceSettingsDraft(info)!;
  draft.name = "a".repeat(20);
  draft.description = "b".repeat(400);
  expect(validSpaceSettings(draft, false)).toBe(true);
  draft.name += "a";
  expect(validSpaceSettings(draft, false)).toBe(false);
  draft.name = ideograph.repeat(10);
  draft.description = ideograph.repeat(200);
  expect(validSpaceSettings(draft, false)).toBe(true);
  draft.description += ideograph;
  expect(validSpaceSettings(draft, false)).toBe(false);
});
it("truncates mixed text in full-width units without splitting a surrogate pair", () => {
  expect(getSpaceTextLength(ideograph.repeat(2) + "world")).toBe(4.5);
  expect(truncateSpaceText(ideograph.repeat(9) + "abc", 10)).toBe(
    ideograph.repeat(9) + "ab",
  );
  expect(truncateSpaceText(ideograph.repeat(9) + "😀", 10)).toBe(
    ideograph.repeat(9),
  );
});
it("does not silently truncate a saved long name when opening settings", () => {
  const draft = spaceSettingsDraft({ ...info, name: "a".repeat(21) })!;
  expect(draft.name).toHaveLength(21);
  expect(validSpaceSettings(draft, false)).toBe(false);
});
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
