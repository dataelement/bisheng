import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { TierSelectCard, coresOf } from "./TierSelectCard"

/**
 * The global `react-i18next` mock (src/test/setup.ts) echoes the key and drops
 * the interpolation, which would hide the one number this card exists to get
 * right — cores, not millicores. So this file overrides it with an echo that
 * appends the values; everything else reads as the copy contract.
 *
 * What is worth pinning beyond that is the *shape of the answer given to an
 * owner who cannot change the thing the card is about*: naming the file that
 * decides it (AC-06 / AC-61), rather than a disabled dropdown that reads as
 * broken.
 */
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options ? `${key}:${Object.values(options).join(",")}` : key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}))

describe("TierSelectCard", () => {
  it("test_a_cli_application_gets_the_read_only_card_and_is_told_where_the_tier_lives", () => {
    render(
      <TierSelectCard
        tier={{ code: "light", name: "Light", cpu_millicores: 500, memory_mb: 1024 }}
        canSubmit={false}
      />,
    )

    expect(screen.getByTestId("tier-select-card")).toBeInTheDocument()
    expect(screen.getByText("Light")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.tier.cliOnlyHint")).toBeInTheDocument()
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument()
  })

  it("test_the_spec_reads_in_cores_not_millicores", () => {
    render(
      <TierSelectCard
        tier={{ code: "light", name: "Light", cpu_millicores: 500, memory_mb: 1024 }}
      />,
    )

    // The key echo carries the interpolation value, which is the number an
    // owner would read out loud — 0.5 核, not 500 毫核.
    expect(screen.getByText(/hostedApp\.tier\.cores/)).toHaveTextContent("0.5")
    expect(screen.getByText(/hostedApp\.tier\.memory/)).toHaveTextContent("1024")
  })

  it("test_an_unknown_tier_still_renders_a_card", () => {
    render(<TierSelectCard tier={null} />)

    expect(screen.getByText("hostedApp.tier.unknown")).toBeInTheDocument()
  })

  it("test_a_retired_tier_is_marked_and_explained", () => {
    render(
      <TierSelectCard
        tier={{
          code: "perf",
          name: "Performance",
          cpu_millicores: 4000,
          memory_mb: 8192,
          enabled: false,
        }}
      />,
    )

    expect(screen.getByText("hostedApp.tier.retiredTag")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.tier.retiredHint")).toBeInTheDocument()
  })

  it("test_the_selectable_branch_needs_both_permission_and_a_list", () => {
    // Wired for PRD-2 and unreachable today: `can.submit` is false for every
    // application (AC-06), and the tier list endpoint is a super-admin surface
    // an owner cannot read, so the page passes neither.
    const { rerender } = render(
      <TierSelectCard tier={null} canSubmit options={[]} />,
    )
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument()

    rerender(
      <TierSelectCard
        tier={null}
        canSubmit
        options={[{ code: "light", name: "Light", cpu_millicores: 500, memory_mb: 1024 }]}
        value="light"
      />,
    )
    expect(screen.getByRole("combobox")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.tier.effectiveHint")).toBeInTheDocument()
  })

  it("test_a_row_without_a_code_never_reaches_a_select_item", () => {
    // An empty `value` on a Radix item throws and blanks the whole page; older
    // backends do send rows like this, so the filter is here, not there.
    render(
      <TierSelectCard
        tier={null}
        canSubmit
        options={[
          { code: "", name: "Broken row", cpu_millicores: null, memory_mb: null },
          { code: "light", name: "Light", cpu_millicores: 500, memory_mb: 1024 },
        ]}
        value="light"
      />,
    )

    expect(screen.getByRole("combobox")).toBeInTheDocument()
  })

  it("test_cores_of_rejects_what_is_not_a_positive_number", () => {
    expect(coresOf(500)).toBe(0.5)
    expect(coresOf(2000)).toBe(2)
    expect(coresOf(null)).toBeNull()
    expect(coresOf(0)).toBeNull()
    expect(coresOf(Number.NaN)).toBeNull()
  })
})
