import {
  actionLabel,
  resourceTypeLabel,
} from "@/pages/SystemPage/components/permission/actionLabels"
import { describe, expect, it } from "vitest"

/** Mimic i18next: an unknown key resolves to `defaultValue`, if one was given. */
function makeT(known: Record<string, string>) {
  return ((key: string, options?: { defaultValue?: string }) =>
    known[key] ?? options?.defaultValue ?? key) as never
}

describe("permission action labels", () => {
  const t = makeT({
    "actionName.manage_permission": "MANAGE_LABEL",
    "resourceTypeName.knowledge_file": "FILE_LABEL",
  })

  it("resolves a known action by its code", () => {
    // The catalog seeds `name` to the code itself, so the stored value is the
    // English identifier and cannot be shown as-is.
    expect(actionLabel(t, "manage_permission", "manage_permission")).toBe("MANAGE_LABEL")
  })

  it("falls back to the stored name for a code it has no label for", () => {
    expect(actionLabel(t, "future_action", "Future Action")).toBe("Future Action")
  })

  it("falls back to the code when nothing else is available", () => {
    expect(actionLabel(t, "future_action")).toBe("future_action")
    expect(actionLabel(t, "future_action", "")).toBe("future_action")
  })

  it("resolves resource types the same way", () => {
    expect(resourceTypeLabel(t, "knowledge_file")).toBe("FILE_LABEL")
    expect(resourceTypeLabel(t, "unknown_type")).toBe("unknown_type")
  })
})
