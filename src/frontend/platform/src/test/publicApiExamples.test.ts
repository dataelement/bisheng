import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

function source(file: string): string {
  return readFileSync(join(process.cwd(), "src", file), "utf8")
}

describe("published API examples", () => {
  it("uses only anonymous v3 workflow and assistant URLs", () => {
    const examples = `${source("components/bs-comp/apiComponent/ApiAccess.tsx")}\n${source("components/bs-comp/apiComponent/ApiAccessFlow.tsx")}`
    expect(examples).toContain("/api/v3/workflow/invoke")
    expect(examples).toContain("/api/v3/workflow/stop")
    expect(examples).toContain("/api/v3/assistant/chat/completions")
    expect(examples).not.toContain("/api/v2/")
    expect(examples).not.toContain("Authorization")
  })

  it("keeps service-account key examples on authenticated v2", () => {
    const keyDialog = source("pages/SystemPage/components/ServiceAccount/KeyIssueDialog.tsx")
    expect(keyDialog).toContain("/api/v2/auth/whoami")
    expect(keyDialog).toContain("Authorization: Bearer")
  })
})
