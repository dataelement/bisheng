import { fireEvent, render, screen } from "@testing-library/react"
import { expect, it, vi } from "vitest"
import RuleFile from "./RuleFile"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: "en" } }),
}))
vi.mock("./FileUploadSplitStrategy", () => ({ default: () => null }))
vi.mock("./KnowledgeTooltip", () => ({ KnowledgeHint: () => null }))

it("only shows chunk length and overlap for custom splitting", () => {
  render(<RuleFile rules={{ splitMode: "auto", chunkSize: "1000", chunkOverlap: "0" }} setRules={vi.fn()} />)
  expect(screen.queryByText("splitLength")).toBeNull()
  expect(screen.queryByText("chunkOverlap")).toBeNull()
  fireEvent.click(screen.getByText("customSplit"))
  expect(screen.getByLabelText("splitLength")).toHaveValue(1000)
  expect(screen.getByLabelText("chunkOverlap")).toHaveValue(0)
  fireEvent.click(screen.getByText("autoSplit"))
  expect(screen.queryByText("splitLength")).toBeNull()
  expect(screen.queryByText("chunkOverlap")).toBeNull()
})
