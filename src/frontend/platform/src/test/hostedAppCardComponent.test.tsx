import CardComponent from "@/components/bs-comp/cardComponent"
import { AppType } from "@/types/app"
import { render, screen, waitFor } from "@testing-library/react"
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
 * cards. Anything added for F054 is optional and the default rendering must
 * stay exactly what it was — a regression here shows up on every card in the
 * build page, not only on the new one.
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
  it("uses the shared online/offline copy for every card type", () => {
    // Hosted applications used to carry their own "已上线 / 已停运" pair here.
    // One vocabulary for the whole build page is the point of dropping it.
    renderCard({ checked: true, showSwitch: true, canSwitch: true })
    expect(screen.getByText("skills.online")).toBeTruthy()
  })
})

describe("CardComponent switch state", () => {
  it("holds the switch until the action resolves, so a slow stop is not clicked twice", async () => {
    // Taking a hosted app offline waits on `docker stop` (~10s). A second
    // click in that window used to fire a second request, which lost the state
    // race and left the card showing a state the server had already left.
    let release: (value: boolean) => void = () => undefined
    const onCheckedChange = vi.fn(
      () => new Promise<boolean>((resolve) => { release = resolve }),
    )
    renderCard({ checked: true, showSwitch: true, canSwitch: true, onCheckedChange })

    const user = userEvent.setup()
    const toggle = screen.getByRole("switch")
    await user.click(toggle)
    expect(onCheckedChange).toHaveBeenCalledTimes(1)

    await waitFor(() => expect(toggle.hasAttribute("disabled")).toBe(true))
    await user.click(toggle)
    expect(onCheckedChange).toHaveBeenCalledTimes(1)

    release(true)
    await waitFor(() => expect(toggle.getAttribute("data-state")).toBe("unchecked"))
    expect(toggle.hasAttribute("disabled")).toBe(false)
  })

  it("follows the row when the list reloads with a new state", async () => {
    // The card kept a copy taken at mount, so a state changed anywhere else —
    // the detail page, another tab, a failed action that had in fact landed —
    // stayed invisible until a manual page refresh.
    const { rerender } = render(
      <CardComponent
        data={{ id: "1" }}
        id="1"
        type={AppType.FLOW}
        title="demo"
        description="desc"
        onClick={() => undefined}
        checked={true}
        showSwitch
        canSwitch
      />,
    )
    expect(screen.getByRole("switch").getAttribute("data-state")).toBe("checked")

    rerender(
      <CardComponent
        data={{ id: "1" }}
        id="1"
        type={AppType.FLOW}
        title="demo"
        description="desc"
        onClick={() => undefined}
        checked={false}
        showSwitch
        canSwitch
      />,
    )
    await waitFor(() =>
      expect(screen.getByRole("switch").getAttribute("data-state")).toBe("unchecked"),
    )
  })
})
