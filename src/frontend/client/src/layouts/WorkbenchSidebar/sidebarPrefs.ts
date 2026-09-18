import { createLocalStore, useLocalStore } from '~/utils/localStore';
import type { WorkbenchHubId, WorkbenchNavSection } from '../useWorkbenchNavLinks';

/**
 * What the user chose to see in the desktop sidebar's module area. By default the modules
 * are folded into their hubs (知识资讯 / 智能拓展); a user may hide a hub (it moves under
 * 更多) or pin a single module as a row of its own.
 *
 * Per-browser for now: there is no user-preference endpoint yet, so this lives in
 * localStorage and does not follow the account across devices.
 */
export interface SidebarPrefs {
  hiddenHubs: WorkbenchHubId[];
  pinnedModules: WorkbenchNavSection[];
}

const DEFAULT_PREFS: SidebarPrefs = { hiddenHubs: [], pinnedModules: [] };

const stringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const sidebarPrefsStore = createLocalStore<SidebarPrefs>('bs_workbench_sidebar_prefs', DEFAULT_PREFS, (raw) => {
  const record = (raw ?? {}) as Record<string, unknown>;
  return {
    hiddenHubs: stringList(record.hiddenHubs) as WorkbenchHubId[],
    pinnedModules: stringList(record.pinnedModules) as WorkbenchNavSection[],
  };
});

const toggled = <T>(list: T[], item: T, on: boolean): T[] =>
  on ? (list.includes(item) ? list : [...list, item]) : list.filter((x) => x !== item);

export function useSidebarPrefs(): SidebarPrefs {
  return useLocalStore(sidebarPrefsStore);
}

export function setHubVisible(hub: WorkbenchHubId, visible: boolean) {
  sidebarPrefsStore.set((prev) => ({ ...prev, hiddenHubs: toggled(prev.hiddenHubs, hub, !visible) }));
}

export function setModulePinned(section: WorkbenchNavSection, pinned: boolean) {
  sidebarPrefsStore.set((prev) => ({ ...prev, pinnedModules: toggled(prev.pinnedModules, section, pinned) }));
}

export function resetSidebarPrefs() {
  sidebarPrefsStore.set(DEFAULT_PREFS);
}

export function isDefaultSidebarPrefs(prefs: SidebarPrefs): boolean {
  return prefs.hiddenHubs.length === 0 && prefs.pinnedModules.length === 0;
}
