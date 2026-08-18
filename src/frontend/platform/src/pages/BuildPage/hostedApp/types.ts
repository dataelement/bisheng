/**
 * UI-side vocabulary for hosted applications.
 *
 * The wire types live in `@/controllers/API/hostedApp`; what is here is the
 * mapping from those values to i18n keys and to the few UI predicates the card
 * and the detail page must agree on. Both surfaces import from here so a state
 * label never says two different things in two places.
 */
import type {
  HostedAppPhase,
  HostedAppState,
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

/** Minimal identity a state action needs; both the card row and the detail payload provide it. */
export interface HostedAppRef {
  appId: string
  name: string
  state?: string | null
}
