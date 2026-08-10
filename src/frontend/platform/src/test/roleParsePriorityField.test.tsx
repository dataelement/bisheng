import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import RoleParsePriorityField, {
  DEFAULT_KNOWLEDGE_PARSE_PRIORITY,
  mergeKnowledgeParsePriority,
  normalizeKnowledgeParsePriority,
} from "@/pages/SystemPage/components/RoleParsePriorityField"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

describe("RoleParsePriorityField", () => {
  it("normalizes missing or invalid legacy values to medium", () => {
    expect(normalizeKnowledgeParsePriority(undefined)).toBe(DEFAULT_KNOWLEDGE_PARSE_PRIORITY)
    expect(normalizeKnowledgeParsePriority("unexpected")).toBe(DEFAULT_KNOWLEDGE_PARSE_PRIORITY)
    expect(normalizeKnowledgeParsePriority("high")).toBe("high")
  })

  it("preserves unrelated quota fields when merging the selected priority", () => {
    expect(mergeKnowledgeParsePriority({ channel: 7, custom: "keep" }, "low")).toEqual({
      channel: 7,
      custom: "keep",
      knowledge_file_parse_priority: "low",
    })
  })

  it("emits the selected priority", () => {
    const handleChange = vi.fn()
    render(<RoleParsePriorityField value="medium" onChange={handleChange} />)

    fireEvent.click(screen.getByText("system.knowledgeParsePriorityHigh"))

    expect(handleChange).toHaveBeenCalledWith("high")
  })
})
