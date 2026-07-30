import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

const LOCALES = ["zh-Hans", "en-US", "ja"] as const

const COMPONENTS = [
  "src/pages/SystemPage/components/RolesAndPermissions.tsx",
  "src/pages/SystemPage/components/permission/ActionLevelBoard.tsx",
  "src/pages/SystemPage/components/permission/ImpactDialog.tsx",
  "src/pages/SystemPage/components/permission/ModelEditor.tsx",
  "src/components/bs-comp/permission/ModeHeader.tsx",
  "src/components/bs-comp/permission/PermissionDialog.tsx",
  "src/components/bs-comp/permission/PermissionGrantTab.tsx",
  "src/components/bs-comp/permission/PermissionListTab.tsx",
  "src/components/bs-comp/permission/SourceBadge.tsx",
  "src/components/bs-comp/permission/useResourceActions.ts",
] as const

const REQUIRED_KEYS = [
  "actionLevel.title",
  "actionLevel.unassigned",
  "actionLevel.level",
  "model.kind.standard",
  "model.kind.custom",
  "model.preset.label",
  "mode.inherit",
  "mode.custom",
  "scope.local",
  "scope.inherited",
  "roster.protected",
  "source.direct",
  "source.department",
  "source.user_group",
  "source.includeChildren",
  "impact.title",
  "impact.publish",
  "mode.confirmTitle",
  "mode.confirmDescription",
  "error.versionConflict",
  "error.checkFailed",
  "error.impactExpired",
  "error.projectionFailed",
  "error.migrationBlocked",
] as const

function flattenKeys(
  value: Record<string, unknown>,
  prefix = "",
): string[] {
  return Object.entries(value).flatMap(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (item && typeof item === "object" && !Array.isArray(item)) {
      return flattenKeys(item as Record<string, unknown>, path)
    }
    return [path]
  })
}

function loadLocale(locale: (typeof LOCALES)[number]): Record<string, unknown> {
  const path = resolve(
    process.cwd(),
    "public",
    "locales",
    locale,
    "permission.json",
  )
  return JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>
}

describe("F048 Platform permission i18n", () => {
  it("keeps the complete key set identical in all three locales", () => {
    const baseline = flattenKeys(loadLocale("zh-Hans")).sort()

    for (const locale of LOCALES) {
      expect(flattenKeys(loadLocale(locale)).sort()).toEqual(baseline)
    }
  })

  it("contains the F048 action, model, source, impact, mode, and error keys", () => {
    for (const locale of LOCALES) {
      const keys = new Set(flattenKeys(loadLocale(locale)))
      for (const key of REQUIRED_KEYS) expect(keys.has(key)).toBe(true)
    }
  })

  it("does not hardcode Chinese copy in F048 components", () => {
    for (const file of COMPONENTS) {
      const source = readFileSync(resolve(process.cwd(), file), "utf8")
      expect(source).not.toMatch(/[\u4e00-\u9fff]/u)
    }
  })
})
