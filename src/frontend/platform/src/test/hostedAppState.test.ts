import { AppNumToType, AppNumType, AppType, AppTypeToNum } from "@/types/app"
import {
  HOSTED_APP_STATES,
  isDeleteBlockedByState,
  isOnline,
  phaseI18nKey,
  stateI18nKey,
} from "@/pages/BuildPage/hostedApp/types"
import { describe, expect, it } from "vitest"

describe("hosted application vocabulary", () => {
  it("offers only states the list can actually return", () => {
    // `deleted` is excluded on purpose: the server's list drops it, so
    // offering it would be a filter that can only ever come back empty, which
    // reads as a broken page rather than as a covered state (ruled 2026-08-17).
    expect(HOSTED_APP_STATES).toEqual([
      "draft",
      "online",
      "pending_capacity",
      "stopped",
    ])
    expect(HOSTED_APP_STATES).not.toContain("deleted")
    expect(stateI18nKey("pending_capacity")).toBe(
      "hostedApp.state.pendingCapacity",
    )
  })

  it("can still name a deleted application even though it is not filterable", () => {
    // A stale link to a removed application must say what happened, so the
    // word survives the filter's removal.
    expect(stateI18nKey("deleted")).toBe("hostedApp.state.deleted")
  })

  it("never renders a raw state value for an unknown state", () => {
    expect(stateI18nKey(undefined)).toMatch(/^hostedApp\.state\./)
    expect(phaseI18nKey("who-knows")).toMatch(/^hostedApp\.phase\./)
  })

  it("blocks deletion only while the application is online", () => {
    // AC-42 — an online app has a running container and a host volume; the
    // teardown has to go through the stop action, not through a row vanishing.
    expect(isDeleteBlockedByState("online")).toBe(true)
    for (const state of ["draft", "pending_capacity", "stopped"]) {
      expect(isDeleteBlockedByState(state)).toBe(false)
    }
    expect(isOnline("online")).toBe(true)
    expect(isOnline("stopped")).toBe(false)
  })
})

describe("shared application type enums", () => {
  it("adds the hosted type without disturbing the existing codes", () => {
    // These mirror the backend FlowType enum; changing an existing value would
    // desynchronise the UNION branch the whole app list is built from.
    expect(AppNumType.ASSISTANT).toBe(5)
    expect(AppNumType.FLOW).toBe(10)
    expect(AppNumType.HOSTED_APP).toBe(35)
    expect(AppTypeToNum[AppType.HOSTED_APP]).toBe(AppNumType.HOSTED_APP)
    expect(AppNumToType[AppNumType.HOSTED_APP]).toBe(AppType.HOSTED_APP)
    expect(AppNumToType[AppNumType.FLOW]).toBe(AppType.FLOW)
  })
})
