import { atom, selector } from 'recoil';
import type { AppItem } from '~/@types/app';

/** Search query for app center home page */
export const appSearchQueryState = atom<string>({
  key: 'appSearchQueryState',
  default: '',
});

/** Raw app list from frequently_used API */
export const recentAppsState = atom<AppItem[]>({
  key: 'recentAppsState',
  default: [],
});

/**
 * Filtered apps (search only).
 * Sorting (pin-first + time desc) is entirely handled by backend.
 * Frontend only filters by name/description for local search.
 */
export const filteredAppsSelector = selector<AppItem[]>({
  key: 'filteredAppsSelector',
  get: ({ get }) => {
    const apps = get(recentAppsState);
    const query = get(appSearchQueryState);

    if (!query) return apps; // Preserve backend order

    const q = query.toLowerCase();
    return apps.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        (a.description || '').toLowerCase().includes(q),
    );
  },
});
