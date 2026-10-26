/**
 * F056 T029 — the ⚙️ menu, per card type (AC-16).
 *
 * The trimming itself is F054 T063's work; this is the regression that says it
 * stayed trimmed and, just as importantly, that trimming it did not quietly
 * change the other two card types. `CardComponent` is shared by workflow,
 * assistant and hosted-application cards, so "hide two entries for the new
 * type" is one prop away from "hide two entries for everybody" — a change that
 * looks fine in the hosted-app screenshot and breaks the build page.
 *
 * Both halves are asserted as *whole menus*, not as "the entry I care about is
 * present". A count is what catches an entry appearing, which is the direction
 * an AC about trimming actually fails in.
 */
import CardComponent from "@/components/bs-comp/cardComponent"
import { HostedAppCard } from "@/pages/BuildPage/HostedAppCard"
import { AppType } from "@/types/app"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

// The global setup's stub has no `i18n.t`, and the delete label is read from
// the `flow` namespace through it.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { t: (key: string) => key, changeLanguage: vi.fn(), language: "en" },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}))

vi.mock("i18next", () => ({
  default: { language: "en", t: (key: string) => key },
}))

// `*.svg?react` has no svgr plugin under vitest; this icon is on the render path.
vi.mock("@/components/bs-icons/user", () => ({ UserIcon: () => null }))

vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }))

vi.mock("@/controllers/API/hostedApp", () => ({
  getHostedAppVersionsApi: vi.fn(async () => []),
}))

const hostedActions = vi.hoisted(() => ({
  stopApp: vi.fn(async () => true),
  resumeApp: vi.fn(async () => true),
  deleteApp: vi.fn(async () => true),
}))

vi.mock("@/pages/BuildPage/useHostedAppActions", () => ({
  useHostedAppActions: () => hostedActions,
}))

/** The four entries `CardComponent` can render, in render order. */
const MENU_LABELS = {
  managePermission: "system.managePermission",
  createTemplate: "skills.createTemplate",
  copy: "copy",
  delete: "delete",
}

async function openMenu() {
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "more" }))
  return user
}

function menuItemTexts(): string[] {
  return Array.from(
    document.querySelectorAll("[data-slot='dropdown-menu-item']"),
  ).map((node) => (node.textContent || "").trim())
}

describe("⚙️ menu — workflow and assistant keep all four entries (AC-16)", () => {
  it("renders exactly the historical four for a workflow card", async () => {
    render(
      <CardComponent
        data={{ id: "1" }}
        id="1"
        type={AppType.FLOW}
        title="wf"
        description="desc"
        onClick={() => undefined}
        edit
        isAdmin
        checked={false}
        onPermission={vi.fn()}
        onAddTemp={vi.fn()}
        showCopy
        onCopy={vi.fn()}
        onDelete={vi.fn()}
      />,
    )
    await openMenu()

    expect(menuItemTexts()).toEqual([
      MENU_LABELS.managePermission,
      MENU_LABELS.createTemplate,
      MENU_LABELS.copy,
      MENU_LABELS.delete,
    ])
  })

  it("keeps the assistant's historical three (no template entry for assistants)", async () => {
    // `type !== 'assistant'` has always gated "add to templates"; it predates
    // this feature and must not have moved with it.
    render(
      <CardComponent
        data={{ id: "2" }}
        id="2"
        type={AppType.ASSISTANT}
        title="as"
        description="desc"
        onClick={() => undefined}
        edit
        isAdmin
        checked={false}
        onPermission={vi.fn()}
        onAddTemp={vi.fn()}
        showCopy
        onCopy={vi.fn()}
        onDelete={vi.fn()}
      />,
    )
    await openMenu()

    expect(menuItemTexts()).toEqual([
      MENU_LABELS.managePermission,
      MENU_LABELS.copy,
      MENU_LABELS.delete,
    ])
  })
})

describe("⚙️ menu — hosted application keeps two entries (AC-16 / F054 AC-53)", () => {
  const baseItem = {
    id: "app-1",
    name: "Alpha",
    description: "hosted",
    user_name: "owner",
    flow_type: 35,
  }

  function renderHosted({ item, ...overrides }: Record<string, unknown> = {}) {
    return render(
      <HostedAppCard
        currentUser={{ user_id: 1 }}
        isAdmin
        canDelete
        canSwitch
        canManagePermission
        onPermission={vi.fn()}
        onChanged={vi.fn()}
        {...overrides}
        item={{ ...baseItem, ...(item as object) }}
      />,
    )
  }

  it("offers manage-permission and delete, and nothing else", async () => {
    renderHosted({ item: { app_state: "stopped", status: 1 } })
    await openMenu()

    expect(menuItemTexts()).toEqual([
      MENU_LABELS.managePermission,
      MENU_LABELS.delete,
    ])
  })

  it("never offers copy or add-to-template, even to an admin who can edit", async () => {
    // The two entries are suppressed at the call site (`showCopy={false}`,
    // `onAddTemp={undefined}`), so no combination of card props can bring them
    // back — which is the claim worth pinning.
    renderHosted({ item: { app_state: "stopped", status: 1 }, isAdmin: true })
    await openMenu()

    const texts = menuItemTexts()
    expect(texts).not.toContain(MENU_LABELS.copy)
    expect(texts).not.toContain(MENU_LABELS.createTemplate)
  })

  it("greys delete out while the application is online (F054 AC-42)", async () => {
    renderHosted({ item: { app_state: "online", status: 2 } })
    await openMenu()

    const items = Array.from(
      document.querySelectorAll("[data-slot='dropdown-menu-item']"),
    )
    const deleteItem = items.find((node) => node.textContent?.trim() === MENU_LABELS.delete)
    expect(deleteItem).toBeTruthy()
    expect(deleteItem?.getAttribute("data-disabled")).not.toBeNull()
    // Disabled, not missing: "you cannot delete a running application" has to
    // read as a rule, and an absent entry reads as a missing feature.
    expect(menuItemTexts()).toEqual([
      MENU_LABELS.managePermission,
      MENU_LABELS.delete,
    ])
  })

  it("drops the permission entry for a caller who may not manage it", async () => {
    renderHosted({ item: { app_state: "stopped", status: 1 }, canManagePermission: false })
    await openMenu()

    expect(menuItemTexts()).toEqual([MENU_LABELS.delete])
  })
})
