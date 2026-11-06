import type { PermissionGrantAssignee } from "@/controllers/API/permission"
import { describe, expect, it } from "vitest"
import { isOwnerOnly, summarizeGrants } from "./visibilityScope"

/**
 * The first test is the reason this file exists: F048 seeds a protected owner
 * grant at creation time, so "the roster is empty" is a state that never
 * occurs. An implementation that checks `grants.length` passes review, passes
 * every manual click-through by the owner, and silently never shows the banner.
 */

function grant(overrides: Partial<PermissionGrantAssignee>): PermissionGrantAssignee {
  return {
    assignee_id: "1",
    assignee_version: 1,
    subject: { type: "user", id: "1", name: null },
    model: { key: "viewer", name: "viewer", level: 1, active: true },
    source: { type: "DIRECT", include_children: false },
    scope: "LOCAL",
    inherited_from: null,
    protected: false,
    editable: true,
    ...overrides,
  }
}

describe("isOwnerOnly", () => {
  it("test_owner_only_when_single_protected_row", () => {
    expect(isOwnerOnly("online", [grant({ protected: true, editable: false })])).toBe(true)
  })

  it("test_not_owner_only_with_grant", () => {
    const grants = [
      grant({ assignee_id: "1", protected: true, editable: false }),
      grant({ assignee_id: "2", subject: { type: "user_group", id: "9", name: "All" } }),
    ]
    expect(isOwnerOnly("online", grants)).toBe(false)
  })

  it("test_draft_never_shows_banner", () => {
    expect(isOwnerOnly("draft", [])).toBe(false)
    expect(isOwnerOnly("stopped", [grant({ protected: true, editable: false })])).toBe(false)
    expect(isOwnerOnly(undefined, [])).toBe(false)
  })
})

describe("summarizeGrants", () => {
  it("test_summary_plus_when_has_more", () => {
    const grants = [
      grant({ assignee_id: "1", protected: true, editable: false }),
      grant({ assignee_id: "2" }),
      grant({ assignee_id: "3" }),
    ]
    expect(summarizeGrants(grants, false)).toBe("2")
    expect(summarizeGrants(grants, true)).toBe("2+")
  })
})
