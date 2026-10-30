import { fireEvent, render, screen } from "@testing-library/react"
import { expect, it, vi } from "vitest"
import type { ContextType, ReactNode } from "react"
import { userContext } from "@/contexts/userContext"
import { DangerZoneCard } from "./DangerZoneCard"

vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: { user_id: 0, is_global_super: false } }),
}))

const mocks = vi.hoisted(() => ({ remove: vi.fn() }))
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }))
vi.mock("../../useHostedAppActions", () => ({ useHostedAppActions: () => ({ deleteApp: mocks.remove }) }))
vi.mock("./Panel", () => ({ Panel: ({ actions }: { actions: ReactNode }) => actions }))

it.each([
  [7, false, "stopped", true, false],
  [8, true, "stopped", true, false],
  [8, false, "stopped", false, false],
  [8, true, "online", true, true],
] as const)("delete visibility and state guard (%s, %s, %s)", (userId, superAdmin, state, visible, disabled) => {
  mocks.remove.mockClear()
  render(
    <userContext.Provider value={{ user: { user_id: userId, is_global_super: superAdmin } } as ContextType<typeof userContext>}>
      <DangerZoneCard app={{ app_id: "app", name: "App", owner_user_id: 7, state } as Parameters<typeof DangerZoneCard>[0]["app"]} />
    </userContext.Provider>,
  )
  const button = screen.queryByRole("button", { name: "hostedApp.dangerZone.delete" })
  expect(Boolean(button)).toBe(visible)
  if (button) {
    expect(button).toHaveProperty("disabled", disabled)
    fireEvent.click(button)
    expect(mocks.remove.mock.calls.length).toBe(disabled ? 0 : 1)
  }
})
