import type { HostedAppVersion } from "@/controllers/API/hostedApp"
import { describe, expect, it } from "vitest"
import {
  approvalStatusI18nKey,
  pendingAwareStateI18nKey,
  versionOutcomeI18nKey,
  versionTerminalStateI18nKey,
} from "./types"

/**
 * These four mappers are the whole reason the publish face does not print
 * database columns at people. Each test below is a bug that shipped somewhere
 * before: an English enum in a Chinese table, a "waiting for resources" notice
 * on a release whose real problem was a crash on start-up, and a blank cell for
 * the one version the owner is actually waiting on.
 */

function version(overrides: Partial<HostedAppVersion> = {}): HostedAppVersion {
  return {
    version_id: "v1",
    version_no: 1,
    kind: "initial",
    terminal_state: null,
    submitted_at: null,
    is_current: false,
    is_pending: false,
    ...overrides,
  }
}

describe("versionTerminalStateI18nKey", () => {
  it("test_settled_outcomes_map_to_keys", () => {
    expect(versionTerminalStateI18nKey("online")).toBe(
      "hostedApp.versionList.outcomeOnline",
    )
    expect(versionTerminalStateI18nKey("rejected")).toBe(
      "hostedApp.versionList.outcomeRejected",
    )
    expect(versionTerminalStateI18nKey("withdrawn")).toBe(
      "hostedApp.versionList.outcomeWithdrawn",
    )
  })

  it("test_undecided_returns_null_so_caller_picks_its_own_blank", () => {
    expect(versionTerminalStateI18nKey(null)).toBeNull()
    expect(versionTerminalStateI18nKey(undefined)).toBeNull()
    // An unknown value must not be echoed to the user as a fake label.
    expect(versionTerminalStateI18nKey("something_new")).toBeNull()
  })
})

describe("versionOutcomeI18nKey", () => {
  it("test_pending_version_reads_as_pending_online_not_blank", () => {
    expect(versionOutcomeI18nKey(version({ is_pending: true }))).toBe(
      "hostedApp.versionList.outcomePendingOnline",
    )
  })

  it("test_undecided_and_unstaged_reads_as_under_approval", () => {
    expect(versionOutcomeI18nKey(version())).toBe(
      "hostedApp.versionList.outcomeInReview",
    )
  })

  it("test_latched_outcome_wins_over_pending_flag", () => {
    // A manual publish latches `online` and clears `pending_version_id`, but a
    // stale row that still carries both must read as the outcome, not as the
    // thing the owner is still waiting for.
    expect(
      versionOutcomeI18nKey(
        version({ terminal_state: "online", is_pending: true }),
      ),
    ).toBe("hostedApp.versionList.outcomeOnline")
  })
})

describe("pendingAwareStateI18nKey", () => {
  it("test_failed_start_is_not_reported_as_a_capacity_shortage", () => {
    expect(pendingAwareStateI18nKey("pending_capacity", "deploy_failed")).toBe(
      "hostedApp.state.pendingDeployFailed",
    )
  })

  it("test_capacity_and_unknown_reason_keep_the_plain_label", () => {
    expect(pendingAwareStateI18nKey("pending_capacity", "capacity")).toBe(
      "hostedApp.state.pendingCapacity",
    )
    expect(pendingAwareStateI18nKey("pending_capacity", null)).toBe(
      "hostedApp.state.pendingCapacity",
    )
  })

  it("test_other_states_are_untouched_by_a_stale_reason", () => {
    expect(pendingAwareStateI18nKey("online", "deploy_failed")).toBe(
      "hostedApp.state.online",
    )
  })
})

describe("approvalStatusI18nKey", () => {
  it("test_approved_and_executed_share_one_label", () => {
    expect(approvalStatusI18nKey("approved")).toBe(
      approvalStatusI18nKey("executed"),
    )
  })

  it("test_unknown_status_degrades_instead_of_echoing_the_wire_value", () => {
    expect(approvalStatusI18nKey("brand_new_status")).toBe(
      "hostedApp.publishStatus.approvalState.unknown",
    )
    expect(approvalStatusI18nKey(null)).toBe(
      "hostedApp.publishStatus.approvalState.unknown",
    )
  })
})
