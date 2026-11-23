/**
 * v3.1.0-alpha1 F001 — the template sheet's hosted-app card explains the path
 * instead of jumping straight to the tutorial (spec AC-12 … AC-16).
 */
import AppTempSheet from "@/components/bs-comp/sheets/AppTempSheet"
import { locationContext } from "@/contexts/locationContext"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { ns?: string }) => (options?.ns ? `${options.ns}:${key}` : key),
    i18n: { t: (key: string) => key, changeLanguage: vi.fn(), language: "en" },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}))

// `*.svg?react` has no svgr plugin under vitest.
vi.mock("@/components/bs-icons/app", () => ({ FlowIcon: () => null, HelperIcon: () => null }))
vi.mock("@/components/bs-comp/cardComponent/avatar", () => ({ default: () => null }))
vi.mock("@/components/bs-comp/cardComponent", () => ({
  default: ({ title, onClick }: { title: React.ReactNode; onClick: () => void }) => (
    <button type="button" onClick={onClick}>
      {title}
    </button>
  ),
}))
const readTemps = vi.hoisted(() => vi.fn(async () => [{ id: "t1", name: "Contract review", description: "" }]))
vi.mock("@/controllers/API", () => ({ readTempsDatabase: readTemps }))
vi.mock("@/controllers/request", () => ({ showApiError: vi.fn() }))

function renderSheet(appRuntimeEnabled: boolean) {
  return render(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- only appConfig is read by the sheet
    <locationContext.Provider value={{ appConfig: { appRuntimeEnabled } } as any}>
      <AppTempSheet onCustomCreate={vi.fn()} onSelect={vi.fn()}>
        <button type="button">open-sheet</button>
      </AppTempSheet>
    </locationContext.Provider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe("template sheet hosted-app card", () => {
  it("selects the card and shows the guide instead of opening a tab", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null)
    renderSheet(true)
    await userEvent.click(screen.getByText("open-sheet"))
    await waitFor(() => expect(screen.getByText("Contract review")).toBeTruthy())

    const card = screen.getByRole("button", { pressed: false, name: /hostedApp/ })
    expect(card.textContent).toContain("hostedAppLearnHow")
    await userEvent.click(card)

    expect(open).not.toHaveBeenCalled()
    expect(card.getAttribute("aria-pressed")).toBe("true")
    expect(screen.getByText("hostedAppGuide.intro")).toBeTruthy()
    expect(screen.getByText("hostedAppGuide.prepareBody")).toBeTruthy()
    expect(screen.getAllByRole("listitem")).toHaveLength(5)
    expect(screen.queryByText("Contract review")).toBeNull()
    expect((screen.getByPlaceholderText("search") as HTMLInputElement).disabled).toBe(true)
    expect(screen.queryByText("bs:hostedApp.guide.descDisabled")).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "viewTutorial" }))
    expect(open).toHaveBeenCalledWith("/tutorial/hosted-app.html", "_blank", "noopener")
  })

  it("goes back to templates when a template kind is picked", async () => {
    renderSheet(true)
    await userEvent.click(screen.getByText("open-sheet"))
    await userEvent.click(await screen.findByRole("button", { name: /hostedApp/ }))
    await userEvent.click(screen.getByText("workflow"))

    expect(screen.queryByText("hostedAppGuide.intro")).toBeNull()
    expect((screen.getByPlaceholderText("search") as HTMLInputElement).disabled).toBe(false)
  })

  it("warns in the guide when the runtime layer is not deployed", async () => {
    renderSheet(false)
    await userEvent.click(screen.getByText("open-sheet"))
    await userEvent.click(await screen.findByRole("button", { name: /hostedApp/ }))

    expect(screen.getByText("bs:hostedApp.guide.descDisabled")).toBeTruthy()
    expect(screen.getByRole("button", { name: "viewTutorial" })).toBeTruthy()
  })
})
