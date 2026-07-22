import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

const localeNames = ["zh-Hans", "en-US", "ja"]
const relevantFiles = [
  "src/controllers/API/developerToken.ts",
  "src/pages/SystemPage/components/DeveloperToken.tsx",
  "src/pages/SystemPage/components/DeveloperTokenFileSyncRule.tsx",
  "src/pages/SystemPage/components/DeveloperTokenGlobalSettings.tsx",
  "src/pages/SystemPage/components/DeveloperTokenTable.tsx",
  "src/pages/SystemPage/components/developerTokenFileSyncRuleValidation.ts",
  "src/components/bs-comp/selectComponent/DepartmentUsersSelect.tsx",
]

function flattenKeys(value: unknown, prefix = ""): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [prefix]
  return Object.entries(value).flatMap(([key, child]) =>
    flattenKeys(child, prefix ? `${prefix}.${key}` : key)
  )
}

describe("developer token file-sync static contracts", () => {
  it("keeps the Developer Token locale key sets aligned in all three languages", () => {
    const keySets = localeNames.map((locale) => {
      const json = JSON.parse(readFileSync(resolve(
        process.cwd(),
        `public/locales/${locale}/bs.json`
      ), "utf8"))
      return flattenKeys(json.system.developerToken).sort()
    })

    expect(keySets[1]).toEqual(keySets[0])
    expect(keySets[2]).toEqual(keySets[0])
    expect(keySets[0]).toContain("fileSync.summary.notConfigured")
    expect(keySets[0]).toContain("columns.fileSync")
  })

  it.each(relevantFiles)("keeps %s at or below 600 lines", (file) => {
    const lines = readFileSync(resolve(process.cwd(), file), "utf8").split("\n").length
    expect(lines).toBeLessThanOrEqual(600)
  })
})
