/**
 * UI-side vocabulary for hosted applications.
 *
 * The wire types live in `@/controllers/API/hostedApp`; what is here is the
 * mapping from those values to i18n keys and to the few UI predicates the card
 * and the detail page must agree on. Both surfaces import from here so a state
 * label never says two different things in two places.
 */
import type {
  HostedAppPendingReason,
  HostedAppPhase,
  HostedAppState,
  HostedAppVersion,
} from "@/controllers/API/hostedApp"

/**
 * Order used by the build page's state filter.
 *
 * `deleted` is deliberately absent even though AC-51 spells out five states:
 * the server's list excludes `state='deleted'`, so offering it as a filter
 * gives an option that can only ever return nothing. A filter that is
 * guaranteed empty reads as a broken page, not as a covered state — a deleted
 * application is not a state the user can browse, it is an application that is
 * gone. The state word itself still resolves (see STATE_I18N) because a
 * detail page reached by a stale link must be able to name what happened.
 * Ruled 2026-08-17.
 */
export const HOSTED_APP_STATES: HostedAppState[] = ["draft", "online", "pending_capacity", "stopped"]

const STATE_I18N: Record<HostedAppState, string> = {
  draft: "hostedApp.state.draft",
  online: "hostedApp.state.online",
  pending_capacity: "hostedApp.state.pendingCapacity",
  stopped: "hostedApp.state.stopped",
  deleted: "hostedApp.state.deleted",
}

const PHASE_I18N: Record<HostedAppPhase, string> = {
  pending: "hostedApp.phase.pending",
  building: "hostedApp.phase.building",
  starting: "hostedApp.phase.starting",
  running: "hostedApp.phase.running",
  unhealthy: "hostedApp.phase.unhealthy",
  stopped: "hostedApp.phase.stopped",
  failed: "hostedApp.phase.failed",
}

export function stateI18nKey(state: string | undefined | null): string {
  return STATE_I18N[state as HostedAppState] ?? "hostedApp.state.draft"
}

/**
 * State label refined by *why* the application is parked.
 *
 * `pending_capacity` is one application state with two causes, and the plain
 * label names only one of them (the capacity one). An owner whose release
 * built fine and then failed its readiness probe would be told to wait for
 * memory that is not the problem, so where the reason is known the label says
 * it. Everything else falls straight through to `stateI18nKey`.
 */
export function pendingAwareStateI18nKey(
  state: string | undefined | null,
  pendingReason: HostedAppPendingReason | null | undefined,
): string {
  if (state === "pending_capacity" && pendingReason === "deploy_failed") {
    return "hostedApp.state.pendingDeployFailed"
  }
  return stateI18nKey(state)
}

export function phaseI18nKey(phase: string | undefined | null): string {
  return PHASE_I18N[phase as HostedAppPhase] ?? "hostedApp.phase.pending"
}

/**
 * Tailwind classes for the state badge. `pending_capacity` deliberately reads
 * as a warning rather than an error: the app passed approval, it is waiting for
 * room on the host, and an explicit action retries it.
 */
export function stateBadgeClass(state: string | undefined | null): string {
  switch (state) {
    case "online":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
    case "pending_capacity":
      return "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
    case "stopped":
      return "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200"
    case "deleted":
      return "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
    default:
      return "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
  }
}

/** AC-42 — an online application must be stopped before it can be deleted. */
export function isDeleteBlockedByState(state: string | undefined | null): boolean {
  return state === "online"
}

/** The card switch is on exactly while the application is online. */
export function isOnline(state: string | undefined | null): boolean {
  return state === "online"
}

/**
 * True for the two states the on/off switch already says out loud.
 *
 * `draft` and `pending_capacity` both project to "switch off" in the list, but
 * neither is reachable by flipping it, so a surface that shows the switch still
 * has to name those two some other way.
 */
export function isStateShownBySwitch(state: string | undefined | null): boolean {
  return state === "online" || state === "stopped"
}

/**
 * Approval-instance status → label.
 *
 * `approved` and `executed` deliberately share one label: the split between
 * "the approvers said yes" and "the business action then ran" is an internal
 * step of the approval engine, and an owner reading "executed" would have to
 * learn what the engine does to understand their own release.
 */
const APPROVAL_STATUS_I18N: Record<string, string> = {
  pending: "hostedApp.publishStatus.approvalState.pending",
  approved: "hostedApp.publishStatus.approvalState.approved",
  executing: "hostedApp.publishStatus.approvalState.executing",
  executed: "hostedApp.publishStatus.approvalState.approved",
  rejected: "hostedApp.publishStatus.approvalState.rejected",
  exception: "hostedApp.publishStatus.approvalState.exception",
  withdrawn: "hostedApp.publishStatus.approvalState.withdrawn",
  cancelled: "hostedApp.publishStatus.approvalState.cancelled",
  execute_failed: "hostedApp.publishStatus.approvalState.executeFailed",
}

export function approvalStatusI18nKey(status: string | undefined | null): string {
  return (
    APPROVAL_STATUS_I18N[String(status || "")] ??
    "hostedApp.publishStatus.approvalState.unknown"
  )
}

/** Badge colouring for an approval status; unknown statuses stay neutral. */
export function approvalStatusBadgeClass(status: string | undefined | null): string {
  switch (status) {
    case "approved":
    case "executed":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
    case "rejected":
    case "exception":
    case "execute_failed":
      return "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
    case "pending":
    case "executing":
      return "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
    default:
      return "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200"
  }
}

/**
 * Why the release is parked — the two causes need different remedies, so they
 * get different copy: capacity is "wait or ask for room", a failed start is
 * "read the logs and fix the application".
 */
export function pendingReasonI18nKey(
  reason: HostedAppPendingReason | null | undefined,
): string {
  return reason === "deploy_failed"
    ? "hostedApp.publishStatus.pendingDeployFailed"
    : "hostedApp.publishStatus.pendingCapacity"
}

/**
 * Settled outcome of one version record.
 *
 * Only the three values the backend ever latches; anything else — including the
 * common case of a version that has not been decided yet — returns `null` so
 * the caller decides what "no outcome" reads as in its own column.
 */
const VERSION_TERMINAL_STATE_I18N: Record<string, string> = {
  online: "hostedApp.versionList.outcomeOnline",
  rejected: "hostedApp.versionList.outcomeRejected",
  withdrawn: "hostedApp.versionList.outcomeWithdrawn",
}

export function versionTerminalStateI18nKey(
  terminalState: string | null | undefined,
): string | null {
  return VERSION_TERMINAL_STATE_I18N[String(terminalState || "")] ?? null
}

/**
 * Outcome word for the publish tab's version list, where a blank cell is not an
 * option: a version with no latched outcome is either staged to go live
 * (`is_pending`, written the moment approval passes) or still under approval,
 * and those two look identical in the row data while meaning opposite things to
 * whoever is waiting on them.
 */
export function versionOutcomeI18nKey(version: HostedAppVersion): string {
  return (
    versionTerminalStateI18nKey(version.terminal_state) ??
    (version.is_pending
      ? "hostedApp.versionList.outcomePendingOnline"
      : "hostedApp.versionList.outcomeInReview")
  )
}

/** Minimal identity a state action needs; both the card row and the detail payload provide it. */
export interface HostedAppRef {
  appId: string
  name: string
  state?: string | null
}
