import { formatIsoDateTime, normalizeServerUtcDateTime } from "@/util/utils"
import { describe, expect, it } from "vitest"

describe("normalizeServerUtcDateTime", () => {
  it("appends Z for naive backend timestamps", () => {
    expect(normalizeServerUtcDateTime("2026-08-07T10:48:02")).toBe("2026-08-07T10:48:02Z")
  })

  it("keeps explicit timezone suffixes", () => {
    expect(normalizeServerUtcDateTime("2026-08-07T10:48:02+00:00")).toBe("2026-08-07T10:48:02+00:00")
    expect(normalizeServerUtcDateTime("2026-08-07T10:48:02Z")).toBe("2026-08-07T10:48:02Z")
  })
})

describe("formatIsoDateTime", () => {
  it("interprets naive backend timestamps as UTC", () => {
    const expected = new Date("2026-08-07T10:48:02Z").toLocaleString()
    expect(formatIsoDateTime("2026-08-07T10:48:02")).toBe(expected)
  })
})
