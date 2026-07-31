import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const LOCALES = ["zh-Hans", "en", "ja"] as const;
const COMPONENTS = [
  "src/components/permission/ModeHeader.tsx",
  "src/components/permission/PermissionDialog.tsx",
  "src/components/permission/PermissionGrantTab.tsx",
  "src/components/permission/PermissionListTab.tsx",
  "src/components/permission/SourceBadge.tsx",
  "src/pages/Subscription/ChannelPermissionDialog.tsx",
] as const;

const REQUIRED_KEYS = [
  "mode.custom",
  "mode.inherit",
  "mode.label",
  "mode.inherit_description",
  "mode.custom_description",
  "mode.confirm",
  "source.direct",
  "source.department",
  "source.user_group",
  "source.include_children",
  "scope.local",
  "scope.inherited",
  "roster.protected",
  "model.level",
  "impact.title",
  "impact.expired",
  "error.version_conflict",
  "error.projection_failed",
  "error.migration_blocked",
] as const;

function flattenKeys(
  value: Record<string, unknown>,
  prefix = "",
): string[] {
  return Object.entries(value).flatMap(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (item && typeof item === "object" && !Array.isArray(item)) {
      return flattenKeys(item as Record<string, unknown>, path);
    }
    return [path];
  });
}

function loadF048Locale(
  locale: (typeof LOCALES)[number],
): Record<string, unknown> {
  const file = resolve(
    process.cwd(),
    "src",
    "locales",
    locale,
    "translation.json",
  );
  const translation = JSON.parse(
    readFileSync(file, "utf8"),
  ) as Record<string, unknown>;
  return translation.f048_permission as Record<string, unknown>;
}

describe("F048 Client permission i18n", () => {
  it("keeps the nested F048 key set identical in all locales", () => {
    const baseline = flattenKeys(loadF048Locale("zh-Hans")).sort();
    for (const locale of LOCALES) {
      expect(flattenKeys(loadF048Locale(locale)).sort()).toEqual(baseline);
    }
  });

  it("contains mode, source, protected, model, impact, and error keys", () => {
    for (const locale of LOCALES) {
      const keys = new Set(flattenKeys(loadF048Locale(locale)));
      for (const key of REQUIRED_KEYS) expect(keys.has(key)).toBe(true);
    }
  });

  it("does not hardcode Chinese copy in F048 permission components", () => {
    for (const component of COMPONENTS) {
      const source = readFileSync(resolve(process.cwd(), component), "utf8");
      expect(source).not.toMatch(/[\u4e00-\u9fff]/u);
    }
  });
});
