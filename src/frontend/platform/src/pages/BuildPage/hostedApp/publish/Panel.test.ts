import { describe, expect, it } from "vitest"
import { formatTimestamp } from "./Panel"

describe("formatTimestamp", () => {
  it("drops the T and fractional seconds of a naive value without shifting it", () => {
    expect(formatTimestamp("2026-10-12T12:06:58")).toBe("2026-10-12 12:06:58")
    expect(formatTimestamp("2026-10-12T12:06:58.123456")).toBe("2026-10-12 12:06:58")
  })

  it("converts a zoned value to local time", () => {
    const value = "2026-10-12T08:13:00.446217259Z"
    // Nanosecond fractions are not valid for Date; the function must still parse.
    const local = new Date("2026-10-12T08:13:00Z")
    const pad = (n: number) => String(n).padStart(2, "0")
    const expected =
      `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())} ` +
      `${pad(local.getHours())}:${pad(local.getMinutes())}:${pad(local.getSeconds())}`
    expect(formatTimestamp(value)).toBe(expected)
  })

  it("renders a dash for an empty value", () => {
    expect(formatTimestamp(null)).toBe("-")
    expect(formatTimestamp("")).toBe("-")
  })
})
