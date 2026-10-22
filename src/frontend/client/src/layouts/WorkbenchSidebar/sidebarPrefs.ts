import { createLocalStore, useLocalStore } from '~/utils/localStore';
import type { WorkbenchNavSection } from '../useWorkbenchNavLinks';

/** An entry of the desktop sidebar's module area: a module, or 广场. */
export type SidebarEntryId = Exclude<WorkbenchNavSection, 'home'> | 'square' | 'capabilities';

/**
 * How the user arranged the desktop sidebar's module area (管理侧边栏): which entries are
 * hidden, and in what order the rest come. The nav shows at most four rows; what does not
 * fit, and what is hidden, is reached through 更多.
 *
 * Per-browser for now: there is no user-preference endpoint yet, so this lives in
 * localStorage and does not follow the account across devices.
 */
export interface SidebarPrefs {
  hidden: SidebarEntryId[];
  /** Entry ids in the user's order. Entries missing from it (new modules, a fresh
   *  grant) keep their default order, after the listed ones. Empty = default order. */
  order: SidebarEntryId[];
}

const DEFAULT_PREFS: SidebarPrefs = { hidden: [], order: [] };

const idList = (value: unknown): SidebarEntryId[] =>
  Array.isArray(value) ? value.filter((item): item is SidebarEntryId => typeof item === 'string') : [];

// v2: the first shape stored hub ids, one of which ('knowledge') now names a module.
const sidebarPrefsStore = createLocalStore<SidebarPrefs>('bs_workbench_sidebar_prefs_v2', DEFAULT_PREFS, (raw) => {
  const record = (raw ?? {}) as { hidden?: unknown; order?: unknown };
  return { hidden: idList(record.hidden), order: idList(record.order) };
});

export function useSidebarPrefs(): SidebarPrefs {
  return useLocalStore(sidebarPrefsStore);
}

/** 管理侧边栏 edits a draft and saves it whole. */
export function saveSidebarPrefs(next: SidebarPrefs) {
  sidebarPrefsStore.set(next);
}

export const DEFAULT_SIDEBAR_PREFS = DEFAULT_PREFS;

export function isDefaultSidebarPrefs(prefs: SidebarPrefs): boolean {
  return prefs.hidden.length === 0 && prefs.order.length === 0;
}

export function isSameSidebarPrefs(left: SidebarPrefs, right: SidebarPrefs): boolean {
  const sameSet = left.hidden.length === right.hidden.length && left.hidden.every((id) => right.hidden.includes(id));
  return sameSet && left.order.join() === right.order.join();
}
