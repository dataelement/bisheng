import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import type { SpaceSettingsUpdate } from "@/controllers/API/knowledgeSpaceSettings";
export const SPACE_NAME_LIMIT = 10;
export const SPACE_DESCRIPTION_LIMIT = 200;

// Match the client settings' full-width units: ASCII is half a unit.
export function getSpaceTextLength(value: string): number {
  let length = 0;
  for (const character of value) {
    length += character.charCodeAt(0) <= 0x7f ? 0.5 : character.length;
  }
  return length;
}
export function truncateSpaceText(value: string, limit: number): string {
  let length = 0,
    end = 0;
  for (const character of value) {
    length += character.charCodeAt(0) <= 0x7f ? 0.5 : character.length;
    if (length > limit) break;
    end += character.length;
  }
  return value.slice(0, end);
}
export interface SpaceSettingsDraft {
  name: string;
  description: string;
  auth: "private" | "public" | "approval";
  released: boolean;
  autoTag: boolean;
  tagMode: "library" | "custom";
  libraryId: number | null;
  customText: string;
}
export function spaceSettingsDraft(
  info: KnowledgeSpaceInfo,
): SpaceSettingsDraft | null {
  if (
    !["private", "public", "approval"].includes(info.auth_type ?? "") ||
    typeof info.is_released !== "boolean"
  )
    return null;
  return {
    name: info.name,
    description: info.description ?? "",
    auth: info.auth_type!,
    released: info.is_released,
    autoTag: Boolean(info.auto_tag_enabled),
    tagMode: info.auto_tag_mode ?? "library",
    libraryId: info.auto_tag_library_id ?? null,
    customText: (info.auto_tag_custom_tags ?? []).join("\n"),
  };
}
export function parseSpaceTags(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/\r?\n/)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ];
}
export function validSpaceSettings(
  value: SpaceSettingsDraft,
  tagsTouched: boolean,
): boolean {
  return (
    Boolean(value.name.trim()) &&
    getSpaceTextLength(value.name) <= SPACE_NAME_LIMIT &&
    getSpaceTextLength(value.description) <= SPACE_DESCRIPTION_LIMIT &&
    (!tagsTouched ||
      !value.autoTag ||
      (value.tagMode === "custom"
        ? parseSpaceTags(value.customText).length > 0 &&
          parseSpaceTags(value.customText).length <= 200
        : Number.isSafeInteger(value.libraryId) && value.libraryId! > 0))
  );
}
export function spaceSettingsPayload(
  value: SpaceSettingsDraft,
  original: KnowledgeSpaceInfo,
  canShare: boolean,
  tagsTouched: boolean,
): SpaceSettingsUpdate {
  return {
    name: value.name.trim(),
    description: value.description.trim(),
    is_released: canShare
      ? value.auth === "private"
        ? false
        : value.released
      : original.is_released!,
    ...(canShare ? { auth_type: value.auth } : {}),
    ...(tagsTouched
      ? {
          auto_tag_enabled: value.autoTag,
          auto_tag_library_id:
            value.autoTag && value.tagMode === "library"
              ? value.libraryId
              : null,
          auto_tag_custom_tags:
            value.autoTag && value.tagMode === "custom"
              ? parseSpaceTags(value.customText)
              : null,
        }
      : {}),
  };
}
