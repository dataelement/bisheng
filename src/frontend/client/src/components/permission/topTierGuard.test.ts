import { canManageLevel, viewerIsCreator } from "./topTierGuard";

/** Twin of the platform app's guard test — the two copies must not drift. */
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
  } as never;
}

describe("top-tier grant guard", () => {
  it("recognises the creator from their own roster row", () => {
    const roster = [
      row({
        source: { type: "CREATOR", include_children: false },
        subject: { type: "user", id: "7" },
      }),
      row({ subject: { type: "user", id: "9" } }),
    ];
    expect(viewerIsCreator(roster, 7)).toBe(true);
    expect(viewerIsCreator(roster, "7")).toBe(true);
    expect(viewerIsCreator(roster, 9)).toBe(false);
  });

  it("does not mistake an ordinary owner for the creator", () => {
    // The reported case: granted owner, so allowed to manage the resource —
    // but not to edit the other owners sitting beside them.
    const roster = [row({ subject: { type: "user", id: "7" } })];
    expect(viewerIsCreator(roster, 7)).toBe(false);
  });

  it("does not mistake a group or department for the viewer", () => {
    const roster = [
      row({
        source: { type: "CREATOR", include_children: false },
        subject: { type: "department", id: "7" },
      }),
    ];
    expect(viewerIsCreator(roster, 7)).toBe(false);
  });

  it("reads an anonymous viewer as not the creator", () => {
    const roster = [
      row({
        source: { type: "CREATOR", include_children: false },
        subject: { type: "user", id: "7" },
      }),
    ];
    expect(viewerIsCreator(roster, null)).toBe(false);
    expect(viewerIsCreator(roster, undefined)).toBe(false);
  });

  it("locks only the top tier, and only for non-creators", () => {
    expect(canManageLevel(4, false)).toBe(false);
    expect(canManageLevel(4, true)).toBe(true);
    for (const level of [1, 2, 3]) {
      expect(canManageLevel(level, false)).toBe(true);
    }
    // A model with no level is not the top tier.
    expect(canManageLevel(null, false)).toBe(true);
    expect(canManageLevel(undefined, false)).toBe(true);
  });
});
