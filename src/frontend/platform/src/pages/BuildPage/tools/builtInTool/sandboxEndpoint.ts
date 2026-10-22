/** Parse sandbox replica addresses and decide whether a save must store them first. */

export type SandboxEndpointIssueKind = "invalid" | "duplicate" | "too_many"

export interface SandboxEndpointIssue {
  index: number
  kind: SandboxEndpointIssueKind
}

const MAX_ENDPOINTS = 32

export function parseSandboxEndpoints(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/\/+$/, ""))
    .filter((line) => line.length > 0)
}

function isLegalAddress(url: string): boolean {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false
    if (!parsed.hostname) return false
    if (parsed.port) {
      const port = Number(parsed.port)
      if (!Number.isInteger(port) || port < 1 || port > 65535) return false
    }
    return true
  } catch {
    return false
  }
}

export function inspectSandboxEndpoints(text: string): {
  endpoints: string[]
  issues: SandboxEndpointIssue[]
} {
  const issues: SandboxEndpointIssue[] = []
  const endpoints: string[] = []
  const seen = new Set<string>()
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim().replace(/\/+$/, "")
    if (!line) return
    if (endpoints.length >= MAX_ENDPOINTS) {
      issues.push({ index, kind: "too_many" })
      return
    }
    if (!isLegalAddress(line)) {
      issues.push({ index, kind: "invalid" })
      return
    }
    if (seen.has(line)) {
      issues.push({ index, kind: "duplicate" })
      return
    }
    seen.add(line)
    endpoints.push(line)
  })
  return { endpoints, issues }
}

export function sandboxSavePlan(
  mode: string,
  changed: boolean
): "sandbox-then-tool" | "tool-only" {
  if (mode === "container" && changed) return "sandbox-then-tool"
  return "tool-only"
}
