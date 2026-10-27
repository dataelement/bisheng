import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

import {
  inspectSandboxEndpoints,
  parseSandboxEndpoints,
  sandboxSavePlan,
} from "@/pages/BuildPage/tools/builtInTool/sandboxEndpoint"

describe("parseSandboxEndpoints", () => {
  it("trims lines, drops blanks, and strips trailing slashes", () => {
    expect(parseSandboxEndpoints("  http://10.0.0.1:8080/ \n\nhttp://10.0.0.2:8080/// \n")).toEqual([
      "http://10.0.0.1:8080",
      "http://10.0.0.2:8080",
    ])
  })
})

describe("inspectSandboxEndpoints", () => {
  it("flags a duplicate after the trailing slash is removed", () => {
    const { issues } = inspectSandboxEndpoints("http://10.0.0.1:8080/\nhttp://10.0.0.1:8080")
    expect(issues).toEqual([{ index: 1, kind: "duplicate" }])
  })

  it("flags an address that is not http or https", () => {
    const { issues } = inspectSandboxEndpoints("ftp://10.0.0.1:8080")
    expect(issues).toEqual([{ index: 0, kind: "invalid" }])
  })

  it("flags more than 32 addresses", () => {
    const text = Array.from({ length: 33 }, (_, index) => `http://10.0.0.${index + 1}:8080`).join("\n")
    const { issues, endpoints } = inspectSandboxEndpoints(text)
    expect(endpoints).toHaveLength(32)
    expect(issues).toEqual([{ index: 32, kind: "too_many" }])
  })
})

describe("sandboxSavePlan", () => {
  it("stores sandbox settings before the tool only when sandbox mode changed", () => {
    expect(sandboxSavePlan("container", true)).toBe("sandbox-then-tool")
    expect(sandboxSavePlan("local", true)).toBe("tool-only")
    expect(sandboxSavePlan("container", false)).toBe("tool-only")
  })
})

describe("sandbox tool copy", () => {
  const here = dirname(fileURLToPath(import.meta.url))
  const files = ["zh-Hans", "en-US", "ja"].map((lang) =>
    JSON.parse(readFileSync(resolve(here, `../../public/locales/${lang}/tool.json`), "utf8"))
  )

  it("names each replica, the load balancer caveat, the platform process, and the four statuses", () => {
    for (const copy of files) {
      expect(copy.executionContainerHint.length).toBeGreaterThan(0)
      expect(copy.sandboxAddressHint.length).toBeGreaterThan(0)
      expect(copy.sandboxTestScope.length).toBeGreaterThan(0)
      expect(copy.sandboxTestOk.length).toBeGreaterThan(0)
      expect(copy.sandboxTestUnreachable.length).toBeGreaterThan(0)
      expect(copy.sandboxTestTokenRejected.length).toBeGreaterThan(0)
      expect(copy.sandboxTestBusy.length).toBeGreaterThan(0)
      expect(copy.sandboxTestResult.length).toBeGreaterThan(0)
      expect(copy.sandboxTestEmpty.length).toBeGreaterThan(0)
      expect(copy.sandboxTestFailed.length).toBeGreaterThan(0)
      expect(copy.sandboxSourcePage.length).toBeGreaterThan(0)
      expect(copy.sandboxSourceDeployment.length).toBeGreaterThan(0)
      expect(copy.sandboxSourceDefault.length).toBeGreaterThan(0)
    }
    expect(files[0].sandboxAddressHint).toContain("负载均衡")
    expect(files[1].sandboxAddressHint).toContain("load balancer")
    expect(files[2].sandboxAddressHint).toContain("ロードバランサ")
    expect(files[0].sandboxTestScope).toContain("平台服务进程")
    expect(files[1].sandboxTestScope).toContain("platform service")
    expect(files[2].sandboxTestScope).toContain("プラットフォーム")
  })
})
