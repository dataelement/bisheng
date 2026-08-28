/**
 * Whose choice is the stored tool selection — the user's, or nobody's.
 *
 * The input bar remembers which tool groups are switched on, per user, in
 * localStorage. That memory is only allowed to outrank the admin-configured
 * `default_checked` set once the user has ACTUALLY used the picker; a user who
 * never opened it must keep following the admin config, including changes made
 * after their first visit.
 *
 * Older builds persisted the selection unconditionally, so the first visit wrote
 * an empty snapshot for every user — and an empty snapshot then outranked the
 * admin default forever. The visible symptom was "后台配了默认工具，工作台一个
 *都没勾上", for every user who had opened the workbench even once before the
 * default was configured, i.e. all of them.
 *
 * Hence the marker key: a stored list counts as a real choice when the marker is
 * present. A legacy entry (no marker) is judged by its content — a non-empty
 * list can only have come from a real toggle, an empty one is the bug's
 * footprint and is discarded.
 */
const AGENT_TOOLS_KEY = 'selectedAgentTools';
const AGENT_TOOLS_TOUCHED_KEY = 'agentToolsTouched';
const TOUCHED_VALUE = '1';

/** Per-user `bs:` namespace, cleared wholesale on logout (AuthContext). */
function keyFor(userId: string | number, name: string): string {
  return `bs:${userId}:${name}`;
}

/**
 * Record that the user has used the tools picker.
 *
 * Lives in localStorage rather than a shared store value because Recoil is
 * frozen in this app; the marker is written where the choice is made (the
 * picker) and read where the selection is persisted and restored (ChatView),
 * and localStorage is the medium both already share.
 */
export function markAgentToolsTouched(userId: string | number | undefined): void {
  if (!userId) return;
  try {
    localStorage.setItem(keyFor(userId, AGENT_TOOLS_TOUCHED_KEY), TOUCHED_VALUE);
  } catch { /* private mode / quota — the selection simply is not remembered */ }
}

/** Whether this user has ever used the picker. */
export function hasTouchedAgentTools(userId: string | number | undefined): boolean {
  if (!userId) return false;
  try {
    return localStorage.getItem(keyFor(userId, AGENT_TOOLS_TOUCHED_KEY)) === TOUCHED_VALUE;
  } catch {
    return false;
  }
}

/**
 * The selection to restore for this user, or `null` when nothing stored is a
 * user choice and the admin defaults should seed instead. Adopting a legacy
 * entry also stamps the marker, so the emptiness rule below never has to judge
 * that user's stored list again.
 */
export function restoreAgentTools(userId: string | number | undefined): unknown[] | null {
  if (!userId) return null;
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(keyFor(userId, AGENT_TOOLS_KEY));
  } catch {
    return null;
  }
  const touched = hasTouchedAgentTools(userId);
  const saved = readStoredAgentTools(raw, touched);
  if (saved !== null && !touched) {
    markAgentToolsTouched(userId);
  }
  return saved;
}

/** Persist the current selection — only ever called once the user has chosen. */
export function persistAgentTools(userId: string | number | undefined, selection: unknown[]): void {
  if (!userId || !hasTouchedAgentTools(userId)) return;
  try {
    localStorage.setItem(keyFor(userId, AGENT_TOOLS_KEY), JSON.stringify(selection));
  } catch { /* private mode / quota — nothing to recover, the run is unaffected */ }
}

/**
 * The stored selection to restore, or `null` when nothing stored represents a
 * user choice and the admin defaults should seed instead.
 *
 * @param raw     the raw `selectedAgentTools` entry (`null` when absent)
 * @param touched whether the "user has used the picker" marker is present
 */
export function readStoredAgentTools(raw: string | null, touched: boolean): unknown[] | null {
  if (raw === null) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // A corrupt entry is not a choice; fall back to the admin defaults.
    return null;
  }
  if (!Array.isArray(parsed)) {
    return null;
  }
  // Empty + no marker = the legacy first-visit snapshot, not a decision.
  if (!touched && parsed.length === 0) {
    return null;
  }
  return parsed;
}
