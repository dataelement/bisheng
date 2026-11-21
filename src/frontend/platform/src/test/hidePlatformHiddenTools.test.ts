import { describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/request", () => ({ default: {} }))

import { hidePlatformHiddenTools } from "@/controllers/API/tools"


describe("hidePlatformHiddenTools", () => {
  it("drops the desktop knowledge search category and keeps other tools", () => {
    const groups = [
      { id: 72, name: "Knowledge search", children: [{ id: 1, tool_key: "bisheng_knowledge_search" }] },
      { id: 3, name: "Web fetch", children: [{ id: 2, tool_key: "web_fetch" }] },
      { id: 9, name: "Mixed", children: [{ id: 3, tool_key: "bisheng_knowledge_search" }, { id: 4, tool_key: "x" }] },
      { id: 10, name: "Empty", children: [] },
    ]
    expect(hidePlatformHiddenTools(groups)).toEqual([
      groups[1],
      { id: 9, name: "Mixed", children: [{ id: 4, tool_key: "x" }] },
      groups[3],
    ])
  })

  it("passes non-array responses through", () => {
    expect(hidePlatformHiddenTools(null)).toBeNull()
  })
})
