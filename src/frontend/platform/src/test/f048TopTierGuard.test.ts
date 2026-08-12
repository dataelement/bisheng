import {
  canManageLevel,
  viewerIsCreator,
} from "@/components/bs-comp/permission/topTierGuard"
import { describe, expect, it } from "vitest"

function row(overrides: Record<string, unknown> = {}) {
  return {
    assignee_id: "1",
    assignee_version: 1,
    subject: { type: "user", id: "7", name: "Alice" },
    model: { key: "owner", name: "Owner", level: 4, active: true },
    source: { type: "DIRECT", include_children: false },
    scope: "LOCAL",
    inherited_from: null,
    protected: false,
    editable: true,
    ...overrides,
  } as never
}

describe("top-tier grant guard", () => {
  it("recognises the creator from their own roster row", () => {
    const roster = [
      row({ source: { type: "CREATOR", include_children: false }, subject: { type: "user", id: "7" } }),
      row({ subject: { type: "user", id: "9" } }),
    ]
    expect(viewerIsCreator(roster, 7)).toBe(true)
    expect(viewerIsCreator(roster, "7")).toBe(true)
    expect(viewerIsCreator(roster, 9)).toBe(false)
  })

  it("does not mistake an ordinary owner for the creator", () => {
    const roster = [row({ subject: { type: "user", id: "7" } })]
    expect(viewerIsCreator(roster, 7)).toBe(false)
  })

  it("does not mistake a group or department for the viewer", () => {
    const roster = [
      row({
        source: { type: "CREATOR", include_children: false },
        subject: { type: "department", id: "7" },
      }),
    ]
    expect(viewerIsCreator(roster, 7)).toBe(false)
  })

  it("reads as not-the-creator without a signed-in user", () => {
    const roster = [
      row({ source: { type: "CREATOR", include_children: false }, subject: { type: "user", id: "7" } }),
    ]
    expect(viewerIsCreator(roster, null)).toBe(false)
    expect(viewerIsCreator(roster, undefined)).toBe(false)
  })

  it("fails closed when the creator row is not on the loaded page", () => {
    // Restrictive is the safe direction for a guardrail: the creator loses the
    // control until more rows load, rather than an owner gaining it.
    expect(viewerIsCreator([row({ subject: { type: "user", id: "7" } })], 7)).toBe(false)
  })

  it("reserves the top tier for the creator", () => {
    expect(canManageLevel(4, false)).toBe(false)
    expect(canManageLevel(4, true)).toBe(true)
  })

  it("leaves every lower tier alone", () => {
    for (const level of [1, 2, 3]) {
      expect(canManageLevel(level, false)).toBe(true)
    }
  })

  it("treats a level-less model as manageable", () => {
    expect(canManageLevel(null, false)).toBe(true)
    expect(canManageLevel(undefined, false)).toBe(true)
  })
})
