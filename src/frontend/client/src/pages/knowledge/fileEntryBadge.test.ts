import type { SpaceLevel } from "~/api/knowledge";
import { shouldShowFileEntryBadge } from "./fileEntryBadge";

test.each([
    ["manager", "personal", "active", false],
    ["manager", "personal", "invalid", true],
    ["publish", "personal", "active", true],
    ["share", "personal", "active", true],
    ["manager", "department", "active", true],
    ["manager", "team", "active", true],
    ["manager", "public", "active", true],
    ["normal", "personal", undefined, false],
    [undefined, "personal", undefined, false],
] as const)("%s / %s / %s 的文件标识可见性为 %s", (entryType, level, status, expected) => {
    expect(shouldShowFileEntryBadge(entryType, level as SpaceLevel, status)).toBe(expected);
});
