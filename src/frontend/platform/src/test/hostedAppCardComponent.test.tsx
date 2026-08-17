import CardComponent from "@/components/bs-comp/cardComponent"
import { AppType } from "@/types/app"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

// The global setup's react-i18next stub has no `i18n.t`, and this component
// reads both `t` and `i18n.t` (the delete label lives in the `flow` namespace).
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      t: (key: string) => key,
      changeLanguage: vi.fn(),
      language: "en",
    },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}))

vi.mock("i18next", () => ({
  default: { language: "en", t: (key: string) => key },
}))

// `*.svg?react` resolves to a data-URI string under vitest (no svgr plugin in
// vitest.config.ts), and React then tries to create an element whose tag name
// is that URI. Only this one icon is on the render path here.
vi.mock("@/components/bs-icons/user", () => ({
  UserIcon: () => null,
}))

/**
 * `CardComponent` is shared by workflow, assistant and (now) hosted-application
 * cards. The two props added for F054 are optional and the default rendering
 * must stay exactly what it was — a regression here shows up on every card in
 * the build page, not only on the new one.
 */
function renderCard(props: Record<string, unknown> = {}) {
  return render(
    <CardComponent
      data={{ id: "1" }}
      id="1"
      type={AppType.FLOW}
      title="demo"
      description="desc"
      onClick={() => undefined}
      {...props}
    />,
  )
}

async function openMenu() {
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "more" }))
  return user
}

describe("CardComponent delete entry", () => {
  it("hides the delete entry while the card is switched on (default behaviour)", async () => {
    renderCard({ checked: true, onDelete: vi.fn(), onPermission: vi.fn() })
    await openMenu()
    expect(await screen.findByText("system.managePermission")).toBeTruthy()
    expect(screen.queryByText("delete")).toBeNull()
  })

  it("shows the delete entry while the card is switched off", async () => {
    renderCard({ checked: false, onDelete: vi.fn(), onPermission: vi.fn() })
    await openMenu()
    const item = await screen.findByText("delete")
    expect(item.closest("[data-disabled]")).toBeNull()
  })

  it("greys the delete entry out instead of hiding it when a hint is given", async () => {
    // AC-42: an online hosted app must show a disabled "delete" plus "stop it
    // first". Built on today's behaviour it would have produced "not there at
    // all", which reads as a missing feature rather than as a rule.
    renderCard({
      checked: true,
      onDelete: vi.fn(),
      onPermission: vi.fn(),
      deleteDisabledHint: "stop it first",
    })
    await openMenu()
    const label = await screen.findByText("delete")
    const item = label.closest("[data-slot='dropdown-menu-item']")
    expect(item).toBeTruthy()
    expect(item?.getAttribute("data-disabled")).not.toBeNull()
  })
})

describe("CardComponent switch labels", () => {
  it("defaults to the shared online/offline copy", () => {
    renderCard({ checked: true, showSwitch: true, canSwitch: true })
    expect(screen.getByText("skills.online")).toBeTruthy()
  })

  it("lets a caller override the labels", () => {
    renderCard({
      checked: true,
      showSwitch: true,
      canSwitch: true,
      switchTexts: { on: "running", off: "stopped" },
    })
    expect(screen.getByText("running")).toBeTruthy()
    expect(screen.queryByText("skills.online")).toBeNull()
  })
})
